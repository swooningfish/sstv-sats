import csv
import io
from datetime import datetime, timezone

import pytest

from sstv_sats.catalog import load_catalog, select
from sstv_sats.chirp import HEADER, chirp_rows, to_csv
from sstv_sats.ics import passes_to_ics
from sstv_sats.location import maidenhead_to_latlon
from sstv_sats.passes import predict_passes
from sstv_sats.tle import parse_tle_text

# Classic ISS element set from the Skyfield docs, so the tests run offline and stay deterministic.
ISS_TLE = """ISS (ZARYA)
1 25544U 98067A   14020.93268519  .00009878  00000-0  18200-3 0  5082
2 25544  51.6498 109.4756 0003572  55.9686 274.8005 15.49815350868473
"""


def test_catalog_loads_and_is_consistent():
    sats = load_catalog()
    assert len(sats) >= 14
    ids = [s.id for s in sats]
    assert len(ids) == len(set(ids))
    for s in sats:
        assert s.downlinks and all(100 < d.freq_mhz < 1000 for d in s.downlinks)
        assert len(s.short) <= 8
    assert any(not s.active for s in sats)  # Nanozond 1 has re-entered
    assert all(s.active for s in select(sats))


def test_select_by_name_and_id():
    sats = load_catalog()
    assert [s.id for s in select(sats, ["umka"])] == ["RS40S"]
    assert [s.id for s in select(sats, ["25544"])] == ["ISS"]


def test_chirp_csv_basic_doppler():
    sats = select(load_catalog(), ["RS40S", "ISS"])
    rows = chirp_rows(sats, doppler="basic", start=1)
    # RS40S: 3 UHF channels. ISS: 145.800 (1 VHF channel) + 437.550 (3 UHF channels).
    assert len(rows) == 7
    parsed = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert list(parsed[0].keys()) == HEADER
    assert [r["Frequency"] for r in parsed[:3]] == ["437.615000", "437.625000", "437.635000"]
    assert [r["Location"] for r in parsed] == [str(i) for i in range(1, 8)]
    assert all(len(r["Name"]) <= 8 for r in parsed)
    assert [r["Name"] for r in parsed[:3]] == ["RS40S-10", "RS40S", "RS40S+10"]
    assert all(r["Mode"] == "FM" and r["Duplex"] == "" for r in parsed)


def test_chirp_doppler_channels_ascend_minus_centre_plus():
    rows = chirp_rows(select(load_catalog(), ["RS40S"]), doppler="full")
    assert [r["Name"] for r in rows] == ["RS40S-10", "RS40S-5", "RS40S", "RS40S+5", "RS40S+10"]
    freqs = [float(r["Frequency"]) for r in rows]
    assert freqs == sorted(freqs)


def test_chirp_name_length_is_respected():
    rows = chirp_rows(select(load_catalog()), doppler="full", name_length=6)
    assert all(len(r["Name"]) <= 6 for r in rows)


def test_parse_tle_text():
    tles = parse_tle_text(ISS_TLE)
    assert list(tles) == [25544]
    assert tles[25544][0] == "ISS (ZARYA)"


@pytest.mark.parametrize("grid,lat,lon", [("IO91wm", 51.52, -0.125), ("FN31pr", 41.73, -72.71), ("JJ00aa", 0.02, 0.04)])
def test_maidenhead(grid, lat, lon):
    la, lo = maidenhead_to_latlon(grid)
    assert la == pytest.approx(lat, abs=0.03) and lo == pytest.approx(lon, abs=0.05)


def test_maidenhead_rejects_garbage():
    with pytest.raises(ValueError):
        maidenhead_to_latlon("ZZ99")


def test_predict_passes_offline():
    iss = select(load_catalog(), ["ISS"])
    start = datetime(2014, 1, 21, 0, 0, tzinfo=timezone.utc)
    passes = predict_passes(iss, parse_tle_text(ISS_TLE), 51.5, -0.12, start=start, hours=24, min_elevation=10)
    assert passes
    for p in passes:
        assert p.aos.time < p.tca.time < p.los.time
        assert p.max_elevation >= 10
        assert abs(p.aos.elevation) < 0.5 and abs(p.los.elevation) < 0.5
        assert 3 * 60 < p.duration.total_seconds() < 12 * 60
        # 145.8 MHz Doppler from the ISS is roughly +/-3.5 kHz
        assert 2000 < p.aos.doppler_hz(145.8) < 4000
        assert -4000 < p.los.doppler_hz(145.8) < -2000
    ics = passes_to_ics(passes)
    assert ics.count("BEGIN:VEVENT") == len(passes) and "TRIGGER:-PT10M" in ics
