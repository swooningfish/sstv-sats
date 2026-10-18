"""Pass prediction with Skyfield (SGP4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from skyfield.api import EarthSatellite, load, wgs84

from .catalog import Satellite

C_KM_S = 299_792.458
_ts = None


def timescale():
    global _ts
    if _ts is None:
        _ts = load.timescale(builtin=True)
    return _ts


@dataclass
class Point:
    time: datetime
    elevation: float
    azimuth: float
    range_km: float
    range_rate_km_s: float

    def doppler_hz(self, freq_mhz: float) -> float:
        return -freq_mhz * 1e6 * self.range_rate_km_s / C_KM_S


@dataclass
class Pass:
    sat: Satellite
    aos: Point
    tca: Point
    los: Point
    in_progress: bool = False
    tle_age_days: Optional[float] = None
    extra: dict = field(default_factory=dict)

    @property
    def max_elevation(self) -> float:
        return self.tca.elevation

    @property
    def duration(self) -> timedelta:
        return self.los.time - self.aos.time

    def to_dict(self) -> dict:
        f = self.sat.primary.freq_mhz

        def pt(p: Point):
            return {
                "time": p.time.isoformat(),
                "elevation": round(p.elevation, 1),
                "azimuth": round(p.azimuth, 1),
                "range_km": round(p.range_km, 1),
                "doppler_hz": round(p.doppler_hz(f)),
            }

        return {
            "satellite": self.sat.label,
            "id": self.sat.id,
            "norad_id": self.sat.norad_id,
            "downlinks_mhz": [d.freq_mhz for d in self.sat.downlinks],
            "aos": pt(self.aos),
            "tca": pt(self.tca),
            "los": pt(self.los),
            "max_elevation": round(self.max_elevation, 1),
            "duration_s": int(self.duration.total_seconds()),
            "in_progress": self.in_progress,
            "tle_age_days": None if self.tle_age_days is None else round(self.tle_age_days, 1),
        }


def _point(sat_obj, observer, t) -> Point:
    topo = (sat_obj - observer).at(t)
    alt, az, dist, _, _, range_rate = topo.frame_latlon_and_rates(observer)
    return Point(
        time=t.utc_datetime(),
        elevation=alt.degrees,
        azimuth=az.degrees,
        range_km=dist.km,
        range_rate_km_s=range_rate.km_per_s,
    )


def predict_passes(
    sats: Iterable[Satellite],
    tles: dict,
    lat: float,
    lon: float,
    alt_m: float = 0.0,
    start: Optional[datetime] = None,
    hours: float = 24.0,
    min_elevation: float = 10.0,
    horizon: float = 0.0,
) -> list:
    """Predict passes above ``horizon`` whose peak elevation is at least ``min_elevation``.

    AOS/LOS are the horizon crossings (when the signal can first/last be heard); passes
    already under way at ``start`` are included and flagged ``in_progress``.
    """
    from .tle import tle_epoch_age_days

    ts = timescale()
    start = start or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(start + timedelta(hours=hours))
    observer = wgs84.latlon(lat, lon, elevation_m=alt_m)

    passes = []
    for sat in sats:
        if sat.norad_id not in tles:
            continue
        name, l1, l2 = tles[sat.norad_id]
        sat_obj = EarthSatellite(l1, l2, name or sat.name, ts)
        age = tle_epoch_age_days(l1)
        times, events = sat_obj.find_events(observer, t0, t1, altitude_degrees=horizon)

        current = None
        if len(events) and events[0] != 0 and _point(sat_obj, observer, t0).elevation > horizon:
            current = {"aos": t0, "culm": [], "in_progress": True}
        for t, ev in zip(times, events):
            if ev == 0:
                current = {"aos": t, "culm": [], "in_progress": False}
            elif current is None:
                continue
            elif ev == 1:
                current["culm"].append(t)
            elif ev == 2:
                aos = _point(sat_obj, observer, current["aos"])
                los = _point(sat_obj, observer, t)
                peaks = [_point(sat_obj, observer, c) for c in current["culm"]] or [aos]
                tca = max(peaks, key=lambda p: p.elevation)
                if tca.elevation >= min_elevation:
                    passes.append(Pass(sat, aos, tca, los, current["in_progress"], age))
                current = None
    passes.sort(key=lambda p: p.aos.time)
    return passes


def compass(az: float) -> str:
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return points[int((az % 360) / 22.5 + 0.5) % 16]
