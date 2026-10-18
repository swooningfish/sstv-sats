/* SSTV satellite pass predictor - runs entirely in the browser using satellite.js (SGP4). */
(() => {
  "use strict";
  const DEG = Math.PI / 180;
  const C_KM_S = 299792.458;
  const STEP_S = 30;
  const $ = (id) => document.getElementById(id);

  const store = {
    get(k, d) { try { const v = localStorage.getItem("sstv." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("sstv." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  };

  let catalog = [], tles = {}, passes = [], hidden = new Set(store.get("hidden", [])), notified = new Set();

  // ---------- data ----------
  function parseTles(text) {
    const lines = text.split(/\r?\n/).map((l) => l.trimEnd()).filter(Boolean);
    const out = {};
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].startsWith("1 ") && lines[i + 1] && lines[i + 1].startsWith("2 ")) {
        const id = parseInt(lines[i].slice(2, 7), 10);
        out[id] = { l1: lines[i], l2: lines[i + 1], name: i > 0 && !lines[i - 1].startsWith("2 ") ? lines[i - 1] : "" };
        i++;
      }
    }
    return out;
  }

  function tleEpoch(l1) {
    const yy = parseInt(l1.slice(18, 20), 10);
    const year = yy < 57 ? 2000 + yy : 1900 + yy;
    return new Date(Date.UTC(year, 0, 1) + (parseFloat(l1.slice(20, 32)) - 1) * 86400000);
  }

  // ---------- geometry ----------
  function maidenhead(grid) {
    const g = grid.trim();
    if (!/^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2}([0-9]{2})?)?$/.test(g)) throw new Error("Not a valid locator");
    const u = g.toUpperCase();
    let lon = (u.charCodeAt(0) - 65) * 20 - 180 + parseInt(u[2], 10) * 2;
    let lat = (u.charCodeAt(1) - 65) * 10 - 90 + parseInt(u[3], 10);
    let ls = 2, as = 1;
    if (g.length >= 6) { ls = 2 / 24; as = 1 / 24; lon += (u.charCodeAt(4) - 65) * ls; lat += (u.charCodeAt(5) - 65) * as; }
    if (g.length >= 8) { ls /= 10; as /= 10; lon += parseInt(u[6], 10) * ls; lat += parseInt(u[7], 10) * as; }
    return { lat: lat + as / 2, lon: lon + ls / 2 };
  }

  function look(satrec, date, obs) {
    const pv = satellite.propagate(satrec, date);
    if (!pv || !pv.position) return null;
    const ecf = satellite.eciToEcf(pv.position, satellite.gstime(date));
    const la = satellite.ecfToLookAngles(obs, ecf);
    return { el: la.elevation / DEG, az: ((la.azimuth / DEG) % 360 + 360) % 360, range: la.rangeSat };
  }

  function pointAt(satrec, t, obs) {
    const a = look(satrec, new Date(t), obs), b = look(satrec, new Date(t + 1000), obs);
    if (!a || !b) return null;
    return { time: new Date(t), el: a.el, az: a.az, range: a.range, rate: b.range - a.range };
  }

  // Bisect the horizon crossing between t0 (state s0) and t1.
  function crossing(satrec, t0, t1, obs, horizon) {
    const above0 = look(satrec, new Date(t0), obs).el > horizon;
    while (t1 - t0 > 500) {
      const m = (t0 + t1) / 2;
      if ((look(satrec, new Date(m), obs).el > horizon) === above0) t0 = m; else t1 = m;
    }
    return (t0 + t1) / 2;
  }

  function peak(satrec, a, b, obs) {
    for (let i = 0; i < 40 && b - a > 500; i++) {
      const m1 = a + (b - a) / 3, m2 = b - (b - a) / 3;
      if (look(satrec, new Date(m1), obs).el < look(satrec, new Date(m2), obs).el) a = m1; else b = m2;
    }
    return (a + b) / 2;
  }

  function predict(sat, tle, obs, start, hours, minEl) {
    const satrec = satellite.twoline2satrec(tle.l1, tle.l2);
    const end = start + hours * 3600000, step = STEP_S * 1000, out = [];
    let prev = look(satrec, new Date(start), obs);
    if (!prev) return out;
    let aos = prev.el > 0 ? start : null, inProgress = prev.el > 0;
    let best = { t: start, el: prev.el };
    for (let t = start + step; t <= end + step * 40; t += step) {
      const cur = look(satrec, new Date(t), obs);
      if (!cur) break;
      if (aos === null && prev.el <= 0 && cur.el > 0) {
        if (t - step > end) break;
        aos = crossing(satrec, t - step, t, obs, 0); best = { t, el: cur.el }; inProgress = false;
      } else if (aos !== null) {
        if (cur.el > best.el) best = { t, el: cur.el };
        if (cur.el <= 0) {
          const los = crossing(satrec, t - step, t, obs, 0);
          const tcaT = peak(satrec, Math.max(aos, best.t - step), Math.min(los, best.t + step), obs);
          const tca = pointAt(satrec, tcaT, obs);
          if (tca && tca.el >= minEl) {
            out.push({ sat, aos: pointAt(satrec, aos, obs), tca, los: pointAt(satrec, los, obs), inProgress, epoch: tleEpoch(tle.l1) });
          }
          aos = null;
        }
      }
      prev = cur;
    }
    return out;
  }

  const doppler = (p, freq) => (-freq * 1e6 * p.rate / C_KM_S) / 1000;
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const compass = (az) => COMPASS[Math.round(az / 22.5) % 16];
  const sign = (v) => (v >= 0 ? "+" : "") + v.toFixed(1);
  const pad = (n) => String(n).padStart(2, "0");
  const fmtTime = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const fmtDay = (d) => d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const fmtDur = (ms) => `${Math.floor(ms / 60000)}:${pad(Math.round((ms % 60000) / 1000))}`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const norm = (x) => x.toUpperCase().replace(/[^A-Z0-9]/g, "");
  // "Robot 36", or per frequency when a satellite has several downlinks.
  const modeText = (s) => {
    const known = s.downlinks.filter((d) => d.sstv_mode);
    if (!known.length) return "not published (your decoder will auto-detect it)";
    if (s.downlinks.length === 1) return known[0].sstv_mode;
    return s.downlinks.map((d) => `${d.sstv_mode || "unknown"} on ${d.freq_mhz.toFixed(3)}`).join(", ");
  };
  const label = (s) => (norm(s.name).startsWith(norm(s.id)) ? s.name : `${s.id} ${s.name}`);

  // ---------- UI ----------
  function readLocation() {
    const grid = $("grid").value.trim();
    if (grid) {
      const { lat, lon } = maidenhead(grid);
      $("lat").value = lat.toFixed(4); $("lon").value = lon.toFixed(4);
    }
    const lat = parseFloat($("lat").value), lon = parseFloat($("lon").value), alt = parseFloat($("alt").value) || 0;
    if (!(Math.abs(lat) <= 90 && Math.abs(lon) <= 180)) throw new Error("Enter a latitude and longitude (or a locator)");
    return { lat, lon, alt };
  }

  function run() {
    let loc;
    try { loc = readLocation(); } catch (e) { alert(e.message); return; }
    const minEl = parseFloat($("minel").value) || 0, hours = Math.min(168, parseFloat($("hours").value) || 24);
    store.set("loc", { lat: $("lat").value, lon: $("lon").value, alt: $("alt").value, grid: $("grid").value, minel: minEl, hours });
    const obs = { latitude: loc.lat * DEG, longitude: loc.lon * DEG, height: loc.alt / 1000 };
    if (window.SstvMap) SstvMap.setObserver(loc.lat, loc.lon, loc.alt / 1000);
    const start = Date.now();
    passes = [];
    for (const sat of catalog) {
      if (sat.active === false || !tles[sat.norad_id]) continue;
      passes.push(...predict(sat, tles[sat.norad_id], obs, start, hours, minEl));
    }
    passes.sort((a, b) => a.aos.time - b.aos.time);
    $("results").hidden = false;
    renderFilters(); renderPasses(); tick();
  }

  function visible() { return passes.filter((p) => !hidden.has(p.sat.id)); }

  function renderFilters() {
    const ids = [...new Set(passes.map((p) => p.sat.id))];
    $("filters").innerHTML = ids.map((id) => {
      const s = catalog.find((x) => x.id === id);
      return `<button type="button" class="chip ${hidden.has(id) ? "off" : ""}" data-id="${esc(id)}">${esc(label(s))}</button>`;
    }).join("");
  }

  function renderPasses() {
    const now = Date.now(), rows = visible();
    $("passes").innerHTML = rows.length ? rows.map((p) => {
      const f = p.sat.downlinks.map((d) => d.freq_mhz.toFixed(3)).join("<br>");
      const elCls = p.tca.el >= 30 ? "el-high" : p.tca.el < 15 ? "el-low" : "";
      const now_ = p.aos.time <= now && p.los.time >= now;
      const f0 = p.sat.downlinks[0].freq_mhz;
      return `<tr class="${now_ ? "now" : ""}" data-sat="${esc(p.sat.id)}" data-aos="${+p.aos.time}" title="Replay this pass on the map">
        <td><b>${esc(label(p.sat))}</b>${now_ ? ' <span class="small">overhead now</span>' : ""}</td>
        <td>${f}</td>
        <td>${fmtDay(p.aos.time)} <b>${fmtTime(p.aos.time)}</b> <span class="small">${compass(p.aos.az)}</span></td>
        <td class="${elCls}">${p.tca.el.toFixed(0)}° <span class="small">${compass(p.tca.az)} ${fmtTime(p.tca.time)}</span></td>
        <td>${fmtTime(p.los.time)} <span class="small">${compass(p.los.az)}</span></td>
        <td>${fmtDur(p.los.time - p.aos.time)}</td>
        <td>${sign(doppler(p.aos, f0))} / ${sign(doppler(p.los, f0))} kHz</td></tr>`;
    }).join("") : `<tr><td colspan="7">No passes found. Try more hours or a lower minimum elevation.</td></tr>`;
    const oldest = Math.max(...passes.map((p) => (now - p.epoch) / 86400000), 0);
    $("data-age").textContent = `Times are your local time. ${passes.length} passes. Oldest orbital data used: ${oldest.toFixed(1)} days.`;
  }

  function tick() {
    const now = Date.now();
    const upcoming = visible().filter((p) => p.los.time > now);
    if (!upcoming.length) { $("next").hidden = true; return; }
    const p = upcoming[0];
    if (window.SstvMap) SstvMap.setAuto(p.sat.id);
    $("next").hidden = false;
    $("next-name").textContent = `${label(p.sat)} · ${p.sat.downlinks.map((d) => d.freq_mhz.toFixed(3)).join(" / ")} MHz`;
    $("next-mode").textContent = `SSTV mode: ${modeText(p.sat)}`;
    $("next-detail").textContent = `${fmtDay(p.aos.time)} ${fmtTime(p.aos.time)} from ${compass(p.aos.az)}, max ${p.tca.el.toFixed(0)}° ${compass(p.tca.az)}, sets ${compass(p.los.az)} at ${fmtTime(p.los.time)}`;
    const ms = p.aos.time - now;
    if (ms <= 0) $("countdown").textContent = "Overhead now";
    else {
      const s = Math.floor(ms / 1000);
      $("countdown").textContent = (s >= 3600 ? `${Math.floor(s / 3600)}:` : "") + `${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
    }
    if (store.get("alerts", false) && "Notification" in window && Notification.permission === "granted") {
      const lead = (parseFloat($("lead").value) || 10) * 60000;
      for (const q of upcoming) {
        const key = `${q.sat.id}@${+q.aos.time}`, until = q.aos.time - now;
        if (until > 0 && until <= lead && !notified.has(key)) {
          notified.add(key);
          new Notification(`SSTV pass: ${label(q.sat)} in ${Math.round(until / 60000)} min`, {
            body: `${q.sat.downlinks.map((d) => d.freq_mhz.toFixed(3)).join(" / ")} MHz, SSTV ${modeText(q.sat)}. Rises ${compass(q.aos.az)} at ${fmtTime(q.aos.time)}, max ${q.tca.el.toFixed(0)}°`,
            tag: key,
          });
        }
      }
    }
  }

  function updateAlertButton() {
    const on = store.get("alerts", false) && "Notification" in window && Notification.permission === "granted";
    $("alerts").textContent = on ? "Alerts on ✓" : "Enable alerts";
    $("alerts").classList.toggle("primary", on);
  }

  function icsDate(d) { return d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, ""); }

  function downloadIcs() {
    const lead = Math.round(parseFloat($("lead").value) || 10), stamp = icsDate(new Date());
    const ev = visible().map((p) => [
      "BEGIN:VEVENT", `UID:${p.sat.norad_id}-${icsDate(p.aos.time)}@sstv-sats`, `DTSTAMP:${stamp}`,
      `DTSTART:${icsDate(p.aos.time)}`, `DTEND:${icsDate(p.los.time)}`,
      `SUMMARY:SSTV ${label(p.sat)} ${p.tca.el.toFixed(0)}° ${p.sat.downlinks[0].freq_mhz.toFixed(3)}`,
      `DESCRIPTION:${p.sat.downlinks.map((d) => d.freq_mhz.toFixed(3)).join(" / ")} MHz\\nAOS ${compass(p.aos.az)} - max ${p.tca.el.toFixed(0)}° ${compass(p.tca.az)} - LOS ${compass(p.los.az)}`,
      "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${label(p.sat)} pass soon`, `TRIGGER:-PT${lead}M`, "END:VALARM", "END:VEVENT",
    ].join("\r\n"));
    const text = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sstv-sats//web//EN", ...ev, "END:VCALENDAR", ""].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/calendar" }));
    a.download = "sstv_passes.ics";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function renderCatalog() {
    $("catalog").innerHTML = catalog.map((s) => {
      const has = !!tles[s.norad_id];
      const note = s.active === false ? `Inactive. ${s.notes || ""}` : (has ? "" : "No current orbital data. ") + (s.notes || "");
      return `<tr><td>${esc(s.id)}</td><td>${esc(s.name)}</td><td>${s.norad_id ?? ""}</td>
        <td>${s.downlinks.map((d) => d.freq_mhz.toFixed(3) + (d.note ? ` <span class="small">${esc(d.note)}</span>` : "")).join("<br>")}</td>
        <td>${s.downlinks.map((d) => (d.sstv_mode ? esc(d.sstv_mode) : '<span class="small">Not published</span>')).join("<br>")}</td>
        <td class="notes">${esc(note)}</td></tr>`;
    }).join("");
  }

  // ---------- UV-K1 / UV-K5 SSTV app key map ----------
  // What each key does in the F4HWN firmware's SSTV app (from its wiki), in table order.
  const SSTV_KEYS = [
    { id: "M", key: "M", tag: "Send logo", action: "Send the boot logo in the selected TX mode" },
    { id: "PTT", key: "PTT", tag: "Ignored", action: "Ignored; never starts an SSTV transmission" },
    { id: "1", key: "1 / F, then 1", tag: "TX mode", action: "Select the next / previous TX mode" },
    { id: "2", key: "2", tag: "1-bit / dither", action: "Switch between 1-BIT and DITHER rendering" },
    { id: "3", key: "3", tag: "Speaker", action: "Turn the received audio speaker on/off" },
    { id: "4", key: "4", tag: "Picture / info", action: "Switch between the received picture and information screen" },
    { id: "F", key: "F", tag: "Reverse", action: "Arm or cancel the reverse direction for the next mode change" },
    { id: "EXIT", key: "EXIT", tag: "Abort / exit", action: "Abort an active TX/RX or leave the picture view; from the information screen, exit the app" },
  ];
  // The UV-K1 and UV-K5 share one grid; only the arrow keys differ (◀ ▶ on the K1, ▲ ▼ on the K5).
  const GRID = ["1", "2", "3", "*", "4", "5", "6", "0", "7", "8", "9", "F"];
  const SUBS = ["BAND", "A/B", "VFO/MR", "SCAN", "FC", "NOAA/WX", "H/M/L", "FM", "VOX", "R", "CALL", "🔑"];

  function renderKeymap() {
    const byId = Object.fromEntries(SSTV_KEYS.map((k) => [k.id, k]));
    const key = (id, label, sub) => {
      const k = byId[id];
      return `<div class="kp-key${k ? " used" : ""}"${k ? ` title="${esc(k.action)}"` : ""}>
        <span class="kp-label">${esc(label)}</span>${sub ? `<span class="kp-sub">${esc(sub)}</span>` : ""}
        ${k ? `<span class="kp-tag">${esc(k.tag)}</span>` : ""}</div>`;
    };
    $("keypads").innerHTML = `
      <figure class="keypad" aria-label="UV-K1 / UV-K5 keypad with SSTV app keys highlighted">
        <figcaption>UV-K1 / UV-K5</figcaption>
        <div class="kp-grid">
          ${key("M", "M", "MENU")}${key("UP", "◀ ▲", "K1 / K5")}${key("DOWN", "▶ ▼", "K1 / K5")}${key("EXIT", "EXIT", "")}
          ${GRID.map((id, i) => key(id, id === "F" ? "F #" : id === "*" ? "✱" : id, SUBS[i])).join("")}
        </div>
      </figure>`;
    $("keytable").innerHTML = SSTV_KEYS.map((k) => `<tr><td><kbd>${esc(k.key)}</kbd></td><td>${esc(k.action)}</td></tr>`).join("");
  }

  // ---------- wiring ----------
  async function init() {
    const saved = store.get("loc", null);
    if (saved) {
      for (const k of ["lat", "lon", "alt", "grid"]) if (saved[k] != null) $(k).value = saved[k];
      if (saved.minel != null) $("minel").value = saved.minel;
      if (saved.hours != null) $("hours").value = saved.hours;
    }
    $("lead").value = store.get("lead", 10);
    const [cat, tleText] = await Promise.all([
      fetch("data/satellites.json").then((r) => r.json()),
      fetch("data/tle.txt").then((r) => r.text()),
    ]);
    catalog = cat.satellites; tles = parseTles(tleText);
    renderCatalog(); updateAlertButton();
    if (window.SstvMap) {
      SstvMap.setSatellites(catalog.filter((s) => s.active !== false && tles[s.norad_id]).map((s) => ({
        id: s.id, label: label(s), freq: s.downlinks.map((d) => d.freq_mhz.toFixed(3)).join(" / "),
        l1: tles[s.norad_id].l1, l2: tles[s.norad_id].l2,
      })));
      SstvMap.setHidden(hidden);
      $("map-card").hidden = false;
    }
    if (saved && saved.lat && saved.lon) run();
  }

  renderKeymap();
  $("loc-form").addEventListener("submit", (e) => { e.preventDefault(); run(); });
  $("lat").addEventListener("input", () => { $("grid").value = ""; });
  $("lon").addEventListener("input", () => { $("grid").value = ""; });
  $("geo").addEventListener("click", () => {
    if (!navigator.geolocation) return alert("Geolocation isn't available in this browser");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        $("lat").value = pos.coords.latitude.toFixed(4); $("lon").value = pos.coords.longitude.toFixed(4);
        if (pos.coords.altitude) $("alt").value = Math.round(pos.coords.altitude);
        $("grid").value = ""; run();
      },
      (err) => alert("Couldn't get your location: " + err.message),
    );
  });
  $("filters").addEventListener("click", (e) => {
    const id = e.target.dataset && e.target.dataset.id;
    if (!id) return;
    hidden.has(id) ? hidden.delete(id) : hidden.add(id);
    store.set("hidden", [...hidden]);
    if (window.SstvMap) SstvMap.setHidden(hidden);
    renderFilters(); renderPasses(); tick();
  });
  $("alerts").addEventListener("click", async () => {
    if (!("Notification" in window)) return alert("This browser doesn't support notifications");
    if (store.get("alerts", false) && Notification.permission === "granted") { store.set("alerts", false); return updateAlertButton(); }
    const perm = await Notification.requestPermission();
    store.set("alerts", perm === "granted");
    if (perm !== "granted") alert("Notifications were blocked. Allow them in your browser's site settings.");
    updateAlertButton();
  });
  $("lead").addEventListener("change", () => store.set("lead", parseFloat($("lead").value) || 10));
  $("ics").addEventListener("click", downloadIcs);
  $("passes").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-sat]");
    if (!row || !window.SstvMap) return;
    SstvMap.showPass(row.dataset.sat, +row.dataset.aos);
    $("map-card").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  setInterval(tick, 1000);
  setInterval(() => { if (passes.length) { renderPasses(); } }, 60000);
  init().catch((e) => { document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="card">Couldn't load satellite data: ${esc(e.message)}</p>`); });
})();
