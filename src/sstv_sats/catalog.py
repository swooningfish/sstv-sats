"""The satellite catalogue (satellites.json) and helpers to load and filter it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Downlink:
    freq_mhz: float
    mode: str = "FM"
    note: str = ""


@dataclass(frozen=True)
class Satellite:
    id: str
    name: str
    short: str
    norad_id: Optional[int]
    downlinks: tuple
    active: bool = True
    notes: str = ""

    @property
    def label(self) -> str:
        norm = lambda x: "".join(c for c in x.upper() if c.isalnum())
        return self.name if norm(self.name).startswith(norm(self.id)) else f"{self.id} {self.name}"

    @property
    def primary(self) -> Downlink:
        return self.downlinks[0]


def catalog_text(path: Optional[Path] = None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return resources.files("sstv_sats").joinpath("satellites.json").read_text(encoding="utf-8")


def load_catalog(path: Optional[Path] = None) -> list:
    data = json.loads(catalog_text(path))
    sats = []
    for s in data["satellites"]:
        sats.append(
            Satellite(
                id=s["id"],
                name=s["name"],
                short=s.get("short") or s["id"],
                norad_id=s.get("norad_id"),
                downlinks=tuple(Downlink(**d) for d in s["downlinks"]),
                active=s.get("active", True),
                notes=s.get("notes", ""),
            )
        )
    return sats


def select(sats: Iterable[Satellite], wanted: Optional[list] = None, include_inactive: bool = False) -> list:
    """Filter by id / short name / name / NORAD id (case-insensitive substring on name)."""
    out = []
    for s in sats:
        if not include_inactive and not s.active:
            continue
        if wanted:
            keys = {s.id.lower(), s.short.lower(), str(s.norad_id)}
            if not any(w.lower() in keys or w.lower() in s.name.lower() for w in wanted):
                continue
        out.append(s)
    return out
