/* World map of the SSTV satellites: positions (live or sped up), ground track, footprint and day/night,
   centred on the observer, plus an optional 3D globe (globe.js + three.js, loaded on demand).
   Exposes window.SstvMap for app.js. Uses satellite.js (SGP4). */
(() => {
  "use strict";
  const DEG = Math.PI / 180;
  const RE = 6378.137; // Earth equatorial radius, km
  const LAND_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/land-110m.json";
  const TRACK_BACK_MIN = 10, TRACK_AHEAD_MIN = 100;
  const OFFSETS = [-720, -360, 0, 360, 720]; // draw wrapped shapes on every copy of the map
  const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js";
  const ORBIT_URL = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js";
  const pref = {
    get(k, d) { try { const v = localStorage.getItem("sstv." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("sstv." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  };
  const $ = (id) => document.getElementById(id);

  const st = {
    sats: [],         // { id, label, freq, satrec }
    hidden: new Set(),
    obs: null,        // { lat, lon, gd }
    pick: "auto",     // satellite id, or "auto" = follow the next pass
    autoId: null,
    hover: null,
    speed: 1,
    simT: Date.now(),
    lastReal: performance.now(),
    land: null,
    track: null,      // cached ground track { id, from, pts }
    view: pref.get("mapView", "3d"),
    altScale: pref.get("altScale", 1),
  };
  let canvas, ctx, landCanvas, W = 0, H = 0, dpr = 1, landKey = "", lastDraw = 0, dots = [];
  let globe = null, globeLoading = null, lastStatus = 0;

  // ---------- geometry ----------
  const norm = (l) => ((((l + 180) % 360) + 360) % 360) - 180;
  const centerLon = () => (st.obs ? st.obs.lon : 0);
  const X = (rel) => ((rel + 180) / 360) * W;
  const Y = (lat) => ((90 - lat) / 180) * H;
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const compass = (az) => COMPASS[Math.round(az / 22.5) % 16];
  const satText = (s) => (s.mode ? `${s.label} · ${s.mode}` : s.label); // map label, with the SSTV mode when known

  // Longitudes relative to the map centre, unwrapped so consecutive points never jump by more than 180°.
  function unwrap(pts) {
    const c = centerLon(), out = [];
    let prev = null;
    for (const p of pts) {
      let l = norm(p[0] - c);
      if (prev !== null) { while (l - prev > 180) l -= 360; while (l - prev < -180) l += 360; }
      out.push([l, p[1], p[2]]);
      prev = l;
    }
    return out;
  }

  function trace(c, u, off) {
    u.forEach(([l, lat], i) => (i ? c.lineTo(X(l + off), Y(lat)) : c.moveTo(X(l + off), Y(lat))));
  }

  // Ring of points at a given angular radius around (lat, lon).
  function circle(lat, lon, radiusDeg) {
    const d = radiusDeg * DEG, p1 = lat * DEG, l1 = lon * DEG, pts = [];
    for (let b = 0; b <= 360; b += 5) {
      const t = b * DEG;
      const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(t));
      const l2 = l1 + Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
      pts.push([l2 / DEG, p2 / DEG]);
    }
    const u = unwrap(pts);
    // A circle around a pole unwraps to a 360° band: close it along the pole.
    if (Math.abs(u[u.length - 1][0] - u[0][0]) > 180) {
      const pole = lat >= 0 ? 90 : -90;
      u.push([u[u.length - 1][0], pole], [u[0][0], pole]);
    }
    return u;
  }

  // Radius (degrees of arc) of the area that can see a satellite at height h km above the horizon.
  const footprintDeg = (h) => Math.acos(RE / (RE + h)) / DEG;

  function sunSubpoint(t) {
    const n = t / 86400000 - 10957.5; // days since J2000.0
    const L = 280.46 + 0.9856474 * n, g = (357.528 + 0.9856003 * n) * DEG;
    const lam = (L + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * DEG, eps = (23.439 - 4e-7 * n) * DEG;
    const ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam)), dec = Math.asin(Math.sin(eps) * Math.sin(lam));
    const gmst = 280.46061837 + 360.98564736629 * n;
    return { lat: dec / DEG, lon: norm(ra / DEG - gmst) };
  }

  function satAt(s, date, gmst) {
    const pv = satellite.propagate(s.satrec, date);
    if (!pv || !pv.position) return null;
    const gd = satellite.eciToGeodetic(pv.position, gmst);
    const r = { lat: gd.latitude / DEG, lon: norm(gd.longitude / DEG), h: gd.height, el: null, az: null, range: null };
    if (st.obs) {
      const la = satellite.ecfToLookAngles(st.obs.gd, satellite.eciToEcf(pv.position, gmst));
      r.el = la.elevation / DEG;
      r.az = ((la.azimuth / DEG) % 360 + 360) % 360;
      r.range = la.rangeSat;
    }
    return r;
  }

  // Decode the world-atlas TopoJSON (quantised, delta-encoded arcs) into a list of polygons of [lon, lat] rings.
  function topoPolygons(topo, object) {
    const [sx, sy] = topo.transform.scale, [tx, ty] = topo.transform.translate;
    const arcs = topo.arcs.map((arc) => {
      let x = 0, y = 0;
      return arc.map(([dx, dy]) => { x += dx; y += dy; return [x * sx + tx, y * sy + ty]; });
    });
    const ring = (ids) => ids.flatMap((i, n) => {
      const a = i >= 0 ? arcs[i] : arcs[~i].slice().reverse();
      return n ? a.slice(1) : a;
    });
    const polys = [];
    for (const g of object.geometries || [object]) {
      if (g.type === "Polygon") polys.push(g.arcs.map(ring));
      else if (g.type === "MultiPolygon") g.arcs.forEach((p) => polys.push(p.map(ring)));
    }
    return polys;
  }

  // ---------- drawing ----------
  function colors() {
    const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
    return {
      sea: v("--map-sea"), land: v("--map-land"), grid: v("--map-grid"), night: v("--map-night"),
      text: v("--text"), muted: v("--muted"), accent: v("--accent"), good: v("--good"), warn: v("--warn"), card: v("--card"),
    };
  }

  function drawBase(c) {
    const key = `${W}x${H}@${dpr}:${centerLon()}:${c.sea}:${c.land}:${!!st.land}`;
    if (key === landKey) return;
    landKey = key;
    landCanvas.width = W * dpr; landCanvas.height = H * dpr;
    const g = landCanvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = c.sea; g.fillRect(0, 0, W, H);
    g.strokeStyle = c.grid; g.lineWidth = 1; g.beginPath();
    for (let lat = -60; lat <= 60; lat += 30) { g.moveTo(0, Y(lat)); g.lineTo(W, Y(lat)); }
    for (let lon = -180; lon < 540; lon += 30) { const x = X(norm(lon - centerLon())); g.moveTo(x, 0); g.lineTo(x, H); }
    g.stroke();
    if (!st.land) return;
    g.fillStyle = c.land;
    for (const poly of st.land) {
      const rings = poly.map(unwrap);
      for (const off of [-360, 0, 360]) {
        g.beginPath();
        for (const u of rings) { trace(g, u, off); g.closePath(); }
        g.fill("evenodd");
      }
    }
  }

  function drawNight(c, t) {
    const sun = sunSubpoint(t), dec = (Math.abs(sun.lat) < 0.01 ? 0.01 : sun.lat) * DEG;
    ctx.beginPath();
    for (let rel = -180; rel <= 180; rel += 2) {
      const h = (rel + centerLon() - sun.lon) * DEG;
      const lat = Math.atan(-Math.cos(h) / Math.tan(dec)) / DEG;
      rel === -180 ? ctx.moveTo(X(rel), Y(lat)) : ctx.lineTo(X(rel), Y(lat));
    }
    const edge = dec > 0 ? H : 0; // the pole in polar night
    ctx.lineTo(W, edge); ctx.lineTo(0, edge); ctx.closePath();
    ctx.fillStyle = c.night; ctx.fill();
  }

  function selectedId() {
    const id = st.pick === "auto" ? st.autoId : st.pick;
    return id && !st.hidden.has(id) ? id : null;
  }

  function groundTrack(s, t) {
    const from = t - TRACK_BACK_MIN * 60000;
    if (st.track && st.track.id === s.id && Math.abs(st.track.from - from) < 15000 && st.track.obsKey === obsKey()) return st.track.pts;
    const pts = [];
    for (let m = 0; m <= TRACK_BACK_MIN + TRACK_AHEAD_MIN; m += 0.5) {
      const d = new Date(from + m * 60000), p = satAt(s, d, satellite.gstime(d));
      if (p) pts.push([p.lon, p.lat, { past: m < TRACK_BACK_MIN, seen: p.el !== null && p.el > 0 }]);
    }
    st.track = { id: s.id, from, pts, obsKey: obsKey() };
    return pts;
  }
  const obsKey = () => (st.obs ? `${st.obs.lat},${st.obs.lon}` : "");

  function drawTrack(c, s, t) {
    const u = unwrap(groundTrack(s, t));
    ctx.lineCap = "round";
    for (const off of OFFSETS) {
      for (let i = 1; i < u.length; i++) {
        const f = u[i][2];
        ctx.beginPath();
        ctx.moveTo(X(u[i - 1][0] + off), Y(u[i - 1][1]));
        ctx.lineTo(X(u[i][0] + off), Y(u[i][1]));
        ctx.strokeStyle = f.seen ? c.good : f.past ? c.muted : c.warn;
        ctx.globalAlpha = f.past ? 0.5 : 1;
        ctx.lineWidth = f.seen ? 4 : 1.5;
        ctx.setLineDash(f.past ? [3, 3] : []);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1; ctx.setLineDash([]);
  }

  function ring(u, stroke, fill, dash) {
    for (const off of [-360, 0, 360]) {
      ctx.beginPath(); trace(ctx, u, off); ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      ctx.setLineDash(dash || []); ctx.strokeStyle = stroke; ctx.lineWidth = 1.2; ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  function label(text, x, y, c, strong, below) {
    ctx.font = `${strong ? 700 : 600} 11px system-ui, -apple-system, "Segoe UI", sans-serif`;
    const w = ctx.measureText(text).width;
    let lx = below ? x - 7 - w : x + 7, ly = below ? y + 18 : y - 7;
    if (lx + w + 4 > W) lx = x - 7 - w;
    if (lx < 3) lx = x + 7;
    if (ly - 10 < 0) ly = y + 16;
    ctx.fillStyle = c.card; ctx.globalAlpha = 0.85; ctx.fillRect(lx - 3, ly - 10, w + 6, 14); ctx.globalAlpha = 1;
    ctx.fillStyle = strong ? c.text : c.muted; ctx.fillText(text, lx, ly);
  }

  function draw() {
    if (!W) return;
    const c = colors(), t = st.simT, date = new Date(t), gmst = satellite.gstime(date);
    drawBase(c);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.drawImage(landCanvas, 0, 0, W, H);
    drawNight(c, t);

    if (st.obs) ring(circle(st.obs.lat, st.obs.lon, footprintDeg(500)), c.text, null, [4, 4]);

    const selId = selectedId(), sel = st.sats.find((s) => s.id === selId);
    const now = new Map();
    for (const s of st.sats) if (!st.hidden.has(s.id)) { const p = satAt(s, date, gmst); if (p) now.set(s.id, p); }

    if (sel && now.has(sel.id)) {
      const p = now.get(sel.id);
      ring(circle(p.lat, p.lon, footprintDeg(p.h)), c.warn, "rgba(240,166,64,0.10)");
      drawTrack(c, sel, t);
    }

    if (st.obs) {
      const x = X(0), y = Y(st.obs.lat);
      ctx.fillStyle = c.text; ctx.strokeStyle = c.card; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 10, y); ctx.lineTo(x + 10, y); ctx.moveTo(x, y - 10); ctx.lineTo(x, y + 10);
      ctx.strokeStyle = c.text; ctx.lineWidth = 1.5; ctx.stroke();
      label("You", x, y, c, true, true);
    }

    dots = [];
    const order = [...now.keys()].sort((a, b) => (a === selId) - (b === selId)); // selected drawn last, on top
    for (const id of order) {
      const s = st.sats.find((x) => x.id === id), p = now.get(id);
      const x = X(norm(p.lon - centerLon())), y = Y(p.lat), seen = p.el !== null && p.el > 0, isSel = id === selId;
      dots.push({ id, x, y });
      ctx.beginPath(); ctx.arc(x, y, isSel ? 6 : 4.5, 0, 2 * Math.PI);
      ctx.fillStyle = seen ? c.good : isSel ? c.warn : c.accent; ctx.fill();
      ctx.lineWidth = isSel ? 2.5 : 1.5; ctx.strokeStyle = isSel ? c.text : c.card; ctx.stroke();
      if (isSel || seen || id === st.hover) label(satText(s), x, y, c, isSel || seen);
    }
    updateStatus(sel, sel && now.get(sel.id), date);
  }

  function updateStatus(sel, p, date) {
    const pad = (n) => String(n).padStart(2, "0");
    const time = `${date.toLocaleDateString(undefined, { weekday: "short" })} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    $("map-clock").textContent = st.speed === 1 ? `Live · ${time}` : `Map time ${time} · ${st.speed}× speed`;
    let info = "";
    if (sel && p) {
      info = `${sel.label} · ${sel.freq} MHz · SSTV ${sel.mode || "mode not published"} · ${Math.round(p.h)} km up · `;
      if (!st.obs) info += "set your location to see when it's in range";
      else if (p.el > 0) info += `in range now: ${p.el.toFixed(0)}° elevation, ${compass(p.az)}`;
      else info += `below your horizon, ${Math.round(p.range).toLocaleString()} km away`;
    } else if (!sel) info = "Pick a satellite to see its track.";
    $("map-info").textContent = info;
  }

  // ---------- loop and events ----------
  function frame(nowMs) {
    requestAnimationFrame(frame);
    const dt = nowMs - st.lastReal;
    st.lastReal = nowMs;
    if (document.hidden || !st.sats.length) return;
    st.simT = st.speed === 1 ? Date.now() : st.simT + dt * st.speed;
    if (st.view === "3d") {
      if (!globe) return;
      globe.render(st.simT); // every frame, so dragging the globe stays smooth
      if (nowMs - lastStatus > 250) {
        lastStatus = nowMs;
        const date = new Date(st.simT), sel = st.sats.find((s) => s.id === selectedId());
        updateStatus(sel, sel && satAt(sel, date, satellite.gstime(date)), date);
      }
      return;
    }
    if (!W) return;
    if (nowMs - lastDraw < (st.speed === 1 ? 1000 : 50)) return;
    lastDraw = nowMs;
    draw();
  }
  const redraw = () => { lastDraw = 0; };

  function resize() {
    const wrap = canvas.parentElement;
    W = Math.round(wrap.clientWidth); H = Math.round(W / 2);
    // Full screen: the map gets whatever height is left, so fit the 2:1 map inside it.
    if (isFull() && wrap.clientHeight && H > wrap.clientHeight) { H = Math.round(wrap.clientHeight); W = H * 2; }
    dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    landKey = "";
    redraw();
  }

  function nearest(ev) {
    const r = canvas.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
    let best = null, bd = 18 * 18;
    for (const d of dots) { const dd = (d.x - x) ** 2 + (d.y - y) ** 2; if (dd < bd) { bd = dd; best = d.id; } }
    return best;
  }

  function setSpeed(speed) {
    st.speed = speed;
    if (speed === 1) st.simT = Date.now();
    document.querySelectorAll("#map-speed button").forEach((b) => b.classList.toggle("primary", +b.dataset.speed === speed));
    redraw();
  }

  // ---------- 2D map / 3D globe switch ----------
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src; s.onload = resolve; s.onerror = () => reject(new Error(`couldn't load ${src.split("/").pop()}`));
      document.head.appendChild(s);
    });
  }

  function ensureGlobe() {
    if (globe) return Promise.resolve(globe);
    globeLoading = globeLoading || (async () => {
      if (!window.THREE) await loadScript(THREE_URL);
      if (!THREE.OrbitControls) await loadScript(ORBIT_URL);
      if (!window.SstvGlobe) await loadScript("globe.js");
      globe = SstvGlobe.create($("globe"), core);
      return globe;
    })();
    return globeLoading;
  }

  async function setView(view) {
    st.view = view;
    pref.set("mapView", view);
    const is3d = view === "3d";
    document.querySelectorAll("#map-view button").forEach((b) => b.classList.toggle("primary", b.dataset.view === view));
    $("alt-wrap").hidden = !is3d;
    $("globe-hint").hidden = !is3d;
    canvas.hidden = is3d;
    $("globe").hidden = !is3d;
    if (is3d) {
      $("map-info").textContent = "Loading the 3D globe…";
      try {
        await ensureGlobe();
        globe.resize();
      } catch (e) {
        globeLoading = null;
        await setView("2d");
        $("map-info").textContent = `The 3D globe couldn't start in this browser (${e.message}), so you're seeing the 2D map.`;
        lastDraw = performance.now() + 4000; // keep the message up for a few seconds
        return;
      }
    }
    redraw();
  }

  // ---------- full screen ----------
  // Uses the Fullscreen API where it exists; otherwise (e.g. iPhone Safari) the panel just fills the window.
  const isFull = () => $("map-card").classList.contains("is-full");

  function setFull(on) {
    const card = $("map-card");
    if (on === isFull()) return;
    card.classList.toggle("is-full", on);
    document.body.classList.toggle("no-scroll", on);
    $("map-full").textContent = on ? "✕ Exit full screen" : "⛶ Full screen";
    $("map-full").setAttribute("aria-pressed", String(on));
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    if (on && !fsEl) {
      const req = card.requestFullscreen || card.webkitRequestFullscreen;
      if (req) Promise.resolve(req.call(card)).catch(() => { /* window-filling fallback stays */ });
    } else if (!on && fsEl) {
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit) Promise.resolve(exit.call(document)).catch(() => {});
    }
    if (globe) globe.resize();
    redraw();
  }

  function onFullscreenChange() {
    if (!(document.fullscreenElement || document.webkitFullscreenElement)) setFull(false);
  }

  // What globe.js needs from the shared map state.
  const core = {
    st, satAt, footprintDeg, sunSubpoint, colors, selectedId, satText,
    select(id) { st.pick = id; $("map-sat").value = id; redraw(); },
  };

  function fillSelect() {
    const sel = $("map-sat");
    sel.innerHTML = `<option value="auto">Next pass (auto)</option>` +
      st.sats.map((s) => `<option value="${s.id}">${s.label.replace(/[<>&"]/g, "")}</option>`).join("");
    sel.value = st.pick;
  }

  function init() {
    canvas = $("map");
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    landCanvas = document.createElement("canvas");
    new ResizeObserver(resize).observe(canvas.parentElement);
    canvas.addEventListener("mousemove", (ev) => { const id = nearest(ev); if (id !== st.hover) { st.hover = id; canvas.style.cursor = id ? "pointer" : "default"; redraw(); } });
    canvas.addEventListener("mouseleave", () => { st.hover = null; redraw(); });
    canvas.addEventListener("click", (ev) => { const id = nearest(ev); if (id) { st.pick = id; $("map-sat").value = id; redraw(); } });
    $("map-sat").addEventListener("change", (ev) => { st.pick = ev.target.value; redraw(); });
    $("map-speed").addEventListener("click", (ev) => { const s = ev.target.dataset && ev.target.dataset.speed; if (s) setSpeed(+s); });
    $("map-view").addEventListener("click", (ev) => { const v = ev.target.dataset && ev.target.dataset.view; if (v && v !== st.view) setView(v); });
    $("alt-exag").checked = st.altScale > 1;
    $("alt-exag").addEventListener("change", (ev) => { st.altScale = ev.target.checked ? 3 : 1; pref.set("altScale", st.altScale); });
    setSpeed(st.speed);
    setView(st.view);
    $("map-full").addEventListener("click", () => setFull(!isFull()));
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") setFull(false); });
    fetch(LAND_URL).then((r) => r.json()).then((topo) => {
      st.land = topoPolygons(topo, topo.objects.land);
      landKey = ""; redraw();
    }).catch(() => { /* the map still works without coastlines */ });
    requestAnimationFrame(frame);
  }

  window.SstvMap = {
    setSatellites(list) {
      st.sats = list.map((s) => ({ ...s, satrec: satellite.twoline2satrec(s.l1, s.l2) }));
      if (st.pick !== "auto" && !st.sats.some((s) => s.id === st.pick)) st.pick = "auto";
      st.track = null;
      fillSelect(); redraw();
    },
    setObserver(lat, lon, altKm) {
      st.obs = { lat, lon, gd: { latitude: lat * DEG, longitude: lon * DEG, height: altKm || 0 } };
      landKey = ""; st.track = null; redraw();
    },
    setHidden(ids) { st.hidden = new Set(ids); redraw(); },
    setAuto(id) { if (id !== st.autoId) { st.autoId = id; redraw(); } },
    // Replay a pass: select the satellite and rewind the map to just before AOS.
    showPass(id, aosMs) {
      st.pick = id; $("map-sat").value = id;
      setSpeed(30);
      st.simT = aosMs - 3 * 60000;
      redraw();
    },
  };

  init();
})();
