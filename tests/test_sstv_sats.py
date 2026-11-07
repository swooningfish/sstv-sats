import csv
import io
from datetime import datetime, timezone

import pytest

from sstv_sats.catalog import load_catalog, select
from sstv_sats.chirp import DOPPLER_PROFILES, HEADER, chirp_layout, chirp_rows, to_csv
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


def test_sstv_modes_flow_into_chirp_comments():
    sats = {s.id: s for s in load_catalog()}
    assert sats["RS58S"].primary.sstv_mode == "Robot 36"
    assert sats["SONATE-2"].primary.sstv_mode == "Martin M1"
    rows = chirp_rows([sats["RS38S"]], doppler="none")
    assert rows[0]["Comment"].endswith("Robot 72")


def test_select_by_name_and_id():
    sats = load_catalog()
    assert [s.id for s in select(sats, ["umka"])] == ["RS40S"]
    assert [s.id for s in select(sats, ["25544"])] == ["ISS"]


def test_chirp_csv_basic_doppler():
    sats = select(load_catalog(), ["RS40S", "ISS"])
    rows = chirp_rows(sats, doppler="basic", start=1)
    # RS40S: 5 UHF channels. ISS: 145.800 (1 VHF channel) + 437.550 (5 UHF channels).
    assert len(rows) == 11
    parsed = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert list(parsed[0].keys()) == HEADER
    assert [r["Frequency"] for r in parsed[:5]] == ["437.615000", "437.620000", "437.625000", "437.630000", "437.635000"]
    assert [r["Location"] for r in parsed] == [str(i) for i in range(1, 12)]
    assert all(len(r["Name"]) <= 8 for r in parsed)
    assert [r["Name"] for r in parsed[:5]] == ["RS40S-10", "RS40S-5", "RS40S", "RS40S+5", "RS40S+10"]
    assert all(r["Mode"] == "FM" and r["Duplex"] == "" for r in parsed)


def test_chirp_doppler_channels_ascend_minus_centre_plus():
    rows = chirp_rows(select(load_catalog(), ["RS40S"]), doppler="full")
    assert [r["Name"] for r in rows] == ["RS40S-10", "RS40S-5", "RS40S", "RS40S+5", "RS40S+10"]
    freqs = [float(r["Frequency"]) for r in rows]
    assert freqs == sorted(freqs)


@pytest.mark.parametrize("profile", list(DOPPLER_PROFILES))
def test_chirp_layout_matches_csv_rows(profile):
    sats = select(load_catalog())
    rows = chirp_rows(sats, doppler=profile, start=1)
    layout = chirp_layout(sats, doppler=profile)
    by_location = {r["Location"]: r for r in rows}
    seen = []
    for sat in sats:
        for i, dl in enumerate(sat.downlinks):
            for off, n in layout[sat.id][i]:
                row = by_location[n + 1]
                assert float(row["Frequency"]) == pytest.approx(dl.freq_mhz + off / 1000)
                seen.append(n)
    assert sorted(seen) == list(range(len(rows)))


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


# A trimmed copy of https://www.ariss.org/upcoming-sstv-events.html (November 2026), newest first.
ARISS_PAGE = """<html><body><div class="paragraph">
<strong>2026-11-05 Expedition 75 Series 35 "Space Memories"</strong><br>
Begins Monday, November 9 time TBD<br>
Concludes Monday, November 16, 2026 time TBD<br>
Images will be transmitted at 437.550 MHz (+/- Doppler shift) using Robot 35 SSTV mode for 36 seconds
transmission, two minutes off.<br>
Submit your original decoded images to the SSTV gallery for event certificate.<br>
<strong>2026-10-19 Expedition 75 Series 34 "ARISS Hardware"</strong><br>
Begins Thursday October 22 15:30 UTC<br>
Concludes Monday October 26 time 17:45 UTC<br>
Images will be transmitted at 437.55 MHz (+/- Doppler shift), decode with Robot 36 mode, transmission 36 seconds on, two minutes off.<br>
<strong>2026-04-09 SSTV Series 31 commemorates several space achievements</strong><br>
The SSTV event should begin shortly after 11:15 UTC on April 10.<br>
The SSTV event should conclude around 13:55 UTC on April 14.<br>
<strong>2026-03-24 SSTV Series 31 commemorates several space achievements</strong><br>
Start: April 10 (start time TBD)<br>End: April 14 (end time TBD)<br>Frequency: 437.55 MHz<br>
SSTV Mode: Robot 36 with 2 minutes between transmissions.<br>
<strong>12-04-2025 SSTV Series 30 Update:</strong><br>
The RS-38S SSTV retread of the Series 30 SSTV campaign is scheduled to start at 00:01 UTC December 5.
The campaign will conclude at 23:59 UTC December 13.<br>
Frequency: 437.825 MHz Mode: Robot 36 Timing: 36 seconds on, 2-3 minutes off<br>
</div></body></html>"""


