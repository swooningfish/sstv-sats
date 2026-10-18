"""Observer location helpers (lat/lon or Maidenhead locator)."""

from __future__ import annotations

import re


def maidenhead_to_latlon(grid: str) -> tuple:
    """Return the centre (lat, lon) of a 4-, 6- or 8-character Maidenhead locator, e.g. IO91wm."""
    g = grid.strip()
    if not re.fullmatch(r"[A-Ra-r]{2}([0-9]{2}([A-Xa-x]{2}([0-9]{2})?)?)?", g) or len(g) < 4:
        raise ValueError(f"not a valid Maidenhead locator: {grid!r}")
    g = g[:2].upper() + g[2:4] + g[4:6].lower() + g[6:8]
    lon = (ord(g[0]) - ord("A")) * 20 - 180
    lat = (ord(g[1]) - ord("A")) * 10 - 90
    lon += int(g[2]) * 2
    lat += int(g[3])
    lon_size, lat_size = 2.0, 1.0
    if len(g) >= 6:
        lon_size, lat_size = 2 / 24, 1 / 24
        lon += (ord(g[4]) - ord("a")) * lon_size
        lat += (ord(g[5]) - ord("a")) * lat_size
    if len(g) >= 8:
        lon_size, lat_size = lon_size / 10, lat_size / 10
        lon += int(g[6]) * lon_size
        lat += int(g[7]) * lat_size
    return lat + lat_size / 2, lon + lon_size / 2
