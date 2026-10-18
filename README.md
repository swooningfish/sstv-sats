# sstv-sats: SSTV satellite pass predictor and CHIRP memories

[![Tests](https://github.com/swooningfish/sstv-sats/actions/workflows/ci.yml/badge.svg)](https://github.com/swooningfish/sstv-sats/actions/workflows/ci.yml)
[![Web app](https://github.com/swooningfish/sstv-sats/actions/workflows/pages.yml/badge.svg)](https://github.com/swooningfish/sstv-sats/actions/workflows/pages.yml)

### 🛰️ Open the web app: **[swooningfish.github.io/sstv-sats](https://swooningfish.github.io/sstv-sats/)**

Enter your location to see when the SSTV satellites pass over you, set alerts, and download the CHIRP files. There's nothing to install.

Tools for receiving slow-scan TV pictures from the amateur satellites that send **periodic SSTV**:

- **CHIRP CSV files** ready to import, with Doppler-offset channels for 70 cm.
- **Pass predictions** for your location: when each satellite rises, how high it gets, where to point, and how far to tune for Doppler.
- **Alerts** before each pass: in the browser, as phone push notifications (ntfy), on Discord or Slack, or as calendar reminders (.ics).
- A **web app** that anyone can use with nothing to install. GitHub Pages hosts it and rebuilds it every day with fresh orbital data.

Satellite list from the "Satellites with periodic SSTV" graphic by **LU3FCI, Juan Carlos**. 73!

## Satellites

| ID | Name | NORAD | Downlink (MHz) | Notes |
|---|---|---|---|---|
| RS58S | Monitor 3 | 57180 | 435.290 | Robot36 |
| RS38S | Vizard Meteo | 57189 | 437.825 | Robot72 |
| RS40S | Umka 1 | 57172 | 437.625 | |
| RS49S | Nanozond 1 | 57190 | 437.000 | **Re-entered 2026-04-20**, so it is excluded by default |
| RS27S | UTMN 2 | 57203 | 436.125 | Robot36 |
| RS18S | Sakhacube Cholbon | 67290 | 437.350 | |
| RS95S | QMR KWT 2 | 67291 | 436.950 | |
| RS57S | Monitor 4 | 57182 | 436.080 | SatNOGS lists GMSK only, so SSTV is unconfirmed |
| RS90S | Luca 1 | 67287 | 437.180 | SatNOGS lists GMSK only, so SSTV is unconfirmed |
| ISS | ISS | 25544 | 145.800 / 437.550 | ARISS SSTV runs as [scheduled events](https://ariss-sstv.blogspot.com/) |
| SONATE-2 | SONATE 2 | 59112 | 145.880 | Martin M1 |
| JAMX01 | JAMX01 | 98248 | 435.175 | Temporary NORAD ID, TLE from SatNOGS |
| IO-86 | LAPAN A2 | 40931 | 435.880 | Equatorial orbit, so it is only visible between about ±20° latitude |
| GALAPAGOS | Galapagos UTE SWSU | 67279 | 437.050 | |

The catalogue lives in [`src/sstv_sats/satellites.json`](src/sstv_sats/satellites.json). To add or change a satellite, edit that one file (see [Contributing](#contributing)).

## Quick start

### 1. Just want the CHIRP file?

Download one of these and use **File → Import** in CHIRP:

| File | Channels | Use when |
|---|---|---|
| [`chirp/sstv_satellites_chirp.csv`](chirp/sstv_satellites_chirp.csv) | 38 | **Recommended.** Each 70 cm satellite gets +10 kHz, centre and −10 kHz channels |
| [`chirp/sstv_satellites_chirp_fine_doppler.csv`](chirp/sstv_satellites_chirp_fine_doppler.csv) | 66 | Narrow-filter radios: ±5 and ±10 kHz on 70 cm, ±5 kHz on 2 m |
| [`chirp/sstv_satellites_chirp_no_doppler.csv`](chirp/sstv_satellites_chirp_no_doppler.csv) | 14 | Centre frequencies only (SDRs, or radios you tune by hand) |

**Doppler, in short:** a satellite coming towards you sounds higher than its real frequency. Start the pass on the `+10` channel, switch to the centre channel near the highest point, and finish on `-10`. On 2 m the shift is only about ±3.5 kHz, so one channel is enough.

### 2. Use the web app

Open **[swooningfish.github.io/sstv-sats](https://swooningfish.github.io/sstv-sats/)**. Enter your latitude and longitude or your Maidenhead locator, or click **Use my location**. The page shows:

- a countdown to the next pass
- a table of passes with rise and set directions, peak elevation and Doppler
- **Enable alerts**, for browser notifications N minutes before each pass (only while the tab is open)
- **Add to calendar (.ics)**, so your phone or computer calendar reminds you even when the page is closed

All calculations run in your browser. Your location is never sent anywhere.

### 3. Use the command line

Needs Python 3.9 or newer.

```bash
pip install git+https://github.com/swooningfish/sstv-sats.git
```

Or, from a clone of this repo:

```bash
pip install .
```

```bash
sstv-sats passes --lat 51.5074 --lon -0.1278
```

Example output:

```
SSTV passes for 51.5208, -0.1250 - next 24 h, max elevation >= 10 deg, times GMT Summer Time

Satellite              Freq MHz  Date            AOS   Az       TCA MaxEl   Az       LOS   Az    Dur  Doppler kHz AOS/TCA/LOS
RS57S Monitor 4         436.080  2026-10-18 21:55:06  SSE  22:00:34    56  ENE  22:06:07    N  11:00  +10.4/-0.0/-10.4
RS40S Umka 1            437.625  2026-10-18 22:05:06    S  22:10:45    57    W  22:16:27  NNW  11:21  +10.3/-0.0/-10.3
ISS                     145.800  2026-10-19 08:39:34    W  08:45:05    90    S  08:50:36    E  11:01  +3.3/-0.0/-3.3
```

- **AOS** (acquisition of signal) is when the satellite rises above your horizon.
- **TCA** (time of closest approach) is the highest point of the pass.
- **LOS** (loss of signal) is when it sets.

Passes above about 30° give the cleanest pictures.

#### Commands

| Command | What it does |
|---|---|
| `sstv-sats list [-v]` | Show the satellite catalogue |
| `sstv-sats chirp [-o file.csv] [--doppler none\|basic\|full] [--start 1] [--name-length 8] [--sat ...]` | Write a CHIRP CSV |
| `sstv-sats passes --lat .. --lon .. [--hours 24] [--min-el 10] [--sat ...] [--utc] [--json]` | List upcoming passes |
| `sstv-sats ics --grid IO91wm [-o passes.ics] [--hours 72] [--alarm 10]` | Calendar file with a reminder before each pass |
| `sstv-sats watch --grid IO91wm [--lead 10] [--ntfy TOPIC] [--webhook URL] [--aos-alert]` | Keep running and send an alert before every pass |
| `sstv-sats update-tle` | Force-refresh the orbital elements |
| `sstv-sats serve [--port 8000] [--host 0.0.0.0]` | Run the web app locally |
| `sstv-sats build-site -o _site` | Build the static web app to upload to any web host |

Every location option accepts `--lat/--lon/--alt` or `--grid`. You can also set them with the environment variables `SSTV_LAT`, `SSTV_LON`, `SSTV_ALT` and `SSTV_GRID`.

Use `--sat` to pick satellites by ID, name or NORAD number, for example `--sat ISS umka RS58S`.

#### Phone alerts with ntfy

1. Install the free [ntfy app](https://ntfy.sh) (Android or iOS) and subscribe to a topic name that's hard to guess, for example `sstv-g4abc-x7k2`.
2. Run:

   ```bash
   sstv-sats watch --grid IO91wm --lead 10 --ntfy sstv-g4abc-x7k2 --test-alert
   ```

Ten minutes before each pass you get a push notification with the frequency, rise and set directions and the Doppler tuning. `--ntfy` also accepts a full URL if you run your own ntfy server.

`--webhook` posts JSON that Discord webhooks accept as-is (`content`) and Slack-style webhooks read too (`text`).

## Hosting your own copy

### GitHub Pages (free, no server)

1. Create a new repository on GitHub and push this code to it.
2. In the repository go to **Settings → Pages → Build and deployment** and set **Source** to **GitHub Actions**.
3. Push to `main`, or run the **Build & deploy web app** workflow from the Actions tab.

The workflow ([`.github/workflows/pages.yml`](.github/workflows/pages.yml)) runs every day at 03:17 UTC. It downloads fresh TLEs and republishes the site, so predictions stay accurate without anyone doing anything. Your copy is published at `https://YOUR-USER.github.io/sstv-sats/`.

### Docker (watcher and web app on a Raspberry Pi or home server)

Edit the location and ntfy topic in [`docker-compose.yml`](docker-compose.yml), then run:

```bash
docker compose up -d
```

This runs two things:

- `watch` sends alerts before every pass.
- `web` serves the web app on port 8000.

### Any web server

```bash
sstv-sats build-site -o _site
```

Upload `_site/` anywhere, and rerun the command at least weekly so the orbital data stays fresh.

## How it works

- **Orbital elements** come from [CelesTrak](https://celestrak.org) by NORAD number. New objects CelesTrak doesn't carry yet, such as JAMX01 with its temporary ID, fall back to [SatNOGS DB](https://db.satnogs.org).
- Elements are cached for 12 hours in `~/.cache/sstv-sats` (set `SSTV_SATS_CACHE` to change this). If the internet is down, the stale copy is used with a warning.
- **Predictions** use SGP4. The CLI uses [Skyfield](https://rhodesmill.org/skyfield/) and the web app uses [satellite.js](https://github.com/shashwatak/satellite-js). AOS and LOS are the 0° horizon crossings. Passes whose peak is below `--min-el` (default 10°) are left out.
- **Doppler** is `−f × range-rate / c` at AOS, TCA and LOS for the satellite's first downlink.

## Receiving tips

- **Mode:** FM, with the wide filter if your radio has one, squelch open, and the volume set once and left alone.
- **Decoders:**
  - Windows: MMSSTV or RX-SSTV
  - Linux: QSSTV
  - macOS: Black Cat SSTV
  - Android: Robot36
- **Record, don't wait.** These satellites transmit SSTV *periodically*, not continuously. Record the audio for the whole pass (Audacity, or an SDR) and decode it afterwards.
- **Antenna:** a handheld 70 cm Yagi, or an Arrow-style dual-band antenna, is a big step up from a rubber duck. Turn it to follow the azimuths in the pass table.

## Contributing

Satellites come and go. To add one, update a frequency or mark a satellite as decayed:

1. Edit [`src/sstv_sats/satellites.json`](src/sstv_sats/satellites.json):
   - `short` is the channel name in CHIRP, 8 characters at most.
   - Set `"active": false` for a satellite that has decayed.
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

CI fails if the CHIRP files don't match the catalogue.

## Licence

MIT. The orbital data is provided by CelesTrak and SatNOGS under their own terms. Please keep the default 12-hour cache so their servers don't get hammered.