def test_ariss_events_parse():
    from sstv_sats.ariss import parse_events

    ev = {e["id"]: e for e in parse_events(ARISS_PAGE)}
    s35 = ev["series-35-ISS"]
    assert s35["theme"] == "Space Memories" and s35["series"] == 35
    assert s35["start"] == "2026-11-09T00:00:00+00:00" and not s35["start_time_known"]
    assert s35["end"] == "2026-11-16T23:59:00+00:00" and not s35["end_time_known"]
    assert s35["freq_mhz"] == 437.55 and s35["sstv_mode"] == "Robot 36"  # "Robot 35" on the page is a typo
    assert s35["schedule"] == "36 s on / 2 min off"
    assert s35["submit_url"] == "https://ariss-usa.org/ARISS_SSTV/" and s35["certificate"]
    s34 = ev["series-34-ISS"]
    assert (s34["start"], s34["end"]) == ("2026-10-22T15:30:00+00:00", "2026-10-26T17:45:00+00:00")
    assert s34["start_time_known"] and s34["end_time_known"]
    # Two announcements of Series 31 are merged: times from the newer one, mode from the older one.
    s31 = ev["series-31-ISS"]
    assert s31["start"] == "2026-04-10T11:15:00+00:00" and s31["end"] == "2026-04-14T13:55:00+00:00"
    assert s31["sstv_mode"] == "Robot 36" and s31["schedule"] == "2 min between pictures"
    rs = ev["series-30-RS38S"]
    assert rs["norad_id"] == 57189 and rs["freq_mhz"] == 437.825 and rs["title"] == "SSTV Series 30"
    assert rs["start"] == "2025-12-05T00:01:00+00:00" and rs["schedule"] == "36 s on / 2-3 min off"


def test_ariss_status_and_window():
    from sstv_sats.ariss import current_or_next, parse_events, status, window

    events = parse_events(ARISS_PAGE)
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    nxt = current_or_next(events, now)
    assert nxt["id"] == "series-35-ISS" and status(nxt, now) == "upcoming"
    assert status(nxt, datetime(2026, 11, 12, tzinfo=timezone.utc)) == "active"
    assert status(nxt, datetime(2026, 11, 17, tzinfo=timezone.utc)) == "ended"
    start, end = window(nxt)
    assert (end - start).days == 7


def test_ariss_curated_overrides():
    from sstv_sats.ariss import merge_curated, parse_events

    merged = merge_curated(parse_events(ARISS_PAGE), [{"id": "series-35-ISS", "start": "2026-11-09T10:00:00+00:00", "start_time_known": True}])
    s35 = next(e for e in merged if e["id"] == "series-35-ISS")
    assert s35["start"] == "2026-11-09T10:00:00+00:00" and s35["start_time_known"] and s35["freq_mhz"] == 437.55


def test_cli_time_window(monkeypatch):
    from sstv_sats import cli

    args = cli.build_parser().parse_args(["passes", "--grid", "IO91wm", "--start", "2026-11-09T10:00Z", "--end", "2026-11-10T04:00Z"])
    start, hours, wanted = cli._resolve_window(args)
    assert start == datetime(2026, 11, 9, 10, tzinfo=timezone.utc) and hours == 18 and wanted is None
    bad = cli.build_parser().parse_args(["passes", "--grid", "IO91wm", "--start", "2026-11-10", "--end", "2026-11-09"])
    with pytest.raises(SystemExit):
        cli._resolve_window(bad)
