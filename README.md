# sstv-sats: SSTV satellite pass predictor and CHIRP memories

[![Tests](https://github.com/swooningfish/sstv-sats/actions/workflows/ci.yml/badge.svg)](https://github.com/swooningfish/sstv-sats/actions/workflows/ci.yml)
[![Web app](https://github.com/swooningfish/sstv-sats/actions/workflows/pages.yml/badge.svg)](https://github.com/swooningfish/sstv-sats/actions/workflows/pages.yml)

Know when the amateur satellites that send **slow-scan TV (SSTV) pictures** will be over you, get an alert before they arrive, and load their frequencies into your radio with CHIRP.

## TL;DR

- 🛰️ **See the passes for your location:** open **[swooningfish.github.io/sstv-sats](https://swooningfish.github.io/sstv-sats/)** and enter your location or locator. There's nothing to install.
- 📻 **Programme your radio:** download [`chirp/sstv_satellites_chirp.csv`](chirp/sstv_satellites_chirp.csv) and use **File → Import** in CHIRP.
- 🔁 **During a pass:** start on the `+10` channel as the satellite rises, move to the centre channel near the top of the pass, and finish on `-10` as it sets.
- 🔔 **Get alerts:** the web app has browser alerts and a calendar download. For phone push alerts, run `sstv-sats watch --ntfy <topic>` (see [Alerts](#alerts)).
- 🎧 **Decode:** FM, wide filter, record the whole pass, and decode with MMSSTV, QSSTV or Robot36. On a Quansheng UV-K5 or UV-K1 you can decode on the radio with the [F4HWN SSTV app](https://github.com/armel/uv-k1-k5v3-firmware-custom/wiki/App-SSTV).
- 🖼️ **Modes:** Robot 36, Robot 72, Martin M1 and PD120/PD180. Decoders pick the mode automatically (see [SSTV modes](#sstv-modes)).

## Contents

1. [The satellites](#the-satellites)
2. [CHIRP memory files](#chirp-memory-files)
3. [Web app](#web-app)
4. [Command line](#command-line)
5. [Alerts](#alerts)
6. [Receiving tips](#receiving-tips)
7. [Hosting your own copy](#hosting-your-own-copy)
8. [How it works](#how-it-works)
9. [Contributing](#contributing)
10. [Credits and licence](#credits-and-licence)

## The satellites

| ID | Name | NORAD | Downlink (MHz) | SSTV mode | Notes |
|---|---|---|---|---|---|
| RS58S | Monitor 3 | 57180 | 435.290 | Robot 36 | |
| RS38S | Vizard Meteo | 57189 | 437.825 | Robot 72 | |
| RS40S | Umka 1 | 57172 | 437.625 | Not published | |
| RS49S | Nanozond 1 | 57190 | 437.000 | Not published | **Re-entered 2026-04-20**, so it is excluded by default |
| RS27S | UTMN 2 | 57203 | 436.125 | Robot 36 | |
| RS18S | Sakhacube Cholbon | 67290 | 437.350 | Not published | |
| RS95S | QMR KWT 2 | 67291 | 436.950 | Not published | |
| RS57S | Monitor 4 | 57182 | 436.080 | Not published | SatNOGS lists GMSK only, so SSTV is unconfirmed |
| RS90S | Luca 1 | 67287 | 437.180 | Not published | SatNOGS lists GMSK only, so SSTV is unconfirmed |
| ISS | ISS | 25544 | 145.800 | PD120 or PD180 | ARISS SSTV runs as [scheduled events](https://ariss-sstv.blogspot.com/) |
| | | | 437.550 | Robot 36 | |
| SONATE-2 | SONATE 2 | 59112 | 145.880 | Martin M1 | |
| JAMX01 | JAMX01 | 98248 | 435.175 | Not published | Temporary NORAD ID, TLE from SatNOGS |
| IO-86 | LAPAN A2 | 40931 | 435.880 | None (SSDV) | Sends SSDV packet images, which SSTV decoders can't read. Equatorial orbit, so it is only visible between about ±20° latitude |
| GALAPAGOS | Galapagos UTE SWSU | 67279 | 437.050 | Not published | |

These satellites send SSTV **periodically**, not all the time, so a pass won't always carry a picture.

### SSTV modes

The modes come from the transmitter listings in [SatNOGS DB](https://db.satnogs.org). "Not published" means SatNOGS lists SSTV on that frequency without saying which mode.

You don't need to know the mode in advance. Every SSTV picture starts with a short **VIS code** that names its mode, and decoders set to auto-detect switch to the right mode automatically.

| Mode | Picture time | Used by |
|---|---|---|
| Robot 36 | 36 s, colour | Monitor 3, UTMN 2, ISS on 437.550 |
| Robot 72 | 72 s, colour | Vizard Meteo |
| Martin M1 | about 114 s, colour | SONATE 2 |
| PD120 / PD180 | 126 s / 187 s, colour | ISS on 145.800 during ARISS events |

#### Decoding on a Quansheng UV-K5 or UV-K1 (F4HWN firmware)

If you have a Quansheng UV-K5 or UV-K1, F4HWN's custom firmware has an **[SSTV app](https://github.com/armel/uv-k1-k5v3-firmware-custom/wiki/App-SSTV)** that decodes pictures on the radio's own screen, with no computer needed:

> It recognizes 14 VIS-selected modes: Robot 36/72, Martin M1/M2, Scottie S1/S2/DX, and PD50/90/120/160/180/240/290.

That covers every mode these satellites use. A few things to know:

- Set the VFO to FM before launching the app.
- Pictures are shown in monochrome on the radio's display.
- The app is part of the experimental "Labs" edition and is installed with UV Studio. See the [wiki page](https://github.com/armel/uv-k1-k5v3-firmware-custom/wiki/App-SSTV) for setup and controls.

## CHIRP memory files

### Which file?

| File | Channels | Use it when |
|---|---|---|
| [`sstv_satellites_chirp.csv`](chirp/sstv_satellites_chirp.csv) | 38 | **Recommended** for most handhelds and mobiles |
| [`sstv_satellites_chirp_fine_doppler.csv`](chirp/sstv_satellites_chirp_fine_doppler.csv) | 66 | Your radio has a narrow filter and needs 5 kHz steps |
| [`sstv_satellites_chirp_no_doppler.csv`](chirp/sstv_satellites_chirp_no_doppler.csv) | 14 | You use an SDR or tune by hand |

To import: in CHIRP, read your radio first, then use **File → Import**, pick the CSV and upload it to the radio.

### Channel layout

Each satellite's channels are in frequency order: **minus, then centre, then plus**. For example, in the recommended file:

| Location | Name | Frequency | When to use it |
|---|---|---|---|
| 1 | `RS58S-10` | 435.280 | End of the pass (LOS) |
| 2 | `RS58S` | 435.290 | Middle of the pass (highest point) |
| 3 | `RS58S+10` | 435.300 | Start of the pass (AOS) |

- **70 cm satellites** get `-10`, centre and `+10` channels in the recommended file, and `-10`, `-5`, centre, `+5` and `+10` in the fine file.
- **2 m downlinks** (ISS 145.800, SONATE 2) only shift by about ±3.5 kHz. They get one channel in the recommended file and `-5`, centre, `+5` in the fine file.
- **ISS** also has a 70 cm downlink, listed as `ISSU`.

### Why Doppler matters

A satellite coming towards you sounds higher than its real frequency, and lower as it moves away. On 70 cm that's up to ±10 kHz, which is enough to garble an FM picture. So:

1. As the satellite rises, listen on the **`+10`** channel.
2. Near the highest point, step down to the **centre** channel.
3. As it sets, step down to **`-10`**.

The [web app](#web-app) and `sstv-sats passes` show the exact shift for each pass.

## Web app

**[swooningfish.github.io/sstv-sats](https://swooningfish.github.io/sstv-sats/)**

Enter your latitude and longitude or Maidenhead locator, or click **Use my location**. You get:

- a countdown to the next pass
- a table of passes with rise and set times, compass directions, peak elevation and Doppler
- **Enable alerts**, for a browser notification before each pass (only while the tab is open)
- **Add to calendar (.ics)**, for reminders from your phone or computer calendar
- download links for the CHIRP files
- a collapsible **UV-K1 / UV-K5 SSTV app keys** panel, showing which keys do what in the F4HWN firmware's SSTV app on a picture of each keypad

Everything is calculated in your browser, and your location is never sent anywhere. The site rebuilds every day with fresh orbital data.

## Command line

### Install

Needs Python 3.9 or newer.

```bash
pip install git+https://github.com/swooningfish/sstv-sats.git
```

### List passes

```bash
sstv-sats passes --grid IO91wm
```

Or use latitude and longitude:

```bash
sstv-sats passes --lat 51.5074 --lon -0.1278
```

Example output:

```
Satellite              Freq MHz  Date            AOS   Az       TCA MaxEl   Az       LOS   Az    Dur  Doppler kHz AOS/TCA/LOS
RS57S Monitor 4         436.080  2026-10-18 21:55:06  SSE  22:00:34    56  ENE  22:06:07    N  11:00  +10.4/-0.0/-10.4
RS40S Umka 1            437.625  2026-10-18 22:05:06    S  22:10:45    57    W  22:16:27  NNW  11:21  +10.3/-0.0/-10.3
ISS                     145.800  2026-10-19 08:39:34    W  08:45:05    90    S  08:50:36    E  11:01  +3.3/-0.0/-3.3
```

| Column | Meaning |
|---|---|
| **AOS** | Acquisition of signal: the satellite rises above your horizon |
| **TCA** | Time of closest approach: the highest point of the pass |
| **MaxEl** | Peak elevation in degrees. Passes above about 30° give the cleanest pictures |
| **LOS** | Loss of signal: the satellite sets |
| **Az** | Compass direction to point your antenna |
| **Doppler** | How far off the nominal frequency the signal is at AOS, TCA and LOS |

### All commands

| Command | What it does |
|---|---|
| `sstv-sats passes` | List upcoming passes |
| `sstv-sats watch` | Keep running and alert before every pass (see [Alerts](#alerts)) |
| `sstv-sats ics -o passes.ics` | Calendar file with a reminder before each pass (next 72 hours) |
| `sstv-sats chirp -o my.csv` | Write a CHIRP CSV |
| `sstv-sats list -v` | Show the satellite catalogue with notes |
| `sstv-sats update-tle` | Force-refresh the orbital data |
| `sstv-sats serve` | Run the web app locally on port 8000 |
| `sstv-sats build-site -o _site` | Build the web app to upload to any web host |

Run any command with `--help` to see all its options.

### Common options

| Option | Used by | Meaning |
|---|---|---|
| `--grid IO91wm` or `--lat` / `--lon` / `--alt` | passes, watch, ics | Your location (or set `SSTV_GRID`, or `SSTV_LAT` / `SSTV_LON` / `SSTV_ALT`) |
| `--hours 24` | passes, watch, ics | How far ahead to look |
| `--min-el 10` | passes, watch, ics | Skip passes that peak lower than this |
| `--sat ISS umka RS58S` | all except list | Only these satellites (by ID, name or NORAD number) |
| `--utc` | passes, watch | Show times in UTC instead of local time |
| `--doppler none\|basic\|full` | chirp | Which Doppler channels to add (`basic` is the default) |
| `--start 1` | chirp | First memory location number |
| `--name-length 8` | chirp | Longest channel name your radio accepts |

## Alerts

| Method | Works when | How |
|---|---|---|
| Browser notification | The web app tab is open | Click **Enable alerts** in the web app |
| Calendar reminder | Always | **Add to calendar** in the web app, or `sstv-sats ics` |
| Phone push (ntfy) | A computer is running `watch` | See below |
| Discord or Slack | A computer is running `watch` | `--webhook <url>` |

### Phone push alerts with ntfy

1. Install the free [ntfy app](https://ntfy.sh) on Android or iOS.
2. Subscribe to a topic name that's hard to guess, for example `sstv-g4abc-x7k2`.
3. On a computer that stays on, run:

   ```bash
   sstv-sats watch --grid IO91wm --lead 10 --ntfy sstv-g4abc-x7k2 --test-alert
   ```

`--test-alert` sends one alert straight away so you can check it works. After that you get a push notification `--lead` minutes before each pass, with the frequency, the rise and set directions, and how far to tune for Doppler. Add `--aos-alert` for a second alert when the satellite rises.

`--ntfy` also accepts a full URL if you run your own ntfy server. `--webhook` posts JSON that Discord accepts as-is (`content`) and Slack-style webhooks read too (`text`).

To keep `watch` running on a Raspberry Pi or home server, use [Docker](#docker).

## Receiving tips

- **Radio:** FM, with the wide filter if your radio has one. Open the squelch, and set the volume once and leave it.
- **Record, don't wait:** record the audio for the whole pass (Audacity, or an SDR) and decode it afterwards.
- **Decoders:**
  - Windows: MMSSTV or RX-SSTV
  - Linux: QSSTV
  - macOS: Black Cat SSTV
  - Android: Robot36
  - On the radio: the [F4HWN SSTV app](https://github.com/armel/uv-k1-k5v3-firmware-custom/wiki/App-SSTV) for the Quansheng UV-K5 and UV-K1
- **Mode:** leave your decoder on auto-detect (VIS) so it picks the right mode for each picture.
- **Antenna:** a handheld 70 cm Yagi, or an Arrow-style dual-band antenna, is a big step up from a rubber duck. Turn it to follow the directions in the pass table.

## Hosting your own copy

### GitHub Pages

Free, with no server to run.

1. Fork this repository.
2. Go to **Settings → Pages** and set **Source** to **GitHub Actions**. Don't configure either of the suggested workflows.
3. Go to the **Actions** tab and run **Build & deploy web app**.

Your copy appears at `https://YOUR-USER.github.io/sstv-sats/` and rebuilds every day at 03:17 UTC with fresh orbital data.

### Docker

Runs the alert watcher and the web app on a Raspberry Pi or home server.

1. Edit your location and ntfy topic in [`docker-compose.yml`](docker-compose.yml).
2. Run:

   ```bash
   docker compose up -d
   ```

This starts two containers:

- `watch` sends alerts before every pass.
- `web` serves the web app on port 8000.

### Any other web server

```bash
sstv-sats build-site -o _site
```

Upload `_site/` to any static web host. Rerun the command at least once a week so the orbital data stays fresh.

## How it works

- **Orbital data (TLEs):** downloaded from [CelesTrak](https://celestrak.org) by NORAD number. Satellites CelesTrak doesn't carry yet fall back to [SatNOGS DB](https://db.satnogs.org).
- **Caching:** TLEs are cached for 12 hours in `~/.cache/sstv-sats` (change this with `SSTV_SATS_CACHE`). If the download fails, the older cached copy is used with a warning.
- **Predictions:** SGP4, using [Skyfield](https://rhodesmill.org/skyfield/) on the command line and [satellite.js](https://github.com/shashwatak/satellite-js) in the web app. AOS and LOS are when the satellite crosses your horizon (0°).
- **Doppler:** `−f × range-rate / c`, worked out at AOS, TCA and LOS on the satellite's first downlink.

## Contributing

Satellites come and go. All the satellite data is in one file, [`src/sstv_sats/satellites.json`](src/sstv_sats/satellites.json).

1. Edit `satellites.json`:
   - To add a satellite, copy an existing entry. `short` is the CHIRP channel name, 8 characters at most.
   - To retire one, set `"active": false`.
2. Regenerate the CHIRP files:

   ```bash
   sstv-sats chirp -o chirp/sstv_satellites_chirp.csv
   ```

   ```bash
   sstv-sats chirp --doppler none -o chirp/sstv_satellites_chirp_no_doppler.csv
   ```

   ```bash
   sstv-sats chirp --doppler full -o chirp/sstv_satellites_chirp_fine_doppler.csv
   ```

3. Run the tests:

   ```bash
   pip install -e ".[test]"
   ```

   ```bash
   pytest
   ```

4. Open a pull request. CI fails if the CHIRP files don't match `satellites.json`.

## Credits and licence

- Satellite list from the "Satellites with periodic SSTV" graphic by **LU3FCI, Juan Carlos**. 73 and good reception to all!
- Orbital data from CelesTrak and SatNOGS, under their own terms. Please keep the 12-hour cache so their servers aren't hammered.
- Code licensed under MIT.
