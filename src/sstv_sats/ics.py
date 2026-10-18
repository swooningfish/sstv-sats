"""iCalendar export so passes (with reminders) show up in any calendar app."""

from __future__ import annotations

from datetime import datetime, timezone

from .passes import compass


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def passes_to_ics(passes: list, alarm_minutes: int = 10) -> str:
    now = _fmt(datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sstv-sats//SSTV satellite passes//EN", "CALSCALE:GREGORIAN"]
    for p in passes:
        freqs = " / ".join(f"{d.freq_mhz:.3f} MHz" for d in p.sat.downlinks)
        desc = (
            f"Downlink: {freqs}\n"
            f"AOS {p.aos.time:%H:%M:%S}Z az {p.aos.azimuth:.0f} ({compass(p.aos.azimuth)})\n"
            f"TCA {p.tca.time:%H:%M:%S}Z max el {p.max_elevation:.0f} az {p.tca.azimuth:.0f}\n"
            f"LOS {p.los.time:%H:%M:%S}Z az {p.los.azimuth:.0f} ({compass(p.los.azimuth)})"
        )
        if p.sat.notes:
            desc += f"\n{p.sat.notes}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{p.sat.norad_id}-{_fmt(p.aos.time)}@sstv-sats",
            f"DTSTAMP:{now}",
            f"DTSTART:{_fmt(p.aos.time)}",
            f"DTEND:{_fmt(p.los.time)}",
            f"SUMMARY:{_escape(f'SSTV {p.sat.label} {p.max_elevation:.0f}° {p.sat.primary.freq_mhz:.3f}')}",
            f"DESCRIPTION:{_escape(desc)}",
        ]
        if alarm_minutes:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(p.sat.label + ' pass soon')}",
                      f"TRIGGER:-PT{int(alarm_minutes)}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
