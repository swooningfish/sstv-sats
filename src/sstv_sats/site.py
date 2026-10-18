"""Build the static web app (GitHub Pages / any static host) with fresh data baked in."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from .catalog import catalog_text, load_catalog, select
from .chirp import DOPPLER_PROFILES, chirp_layout, chirp_rows, to_csv
from .tle import get_tles

CHIRP_FILES = {p: f"sstv_satellites_chirp_{p}.csv" for p in DOPPLER_PROFILES}


def build_site(out_dir: Path, tle_file=None, offline: bool = False) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / "chirp").mkdir()

    web = resources.files("sstv_sats").joinpath("web")
    for item in web.iterdir():
        if item.is_file():
            (out / item.name).write_bytes(item.read_bytes())

    sats = load_catalog()
    (out / "data" / "satellites.json").write_text(catalog_text(), encoding="utf-8")
    tles = get_tles([s.norad_id for s in select(sats)], tle_file=tle_file, offline=offline)
    tle_text = "".join(f"{name}\n{l1}\n{l2}\n" for name, l1, l2 in tles.values())
    (out / "data" / "tle.txt").write_text(tle_text, encoding="utf-8")
    (out / "data" / "build.json").write_text(
        json.dumps({"built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tle_count": len(tles)}),
        encoding="utf-8",
    )
    for profile, name in CHIRP_FILES.items():
        (out / "chirp" / name).write_bytes(to_csv(chirp_rows(select(sats), doppler=profile)).encode("utf-8"))
    # Which memory channel each satellite lands on in each file, for the web app's Channel column.
    layout = {profile: chirp_layout(select(sats), doppler=profile) for profile in CHIRP_FILES}
    (out / "data" / "chirp_layout.json").write_text(json.dumps(layout, separators=(",", ":")), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out
