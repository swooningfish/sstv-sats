/* 3D globe for the satellite map: satellites at their real (or exaggerated) altitude, each with a
   cone down to the edge of the area that can hear it. three.js r128, loaded on demand by map.js. */
(() => {
  "use strict";
  const DEG = Math.PI / 180;
  const RE = 6378.137; // km
  const SEG = 48;      // segments around each cone
  const TRACK_BACK_MIN = 10, TRACK_AHEAD_MIN = 100;

  // Geographic position -> three.js world space, matching SphereGeometry's equirectangular texture.
  function vec(lat, lon, r, out = new THREE.Vector3()) {
    const phi = (lon + 180) * DEG, theta = (90 - lat) * DEG;
    return out.set(-r * Math.cos(phi) * Math.sin(theta), r * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta));
  }

  // Points on the ground at a given arc radius around (lat, lon).
  function ring(lat, lon, radiusDeg) {
    const d = radiusDeg * DEG, p1 = lat * DEG, l1 = lon * DEG, pts = [];
    for (let i = 0; i <= SEG; i++) {
      const t = (i / SEG) * 2 * Math.PI;
      const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(t));
      const l2 = l1 + Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
      pts.push([p2 / DEG, l2 / DEG]);
    }
    return pts;
  }

  function create(container, core) {
    const st = core.st;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); // throws if WebGL is unavailable
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.appendChild(renderer.domElement);
    const labelLayer = document.createElement("div");
    labelLayer.className = "globe-labels";
    container.appendChild(labelLayer);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    Object.assign(controls, { enableDamping: true, dampingFactor: 0.08, enablePan: false, minDistance: 1.25, maxDistance: 9, rotateSpeed: 0.5, zoomSpeed: 0.7 });

    // Earth: the same coastlines as the 2D map, painted onto an equirectangular texture.
    const texCanvas = document.createElement("canvas");
    texCanvas.width = 2048; texCanvas.height = 1024;
    const texture = new THREE.CanvasTexture(texCanvas);
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(1, 128, 64), new THREE.MeshPhongMaterial({ map: texture, shininess: 6, specular: 0x111111 })));
    const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(1.02, 64, 32), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.08, side: THREE.BackSide }));
    scene.add(atmosphere);
    scene.add(new THREE.AmbientLight(0xffffff, 0.62));
    const sunLight = new THREE.DirectionalLight(0xffffff, 0.7); // lit side = day
    scene.add(sunLight);

    const you = new THREE.Mesh(new THREE.SphereGeometry(0.012, 16, 12), new THREE.MeshBasicMaterial());
    you.visible = false;
    scene.add(you);

    const trackGeo = new THREE.BufferGeometry();
    const track = new THREE.Line(trackGeo, new THREE.LineBasicMaterial({ vertexColors: true }));
    scene.add(track);
    let trackKey = "";

    let c = core.colors(), texKey = "", lastColors = 0, aimedAt = "";
    const objs = new Map();
    const labelEls = [];
    let screenDots = [];

    function paintTexture() {
      const key = `${c.sea}|${c.land}|${!!st.land}`;
      if (key === texKey) return;
      texKey = key;
      const g = texCanvas.getContext("2d"), w = texCanvas.width, h = texCanvas.height;
      const X = (lon) => ((lon + 180) / 360) * w, Y = (lat) => ((90 - lat) / 180) * h;
      g.fillStyle = c.sea; g.fillRect(0, 0, w, h);
      g.strokeStyle = c.grid; g.lineWidth = 2; g.beginPath();
      for (let lat = -60; lat <= 60; lat += 30) { g.moveTo(0, Y(lat)); g.lineTo(w, Y(lat)); }
      for (let lon = -180; lon <= 180; lon += 30) { g.moveTo(X(lon), 0); g.lineTo(X(lon), h); }
      g.stroke();
      if (st.land) {
        g.fillStyle = c.land;
        for (const poly of st.land) {
          for (const off of [-360, 0, 360]) {
            g.beginPath();
            for (const r of poly) {
              let prev = null;
              r.forEach(([lon, lat], i) => {
                let l = lon;
                if (prev !== null) { while (l - prev > 180) l -= 360; while (l - prev < -180) l += 360; }
                prev = l;
                i ? g.lineTo(X(l + off), Y(lat)) : g.moveTo(X(l + off), Y(lat));
              });
              g.closePath();
            }
            g.fill("evenodd");
          }
        }
      }
      texture.needsUpdate = true;
      atmosphere.material.color.set(c.accent);
      you.material.color.set(c.text);
    }

    function objFor(s) {
      let o = objs.get(s.id);
      if (o) return o;
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.016, 16, 12), new THREE.MeshBasicMaterial());
      const stalkGeo = new THREE.BufferGeometry();
      stalkGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
      const stalk = new THREE.Line(stalkGeo, new THREE.LineBasicMaterial({ transparent: true, opacity: 0.55 }));
      const coneGeo = new THREE.BufferGeometry();
      coneGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array((SEG + 2) * 3), 3));
      const idx = [];
      for (let i = 1; i <= SEG; i++) idx.push(0, i, i + 1);
      coneGeo.setIndex(idx);
      const cone = new THREE.Mesh(coneGeo, new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide, depthWrite: false }));
      const edgeGeo = new THREE.BufferGeometry();
      edgeGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array((SEG + 1) * 3), 3));
      const edge = new THREE.Line(edgeGeo, new THREE.LineBasicMaterial({ transparent: true, opacity: 0.8 }));
      scene.add(dot, stalk, cone, edge);
      o = { dot, stalk, cone, edge };
      objs.set(s.id, o);
      return o;
    }

    function setVisible(o, v) { o.dot.visible = o.stalk.visible = o.cone.visible = o.edge.visible = v; }

    const tmp = new THREE.Vector3();
    function updateSat(s, o, p, isSel) {
      const seen = p.el !== null && p.el > 0;
      const color = seen ? c.good : isSel ? c.warn : c.accent;
      const r = 1 + (p.h / RE) * (st.altScale || 1);
      vec(p.lat, p.lon, r, o.dot.position);
      o.dot.material.color.set(color);
      o.dot.scale.setScalar(isSel ? 1.6 : 1);

      const sp = o.stalk.geometry.attributes.position;
      vec(p.lat, p.lon, 1.001, tmp); sp.setXYZ(0, tmp.x, tmp.y, tmp.z);
      sp.setXYZ(1, o.dot.position.x, o.dot.position.y, o.dot.position.z);
      sp.needsUpdate = true;
      o.stalk.material.color.set(color);

      // Cone from the satellite down to the edge of its coverage on the ground.
      const pts = ring(p.lat, p.lon, core.footprintDeg(p.h));
      const cp = o.cone.geometry.attributes.position, ep = o.edge.geometry.attributes.position;
      cp.setXYZ(0, o.dot.position.x, o.dot.position.y, o.dot.position.z);
      pts.forEach(([lat, lon], i) => {
        vec(lat, lon, 1.002, tmp);
        cp.setXYZ(i + 1, tmp.x, tmp.y, tmp.z);
        ep.setXYZ(i, tmp.x, tmp.y, tmp.z);
      });
      cp.needsUpdate = true; ep.needsUpdate = true;
      o.cone.geometry.computeBoundingSphere();
      o.edge.geometry.computeBoundingSphere();
      o.cone.material.color.set(color);
      o.cone.material.opacity = isSel ? 0.24 : seen ? 0.18 : 0.08;
      o.edge.material.color.set(color);
      o.edge.visible = isSel || seen;
      return seen;
    }

    // Selected satellite's path for the next 100 minutes, drawn at its altitude; green while you can hear it.
    function updateTrack(sel, t) {
      if (!sel) { track.visible = false; return; }
      const from = t - TRACK_BACK_MIN * 60000;
      const key = `${sel.id}|${Math.round(from / 15000)}|${st.altScale}|${st.obs ? st.obs.lat + "," + st.obs.lon : ""}|${c.good}`;
      track.visible = true;
      if (key === trackKey) return;
      trackKey = key;
      const pos = [], col = [], cGood = new THREE.Color(c.good), cWarn = new THREE.Color(c.warn), cPast = new THREE.Color(c.muted);
      for (let m = 0; m <= TRACK_BACK_MIN + TRACK_AHEAD_MIN; m += 0.5) {
        const d = new Date(from + m * 60000), p = core.satAt(sel, d, satellite.gstime(d));
        if (!p) continue;
        vec(p.lat, p.lon, 1 + (p.h / RE) * (st.altScale || 1), tmp);
        pos.push(tmp.x, tmp.y, tmp.z);
        const cc = p.el !== null && p.el > 0 ? cGood : m < TRACK_BACK_MIN ? cPast : cWarn;
        col.push(cc.r, cc.g, cc.b);
      }
      trackGeo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      trackGeo.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
      trackGeo.computeBoundingSphere();
    }

    // Hidden behind the Earth? (ray from the camera hits the globe first)
    function occluded(p) {
      const cam = camera.position, d = tmp.copy(p).sub(cam), len = d.length();
      d.divideScalar(len);
      const b = cam.dot(d), cc = cam.lengthSq() - 0.995 * 0.995, disc = b * b - cc;
      if (disc < 0) return false;
      const hit = -b - Math.sqrt(disc);
      return hit > 0 && hit < len;
    }

    function toScreen(p) {
      const v = p.clone().project(camera), el = renderer.domElement;
      return { x: ((v.x + 1) / 2) * el.clientWidth, y: ((1 - v.y) / 2) * el.clientHeight };
    }

    function placeLabels(items) {
      while (labelEls.length < items.length) {
        const d = document.createElement("div");
        d.className = "globe-label";
        labelLayer.appendChild(d);
        labelEls.push(d);
      }
      labelEls.forEach((el, i) => {
        const it = items[i];
        if (!it || occluded(it.pos)) { el.style.display = "none"; return; }
        const s = toScreen(it.pos);
        el.style.display = "";
        el.textContent = it.text;
        el.classList.toggle("strong", !!it.strong);
        el.style.transform = `translate(${(s.x + 8).toFixed(1)}px, ${(s.y - 20).toFixed(1)}px)`;
      });
    }

    function aim() {
      const key = st.obs ? `${st.obs.lat},${st.obs.lon}` : "none";
      if (key === aimedAt) return;
      aimedAt = key;
      const lat = st.obs ? st.obs.lat : 20, lon = st.obs ? st.obs.lon : 0;
      vec(Math.max(-60, Math.min(60, lat - 8)), lon, 3.6, camera.position);
      controls.update();
    }

    function render(t) {
      const nowMs = performance.now();
      if (nowMs - lastColors > 1000) { lastColors = nowMs; c = core.colors(); }
      paintTexture();
      aim();
      const date = new Date(t), gmst = satellite.gstime(date), selId = core.selectedId();
      const sun = core.sunSubpoint(t);
      vec(sun.lat, sun.lon, 10, sunLight.position);

      const labels = [], seenIds = new Set();
      screenDots = [];
      if (st.obs) {
        you.visible = true;
        vec(st.obs.lat, st.obs.lon, 1.003, you.position);
        labels.push({ text: "You", pos: you.position.clone(), strong: true });
      }
      let sel = null;
      for (const s of st.sats) {
        const o = objFor(s);
        seenIds.add(s.id);
        const p = st.hidden.has(s.id) ? null : core.satAt(s, date, gmst);
        if (!p) { setVisible(o, false); continue; }
        setVisible(o, true);
        const isSel = s.id === selId;
        if (isSel) sel = s;
        const seen = updateSat(s, o, p, isSel);
        if (isSel || seen) labels.push({ text: core.satText(s), pos: o.dot.position.clone(), strong: true });
        if (!occluded(o.dot.position)) screenDots.push({ id: s.id, ...toScreen(o.dot.position) });
      }
      for (const [id, o] of objs) if (!seenIds.has(id)) setVisible(o, false); // removed satellites
      updateTrack(sel, t);
      controls.update();
      renderer.render(scene, camera);
      placeLabels(labels);
    }

    function resize() {
      const w = container.clientWidth;
      if (!w) return;
      const full = container.closest(".is-full");
      const h = full ? container.parentElement.clientHeight : Math.round(Math.min(Math.max(w * 0.72, 300), 560));
      if (!h) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }

    // Click (not drag) on a satellite to track it.
    let down = null;
    renderer.domElement.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY }; });
    renderer.domElement.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return;
      const r = renderer.domElement.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      let best = null, bd = 16 * 16;
      for (const d of screenDots) { const dd = (d.x - x) ** 2 + (d.y - y) ** 2; if (dd < bd) { bd = dd; best = d.id; } }
      if (best) core.select(best);
    });
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    ro.observe(container.parentElement); // full-screen changes the space available
    resize();
    return { render, resize };
  }

  window.SstvGlobe = { create };
})();
