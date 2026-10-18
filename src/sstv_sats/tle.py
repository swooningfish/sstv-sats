"""Download and cache orbital elements (TLEs) from CelesTrak."""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

from . import __version__

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=TLE"
# Fallback for objects CelesTrak doesn't carry (new launches with temporary 98xxx IDs, etc.).
SATNOGS_URL = "https://db.satnogs.org/api/tle/?norad_cat_id={norad}&format=json"
USER_AGENT = f"sstv-sats/{__version__} (+https://github.com/swooningfish/sstv-sats)"
DEFAULT_MAX_AGE_HOURS = 12  # CelesTrak updates a few times a day; please don't hammer it.


def cache_dir() -> Path:
    env = os.environ.get("SSTV_SATS_CACHE")
    path = Path(env) if env else Path.home() / ".cache" / "sstv-sats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_tle_text(text: str) -> dict:
    """Parse 2- or 3-line TLE text into {norad_id: (name, line1, line2)}."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    out = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            name, l1, l2 = "", lines[i], lines[i + 1]
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue
        out[int(l1[2:7])] = (name, l1, l2)
    return out


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def _download(norad: int) -> Optional[str]:
    try:
        text = _get(CELESTRAK_URL.format(norad=norad))
        if norad in parse_tle_text(text):
            return text
    except urllib.error.HTTPError as exc:  # CelesTrak answers 404 for objects it doesn't carry
        if exc.code != 404:
            raise
    import json

    for item in json.loads(_get(SATNOGS_URL.format(norad=norad))):
        text = "\n".join((item["tle0"], item["tle1"], item["tle2"])) + "\n"
        if norad in parse_tle_text(text):
            return text
    return None


def get_tles(
    norad_ids: Iterable[int],
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    offline: bool = False,
    tle_file: Optional[Path] = None,
    quiet: bool = False,
) -> dict:
    """Return {norad_id: (name, line1, line2)}, using the cache where it is fresh enough.

    A user-supplied ``tle_file`` takes priority. If a download fails the stale cached copy
    is used with a warning, so the tool keeps working offline.
    """
    def warn(msg):
        if not quiet:
            print(f"warning: {msg}", file=sys.stderr)

    ids = [n for n in norad_ids if n]
    result = {}
    if tle_file:
        parsed = parse_tle_text(Path(tle_file).read_text(encoding="utf-8"))
        result.update({n: parsed[n] for n in ids if n in parsed})
    for norad in ids:
        if norad in result:
            continue
        cached = cache_dir() / f"{norad}.tle"
        fresh = cached.exists() and (time.time() - cached.stat().st_mtime) < max_age_hours * 3600
        if not fresh and not offline:
            try:
                text = _download(norad)
                if text:
                    cached.write_text(text, encoding="utf-8")
                else:
                    warn(f"neither CelesTrak nor SatNOGS has current elements for NORAD {norad} (decayed or not yet catalogued?)")
            except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
                warn(f"could not download TLE for NORAD {norad}: {exc}")
        if cached.exists():
            parsed = parse_tle_text(cached.read_text(encoding="utf-8"))
            if norad in parsed:
                result[norad] = parsed[norad]
    return result


def tle_epoch_age_days(line1: str) -> float:
    """Age of a TLE in days, from the epoch field of line 1."""
    from datetime import datetime, timedelta, timezone

    yy = int(line1[18:20])
    year = 2000 + yy if yy < 57 else 1900 + yy
    epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(line1[20:32]) - 1)
    return (datetime.now(timezone.utc) - epoch).total_seconds() / 86400
