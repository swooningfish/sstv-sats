"""Command-line interface: ``sstv-sats <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .catalog import load_catalog, select
from .chirp import DOPPLER_PROFILES, chirp_rows, to_csv
from .location import maidenhead_to_latlon
from .tle import get_tles

EPILOG = "Location can also come from env vars SSTV_LAT / SSTV_LON / SSTV_ALT or SSTV_GRID."


def _add_location(p):
    g = p.add_argument_group("location")
    g.add_argument("--lat", type=float, default=_env_float("SSTV_LAT"), help="latitude, decimal degrees (north +)")
    g.add_argument("--lon", type=float, default=_env_float("SSTV_LON"), help="longitude, decimal degrees (east +, west -)")
    g.add_argument("--alt", type=float, default=_env_float("SSTV_ALT") or 0.0, help="height above sea level, metres")
    g.add_argument("--grid", default=os.environ.get("SSTV_GRID"), help="Maidenhead locator instead of lat/lon, e.g. IO91wm")


def _add_prediction(p):
    _add_location(p)
    g = p.add_argument_group("prediction")
    g.add_argument("--hours", type=float, default=24, help="how far ahead to look (default 24)")
    g.add_argument("--min-el", type=float, default=10, help="ignore passes peaking below this elevation (default 10)")
    g.add_argument("--sat", nargs="+", metavar="SAT", help="only these satellites (id, name or NORAD id)")
    g.add_argument("--tle-file", type=Path, help="use this TLE file instead of downloading")
    g.add_argument("--offline", action="store_true", help="don't download; use cached TLEs only")


def _env_float(name):
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else None


def _resolve_location(args):
    if args.grid:
        lat, lon = maidenhead_to_latlon(args.grid)
        return lat, lon, args.alt
    if args.lat is None or args.lon is None:
        sys.exit("error: give --lat and --lon (or --grid). " + EPILOG)
    if not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        sys.exit("error: latitude must be -90..90 and longitude -180..180")
    return args.lat, args.lon, args.alt


def _predict(args, start=None, quiet=False):
    from .passes import predict_passes

    lat, lon, alt = _resolve_location(args)
    sats = select(load_catalog(), args.sat)
    if not sats:
        sys.exit("error: no matching satellites (see `sstv-sats list`)")
    tles = get_tles([s.norad_id for s in sats], tle_file=args.tle_file, offline=args.offline, quiet=quiet)
    missing = [s.label for s in sats if s.norad_id not in tles]
    if missing and not quiet:
        print(f"warning: no orbital elements for: {', '.join(missing)}", file=sys.stderr)
    passes = predict_passes(sats, tles, lat, lon, alt, start=start, hours=args.hours, min_elevation=args.min_el)
    return passes, (lat, lon, alt)


def _local(dt: datetime, utc: bool) -> datetime:
    return dt.astimezone(timezone.utc) if utc else dt.astimezone()


def _doppler_khz(p, point):
    return point.doppler_hz(p.sat.primary.freq_mhz) / 1000


def cmd_list(args):
    for s in load_catalog():
        freqs = " / ".join(f"{d.freq_mhz:.3f}" for d in s.downlinks)
        status = "" if s.active else "  [inactive]"
        print(f"{s.id:<10} {s.name:<20} NORAD {str(s.norad_id):<6} {freqs} MHz{status}")
        if s.notes and args.verbose:
            print(f"{'':<10} {s.notes}")


def cmd_chirp(args):
    sats = select(load_catalog(), args.sat, include_inactive=args.include_inactive)
    rows = chirp_rows(sats, doppler=args.doppler, start=args.start, name_length=args.name_length,
                      all_downlinks=not args.primary_only)
    text = to_csv(rows)
    if args.output == "-":
        sys.stdout.write(text)
    else:
        Path(args.output).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {len(rows)} channels to {args.output}", file=sys.stderr)


def cmd_passes(args):
    from .passes import compass

    passes, (lat, lon, _) = _predict(args)
    if args.json:
        print(json.dumps([p.to_dict() for p in passes], indent=2))
        return
    tz = "UTC" if args.utc else datetime.now().astimezone().tzname()
    print(f"SSTV passes for {lat:.4f}, {lon:.4f} - next {args.hours:g} h, max elevation >= {args.min_el:g} deg, times {tz}\n")
    if not passes:
        print("No passes found. Try --hours 48 or a lower --min-el.")
        return
    print(f"{'Satellite':<22} {'Freq MHz':>8}  {'Date':<10} {'AOS':>8} {'Az':>4}  {'TCA':>8} {'MaxEl':>5} {'Az':>4}  {'LOS':>8} {'Az':>4}  {'Dur':>5}  Doppler kHz AOS/TCA/LOS")
    for p in passes:
        a, t, l = (_local(x.time, args.utc) for x in (p.aos, p.tca, p.los))
        dur = int(p.duration.total_seconds())
        dop = "/".join(f"{_doppler_khz(p, x):+.1f}" for x in (p.aos, p.tca, p.los))
        flag = " (now!)" if p.in_progress else ""
        print(f"{p.sat.label[:22]:<22} {p.sat.primary.freq_mhz:>8.3f}  {a:%Y-%m-%d} {a:%H:%M:%S} {compass(p.aos.azimuth):>4}  "
              f"{t:%H:%M:%S} {p.max_elevation:>5.0f} {compass(p.tca.azimuth):>4}  {l:%H:%M:%S} {compass(p.los.azimuth):>4}  "
              f"{dur // 60:>2}:{dur % 60:02d}  {dop}{flag}")
    stale = {p.sat.label for p in passes if p.tle_age_days and p.tle_age_days > 14}
    if stale:
        print(f"\nnote: TLEs older than 14 days for {', '.join(sorted(stale))} - predictions may be off by minutes.")


def cmd_ics(args):
    from .ics import passes_to_ics

    passes, _ = _predict(args)
    Path(args.output).write_text(passes_to_ics(passes, args.alarm), encoding="utf-8", newline="")
    print(f"wrote {len(passes)} passes to {args.output}", file=sys.stderr)


def cmd_watch(args):
    from . import notify
    from .passes import compass

    notifiers = [notify.Console()]
    notifiers += [notify.Ntfy(t) for t in args.ntfy or []]
    notifiers += [notify.Webhook(u) for u in args.webhook or []]
    lat, lon, _ = _resolve_location(args)
    print(f"Watching for SSTV passes over {lat:.4f}, {lon:.4f} (alert {args.lead:g} min before AOS, "
          f"max el >= {args.min_el:g}). Ctrl+C to stop.", flush=True)
    if args.test_alert:
        notify.broadcast(notifiers, "sstv-sats test alert", "If you can read this, alerts are working.")

    alerted, aos_alerted = set(), set()
    passes, refreshed = [], None
    try:
        while True:
            now = datetime.now(timezone.utc)
            if refreshed is None or now - refreshed > timedelta(hours=1):
                passes, _ = _predict(args, quiet=refreshed is not None)
                refreshed = now
                upcoming = [p for p in passes if p.aos.time > now]
                if upcoming:
                    nxt = upcoming[0]
                    print(f"[{_local(now, args.utc):%H:%M}] {len(passes)} passes in next {args.hours:g} h; next: "
                          f"{nxt.sat.label} at {_local(nxt.aos.time, args.utc):%a %H:%M}", flush=True)
            for p in passes:
                key = (p.sat.norad_id, p.aos.time)
                mins = (p.aos.time - now).total_seconds() / 60
                if key not in alerted and 0 < mins <= args.lead:
                    alerted.add(key)
                    freqs = " / ".join(f"{d.freq_mhz:.3f}" for d in p.sat.downlinks)
                    msg = (f"{p.sat.label} in {mins:.0f} min on {freqs} MHz\n"
                           f"AOS {_local(p.aos.time, args.utc):%H:%M:%S} {compass(p.aos.azimuth)} -> "
                           f"max {p.max_elevation:.0f} deg {compass(p.tca.azimuth)} at {_local(p.tca.time, args.utc):%H:%M} -> "
                           f"LOS {_local(p.los.time, args.utc):%H:%M:%S} {compass(p.los.azimuth)}\n"
                           f"Doppler: tune {_doppler_khz(p, p.aos):+.1f} kHz at AOS, {_doppler_khz(p, p.los):+.1f} kHz at LOS")
                    notify.broadcast(notifiers, f"SSTV pass: {p.sat.label} ({p.max_elevation:.0f} deg)", msg)
                if args.aos_alert and key not in aos_alerted and -1 < mins <= 0:
                    aos_alerted.add(key)
                    notify.broadcast(notifiers, f"AOS now: {p.sat.label}", f"{p.sat.primary.freq_mhz:.3f} MHz - start recording!")
            if args.once:
                return
            time.sleep(20)
    except KeyboardInterrupt:
        print("stopped.")


def cmd_update_tle(args):
    sats = select(load_catalog())
    tles = get_tles([s.norad_id for s in sats], max_age_hours=0)
    from .tle import tle_epoch_age_days

    for s in sats:
        if s.norad_id in tles:
            print(f"{s.label:<24} NORAD {s.norad_id:<6} TLE age {tle_epoch_age_days(tles[s.norad_id][1]):.1f} days")
        else:
            print(f"{s.label:<24} NORAD {s.norad_id:<6} no TLE available")


def cmd_build_site(args):
    from .site import build_site

    out = build_site(args.output, tle_file=args.tle_file, offline=args.offline)
    print(f"site built in {out}", file=sys.stderr)


def cmd_serve(args):
    import functools
    import http.server
    import tempfile

    from .site import build_site

    out = build_site(Path(tempfile.mkdtemp(prefix="sstv-sats-site-")) / "site", offline=args.offline)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving the SSTV pass predictor on http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/ "
              "(Ctrl+C to stop)", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("stopped.")


def build_parser():
    ap = argparse.ArgumentParser(prog="sstv-sats", description="SSTV satellite pass predictor, alerts and CHIRP export.", epilog=EPILOG)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="show the satellite catalogue")
    p.add_argument("-v", "--verbose", action="store_true", help="include notes")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("chirp", help="write a CHIRP CSV of SSTV downlink channels")
    p.add_argument("-o", "--output", default="sstv_satellites_chirp.csv", help="output file, or - for stdout")
    p.add_argument("--doppler", choices=list(DOPPLER_PROFILES), default="basic",
                   help="extra Doppler channels: none, basic (70cm +/-10 kHz) or full (+/-5 & 10 kHz, 2m +/-5) (default basic)")
    p.add_argument("--start", type=int, default=1, help="first memory location (default 1)")
    p.add_argument("--name-length", type=int, default=8, help="max channel-name length for your radio (default 8)")
    p.add_argument("--sat", nargs="+", metavar="SAT", help="only these satellites")
    p.add_argument("--primary-only", action="store_true", help="only the first downlink per satellite (e.g. ISS 145.800)")
    p.add_argument("--include-inactive", action="store_true", help="include decayed / inactive satellites")
    p.set_defaults(func=cmd_chirp)

    p = sub.add_parser("passes", help="list upcoming passes for your location", epilog=EPILOG)
    _add_prediction(p)
    p.add_argument("--utc", action="store_true", help="show times in UTC instead of local time")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_passes)

    p = sub.add_parser("ics", help="export upcoming passes as a calendar (.ics) with reminders", epilog=EPILOG)
    _add_prediction(p)
    p.add_argument("-o", "--output", default="sstv_passes.ics")
    p.add_argument("--alarm", type=int, default=10, help="reminder minutes before AOS (0 = none, default 10)")
    p.set_defaults(func=cmd_ics, hours=72)

    p = sub.add_parser("watch", help="run continuously and alert before each pass", epilog=EPILOG)
    _add_prediction(p)
    p.add_argument("--lead", type=float, default=float(os.environ.get("SSTV_LEAD", 10)), help="minutes of warning before AOS (default 10)")
    p.add_argument("--ntfy", nargs="+", default=os.environ.get("SSTV_NTFY", "").split() or None, metavar="TOPIC",
                   help="ntfy topic or full URL for phone push alerts")
    p.add_argument("--webhook", nargs="+", default=os.environ.get("SSTV_WEBHOOK", "").split() or None, metavar="URL",
                   help="POST alerts as JSON (Discord/Slack-style webhook)")
    p.add_argument("--aos-alert", action="store_true", help="also alert at AOS")
    p.add_argument("--test-alert", action="store_true", help="send a test alert on start-up")
    p.add_argument("--utc", action="store_true")
    p.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("update-tle", help="force-refresh cached orbital elements")
    p.set_defaults(func=cmd_update_tle)

    p = sub.add_parser("build-site", help="build the static web app (for GitHub Pages or any web server)")
    p.add_argument("-o", "--output", type=Path, default=Path("_site"))
    p.add_argument("--tle-file", type=Path)
    p.add_argument("--offline", action="store_true")
    p.set_defaults(func=cmd_build_site)

    p = sub.add_parser("serve", help="build and serve the web app locally")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to share on your LAN / in Docker")
    p.add_argument("--offline", action="store_true")
    p.set_defaults(func=cmd_serve)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0
