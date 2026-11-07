"""ARISS SSTV events: scheduled slow-scan TV transmissions from the ISS (and occasionally other satellites).

ARISS publishes its schedule as free text on https://www.ariss.org/upcoming-sstv-events.html, newest
first, one block per announcement headed by the date it was posted, for example::

    2026-11-05 Expedition 75 Series 35 "Space Memories"
    Begins Monday, November 9 time TBD
    Concludes Monday, November 16, 2026 time TBD
    Images will be transmitted at 437.550 MHz (+/- Doppler shift) using Robot 36 SSTV mode for
    36 seconds transmission, two minutes off.
    Submit your original decoded images to the SSTV gallery for event certificate.

The page has no feed and no CORS headers, so it is read here (by the CLI and the daily site build)
and turned into structured events. The wording changes from post to post, so parsing is best-effort:
anything that can't be read is left blank, and the original text is kept in ``details``.
Corrections can be added by hand to ``ariss_events.json``, which overrides the parsed events.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Optional

from .tle import _get, cache_dir

EVENTS_URL = "https://www.ariss.org/upcoming-sstv-events.html"
GALLERY_URL = "https://ariss-usa.org/ARISS_SSTV/"
DEFAULT_MAX_AGE_HOURS = 6

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
# "November 9", "Nov.12, 2025", "Monday, November 16, 2026" or "01-December-2025".
_DATE_RES = [
    re.compile(_MON + r"\s*(?P<day>\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(?P<year>20\d\d))?", re.I),
    re.compile(r"\b(?P<day>\d{1,2})[- ]" + _MON + r"[- ](?P<year>20\d\d)", re.I),
    re.compile(r"\b(?P<year>20\d\d)-(?P<mon>\d\d)-(?P<day>\d\d)\b"),
]
# "15:30 UTC", "9:00 UTC", "1700 GMT", "17:05Z"
_TIME_RE = re.compile(r"\b(?P<h>\d{1,2}):?(?P<m>\d{2})\s*(?:UTC|GMT|Z)\b", re.I)
_START_RE = re.compile(r"\b(?:begin|begins|beginning|start|starts|starting|start time)\b", re.I)
_END_RE = re.compile(r"\b(?:end|ends|ending|conclude|concludes|concluding|stop)\b", re.I)
_HEADING_RE = re.compile(r"^\s*(?:(?P<y>20\d\d)-(?P<mo>\d\d)-(?P<d>\d\d)|(?P<mo2>\d\d)-(?P<d2>\d\d)-(?P<y2>20\d\d))\s+(?!TBD\b)(?P<title>[A-Za-z\"“].*)$")
# Undated announcements further down the page are headed by a line in capitals.
_CAPS_HEADING_RE = re.compile(r"^(?=.*[A-Z]{4}.*[A-Z]{4})[A-Z0-9 ,.:;'!&/\-]{20,}$")
_FREQ_RE = re.compile(r"\b(\d{3}\.\d{1,3})\s*MHz", re.I)
_MODE_RE = re.compile(r"\b(?:Robot\s*(?P<robot>\d+)|PD\s*-?\s*(?P<pd>\d+)|Martin\s*M?\s*(?P<martin>\d)|Scottie\s*(?P<scottie>S?\d|DX))\b", re.I)
_SERIES_RE = re.compile(r"\bSeries[\s-]*(\d+)\b", re.I)
_SAT_RE = re.compile(r"\bRS-?(\d{2})S\b", re.I)
_PAUSE_RE = re.compile(r"\b(?:pause|interrupt\w*|switched off|turned off|be off)\b", re.I)


def _parse_date(text: str):
    """First (year|None, month, day) in ``text`` and the index just after it, or None."""
    best = None
    for rx in _DATE_RES:
        m = rx.search(text)
        if m and (best is None or m.start() < best[0].start()):
            best = (m, rx)
    if not best:
        return None
    m = best[0]
    mon = m.group("mon")
    month = int(mon) if mon.isdigit() else MONTHS[mon[:3].lower()]
    year = int(m.group("year")) if m.group("year") else None
    return year, month, int(m.group("day")), m.end()


def _when(segment: str, posted: datetime, end_of_day: bool, after: Optional[datetime] = None):
    """Turn "Monday, November 9 time TBD" into (UTC datetime, time_known).

    With no year given, it is the year the announcement was posted (or, for an end date, the year
    the event starts), moved on a year if that would put it well in the past.
    """
    d = _parse_date(segment)
    if not d:
        return None, False
    year, month, day, d_end = d
    if year is None:
        ref, slack = (after, timedelta(days=1)) if after else (posted, timedelta(days=60))
        year = ref.year
        try:
            if datetime(year, month, day, tzinfo=timezone.utc) < ref - slack:
                year += 1
        except ValueError:
            return None, False
    # The time sits just before or just after its date ("00:01 UTC December 5", "May 8 10:30 UTC"),
    # never after a second date ("October 3: ... a pause October 4 from 10:00 UTC").
    near = segment[: d_end + 30]
    nxt = _parse_date(segment[d_end:d_end + 30])
    if nxt:
        near = segment[: d_end + nxt[3] - 6]
    t = _TIME_RE.search(near)
    try:
        if t and 0 <= int(t.group("h")) < 24 and 0 <= int(t.group("m")) < 60:
            return datetime(year, month, day, int(t.group("h")), int(t.group("m")), tzinfo=timezone.utc), True
        base = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None, False
    return (base + timedelta(hours=23, minutes=59) if end_of_day else base), False


def _find_when(text: str, keyword: re.Pattern, posted: datetime, end_of_day: bool, after: Optional[datetime] = None):
    """The first date that follows a start (or end) keyword within the same short phrase."""
    for m in keyword.finditer(text):
        seg = text[m.end(): m.end() + 90]
        # Don't run on into the other keyword's date ("Begins ... Concludes Monday, November 16").
        other = (_END_RE if keyword is _START_RE else _START_RE).search(seg)
        if other:
            seg = seg[: other.start()]
        when, known = _when(seg, posted, end_of_day, after)
        if when:
            return when, known
    return None, False


def _mode(text: str) -> str:
    m = _MODE_RE.search(text)
    if not m:
        return ""
    if m.group("robot"):
        n = m.group("robot")
        return f"Robot {'36' if n == '35' else n}"  # "Robot 35" is a typo seen on the page; there is no such mode
    if m.group("pd"):
        return f"PD{m.group('pd')}"
    if m.group("martin"):
        return f"Martin M{m.group('martin')}"
    return f"Scottie {m.group('scottie').upper()}"


def _schedule(text: str) -> str:
    m = re.search(r"\b(\d+)\s*sec\w*\b.{0,50}?\b(\d+(?:\s*-\s*\d+)?|one|two|three)\s*min\w*\s*(?:off|between)", text, re.I | re.S)
    if m:
        off = {"one": "1", "two": "2", "three": "3"}.get(m.group(2).lower(), m.group(2).replace(" ", ""))
        return f"{m.group(1)} s on / {off} min off"
    m = re.search(r"\b(\d+)\s*min\w*\s*on,?\s*(\d+)\s*min\w*\s*off", text, re.I)
    if m:
        return f"{m.group(1)} min on / {m.group(2)} min off"
    m = re.search(r"\b(\d+|one|two|three)\s*min\w*\s*between\s*(?:transmissions|images|pictures)", text, re.I)
    if m:
        gap = {"one": "1", "two": "2", "three": "3"}.get(m.group(1).lower(), m.group(1))
        return f"{gap} min between pictures"
    return ""


def html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", page)
    page = re.sub(r"(?i)<(br|/p|/div|/li|/h\d|/tr)\b[^>]*>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"[ \t\xa0​]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _blocks(text: str):
    """Split the page into (posted date, heading, body) announcements."""
    current = None
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            if current:
                yield current
            y, mo, d = (m.group("y"), m.group("mo"), m.group("d")) if m.group("y") else (m.group("y2"), m.group("mo2"), m.group("d2"))
            try:
                posted = datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
            except ValueError:
                current = None
                continue
            current = [posted, m.group("title").strip(), []]
        elif current and _CAPS_HEADING_RE.match(line):
            yield current
            current = [current[0], line.title().replace("Ariss", "ARISS").replace("Sstv", "SSTV"), []]
        elif current:
            current[2].append(line)
    if current:
        yield current


def _satellite(text: str):
    m = _SAT_RE.search(text)
    if m:
        sat_id = f"RS{m.group(1)}S"
        from .catalog import load_catalog

        for s in load_catalog():
            if s.id == sat_id:
                return s.id, s.name, s.norad_id
        return sat_id, sat_id, None
    return "ISS", "ISS", 25544


def parse_events(page: str) -> list:
    """Parse the ARISS "Upcoming SSTV events" page into event dicts, newest start first.

    Announcements about the same series (a first notice, then one with times, then updates) are
    merged: the most recent announcement wins, older ones fill in what it leaves out.
    """
    merged = {}
    for posted, heading, lines in _blocks(html_to_text(page)):
        body = "\n".join(lines)
        text = f"{heading}\n{body}"
        flat = re.sub(r"\s+", " ", text)
        start, start_known = _find_when(flat, _START_RE, posted, end_of_day=False)
        end, end_known = _find_when(flat, _END_RE, posted, end_of_day=True, after=start)
        series = _SERIES_RE.search(flat)
        sat_id, sat_name, norad = _satellite(flat)
        freq = _FREQ_RE.search(flat)
        theme = re.search(r"[\"“]([^\"”]{3,60})[\"”]", heading)
        title = re.sub(r"\s*[:\-]+\s*$", "", heading).replace("“", '"').replace("”", '"')
        ev = {
            "id": f"series-{series.group(1)}-{sat_id}" if series else None,
            "title": title,
            "series": int(series.group(1)) if series else None,
            "theme": theme.group(1).strip() if theme else "",
            "posted": posted.date().isoformat(),
            "start": start.isoformat() if start else None,
            "start_time_known": start_known,
            "end": end.isoformat() if end else None,
            "end_time_known": end_known,
            "satellite_id": sat_id,
            "satellite": sat_name,
            "norad_id": norad,
            "freq_mhz": float(freq.group(1)) if freq else None,
            "sstv_mode": _mode(flat),
            "schedule": _schedule(flat),
            "pauses": [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", body) if _PAUSE_RE.search(s)][:4],
            "submit_url": GALLERY_URL if re.search(r"gallery", flat, re.I) else "",
            "certificate": bool(re.search(r"certificate|award", flat, re.I)),
            "details": body[:800],
            "source_url": EVENTS_URL,
        }
        if ev["id"] is None:
            if not start:
                continue  # an update with nothing we can place in time
            ev["id"] = f"{start.date().isoformat()}-{sat_id}"
        old = merged.get(ev["id"])
        if old is None:
            merged[ev["id"]] = ev
            continue
        # Page is newest first, so ``old`` is the newer announcement: fill only its gaps.
        if re.search(r"\bupdate\b", old["title"], re.I) and not re.search(r"\bupdate\b", title, re.I):
            old["title"] = title  # keep the announcement's own name, not "Series 30 Update"
        for k, v in ev.items():
            if k in ("start", "end"):
                if old[k] is None or (not old[f"{k}_time_known"] and ev[f"{k}_time_known"] and old[k][:10] == (v or "")[:10]):
                    old[k], old[f"{k}_time_known"] = v, ev[f"{k}_time_known"]
            elif k in ("pauses",):
                old[k] = old[k] + [p for p in v if p not in old[k]]
            elif k in ("theme", "freq_mhz", "sstv_mode", "schedule", "submit_url", "series") and not old[k]:
                old[k] = v
            elif k == "certificate":
                old[k] = old[k] or v
    events = [e for e in merged.values() if e["start"]]
    for e in events:
        e["title"] = re.sub(r"\s*\bUpdate\b.*$", "", e["title"], flags=re.I) or e["title"]
        if not e["submit_url"] and e["satellite_id"] == "ISS":
            e["submit_url"] = GALLERY_URL  # every ARISS series has a gallery area for decodes
    events.sort(key=lambda e: e["start"], reverse=True)
    return events


def curated_events() -> list:
    """Hand-entered events and corrections from ariss_events.json (same keys as parsed events)."""
    try:
        data = json.loads(resources.files("sstv_sats").joinpath("ariss_events.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return data.get("events", [])


def merge_curated(events: list, curated: list) -> list:
    by_id = {e["id"]: e for e in events}
    for c in curated:
        base = by_id.get(c["id"], {"source_url": EVENTS_URL, "pauses": [], "details": ""})
        by_id[c["id"]] = {**base, **c}
    return sorted(by_id.values(), key=lambda e: e.get("start") or "", reverse=True)


def get_events(offline: bool = False, max_age_hours: float = DEFAULT_MAX_AGE_HOURS, quiet: bool = False) -> dict:
    """{"fetched": iso time or None, "source": url, "events": [...]}, cached like the TLEs."""
    cached = cache_dir() / "ariss_sstv_events.html"
    fresh = cached.exists() and (time.time() - cached.stat().st_mtime) < max_age_hours * 3600
    if not fresh and not offline:
        try:
            cached.write_text(_get(EVENTS_URL), encoding="utf-8")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if not quiet:
                print(f"warning: could not download the ARISS SSTV schedule: {exc}", file=sys.stderr)
    events, fetched = [], None
    if cached.exists():
        events = parse_events(cached.read_text(encoding="utf-8"))
        fetched = datetime.fromtimestamp(cached.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return {"fetched": fetched, "source": EVENTS_URL, "gallery": GALLERY_URL,
            "events": merge_curated(events, curated_events())}


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def status(event: dict, now: Optional[datetime] = None) -> str:
    """"upcoming", "active" or "ended". An event with no end date is treated as lasting a day."""
    now = now or datetime.now(timezone.utc)
    start = _dt(event.get("start"))
    end = _dt(event.get("end")) or (start + timedelta(days=1) if start else None)
    if start and now < start:
        return "upcoming"
    if end and now <= end:
        return "active"
    return "ended"


def window(event: dict):
    """(start, end) UTC datetimes covering the event, whole days when the times are still TBD."""
    start = _dt(event["start"])
    end = _dt(event.get("end")) or start + timedelta(days=1)
    return start, end


def current_or_next(events: list, now: Optional[datetime] = None) -> Optional[dict]:
    live = [e for e in events if status(e, now) != "ended"]
    return min(live, key=lambda e: e["start"]) if live else None
