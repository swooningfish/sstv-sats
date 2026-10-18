"""Export the catalogue as a CHIRP-compatible CSV memory file.

On 70 cm a LEO satellite's downlink is shifted by up to about +/-10 kHz by Doppler, which
is enough to garble FM SSTV on a 12.5 kHz channel. The usual trick is to programme the
same satellite several times at different offsets and step through them during the
pass (high at AOS, nominal at TCA, low at LOS). Channels are written in ascending
frequency order (minus, centre, plus) so they sit in order in the radio's memory list.
"""

from __future__ import annotations

import csv
import io
from typing import Iterable

from .catalog import Satellite

HEADER = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone", "rToneFreq", "cToneFreq",
    "DtcsCode", "DtcsPolarity", "RxDtcsCode", "CrossMode", "Mode", "TStep", "Skip", "Comment",
    "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE",
]

# Doppler offsets in kHz, by profile, for UHF (>= 300 MHz) and VHF downlinks, lowest first.
DOPPLER_PROFILES = {
    "none": {"uhf": [0], "vhf": [0]},
    "basic": {"uhf": [-10, 0, 10], "vhf": [0]},
    "full": {"uhf": [-10, -5, 0, 5, 10], "vhf": [-5, 0, 5]},
}


def _channel_name(short: str, offset_khz: int, max_len: int) -> str:
    suffix = "" if offset_khz == 0 else f"{offset_khz:+d}"
    return (short[: max(1, max_len - len(suffix))] + suffix)[:max_len]


def _channels(sats: Iterable[Satellite], doppler: str, all_downlinks: bool, name_length: int):
    """Yield (sat, downlink index, downlink, offset kHz, short name) in memory-channel order."""
    profile = DOPPLER_PROFILES[doppler]
    for sat in sats:
        downlinks = sat.downlinks if all_downlinks else sat.downlinks[:1]
        for i, dl in enumerate(downlinks):
            band = "uhf" if dl.freq_mhz >= 300 else "vhf"
            short = sat.short
            if i:
                short = sat.short[: max(1, name_length - 4)] + ("U" if band == "uhf" else "V")
            for off in profile[band]:
                yield sat, i, dl, off, short


def chirp_layout(sats: Iterable[Satellite], doppler: str = "basic", all_downlinks: bool = True) -> dict:
    """Where each satellite lands in the CHIRP file: {sat id: [[[offset kHz, 0-based channel], ...] per downlink]}.

    The web app adds the user's first memory channel to show which channel to use on each pass.
    """
    layout: dict = {}
    for n, (sat, i, _dl, off, _short) in enumerate(_channels(sats, doppler, all_downlinks, 8)):
        per_dl = layout.setdefault(sat.id, [])
        while len(per_dl) <= i:
            per_dl.append([])
        per_dl[i].append([off, n])
    return layout


def chirp_rows(
    sats: Iterable[Satellite],
    doppler: str = "basic",
    start: int = 1,
    name_length: int = 8,
    all_downlinks: bool = True,
) -> list:
    rows = []
    loc = start
    for sat, _i, dl, off, short in _channels(sats, doppler, all_downlinks, name_length):
        freq = dl.freq_mhz + off / 1000.0
        comment = f"{sat.label} SSTV RX"
        if off:
            comment += f" Doppler {off:+d}kHz ({'AOS' if off > 0 else 'LOS'})"
        if dl.sstv_mode:
            comment += f" - {dl.sstv_mode}"
        if dl.note:
            comment += f" - {dl.note}"
        rows.append({
            "Location": loc,
            "Name": _channel_name(short, off, name_length),
            "Frequency": f"{freq:.6f}",
            "Duplex": "",
            "Offset": "0.000000",
            "Tone": "",
            "rToneFreq": "88.5",
            "cToneFreq": "88.5",
            "DtcsCode": "023",
            "DtcsPolarity": "NN",
            "RxDtcsCode": "023",
            "CrossMode": "Tone->Tone",
            "Mode": dl.mode,
            "TStep": "5.00",
            "Skip": "",
            "Comment": comment,
            "URCALL": "", "RPT1CALL": "", "RPT2CALL": "", "DVCODE": "",
        })
        loc += 1
    return rows


def to_csv(rows: list) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
