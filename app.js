/* Climbable-Trees — STATIC demo frontend (GitHub Pages, no API server).
 *
 * Same UI as the full app, but candidates come from pre-scored per-city JSON
 * snapshots (docs/data/*.json, built by scripts/export_static.py). Radius
 * filtering and the reach-match FORM GUESS run client-side; street photos come
 * straight from the Mapillary Graph API (client token, CC BY-SA attribution),
 * with a Wikipedia species reference as fallback.
 *
 * Confidence is rendered honestly: circle color = score, circle opacity =
 * confidence, and the detail panel labels the reach-match a "form-based guess".
 */

// Mapillary CLIENT token — public by design (browser-embedded), read-only.
const MLY_TOKEN = "MLY|27259450777079853|57f15428329a51c19b24017613444fb6";

const map = new maplibregl.Map({
  container: "map",
  // "bright": OpenFreeMap's soft, pastel style — the smooth Apple-Maps-ish look
  style: "https://tiles.openfreemap.org/styles/bright",
  center: [-122.4194, 37.7749], // San Francisco (dense real data on load)
  zoom: 15,
});
map.addControl(new maplibregl.NavigationControl(), "top-left");

let searchPoint = null;      // [lon, lat]
let searchMarker = null;
let polygon = [];            // array of [lon,lat] while drawing
let polygonMode = false;

let cityManifest = [];             // from data/cities.json
const cityTrees = {};              // source_id -> tree rows (lazy-loaded)

const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function setStatus(msg) { statusEl.textContent = msg || ""; }

// ---- confidence -> badge tier -------------------------------------------------
function confTier(c) {
  if (c >= 0.55) return "high";
  if (c >= 0.3) return "med";
  return "low";
}

// scores/confidences render as whole percentages everywhere
const pct = (x) => `${Math.round((x ?? 0) * 100)}%`;

// ---- cartoon tree icon for strong candidates ------------------------------------
// Strong candidates (score >= 0.55, the green range) render as a little tree;
// lower-score trees KEEP their amber/rust dots so the score encoding survives.
const TREE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
  <ellipse cx="24" cy="43" rx="9" ry="2.6" fill="rgba(40,60,40,0.25)"/>
  <path d="M21.6 29h4.8v13h-4.8z" fill="#8d5a2b" stroke="#5d3a18" stroke-width="1.4" stroke-linejoin="round"/>
  <circle cx="14.5" cy="23.5" r="8.2" fill="#4cc06d" stroke="#1e7a3e" stroke-width="1.6"/>
  <circle cx="33.5" cy="23.5" r="8.2" fill="#37a355" stroke="#1e7a3e" stroke-width="1.6"/>
  <circle cx="24" cy="14.5" r="10.2" fill="#3fae5e" stroke="#1e7a3e" stroke-width="1.6"/>
  <circle cx="24" cy="22.5" r="9.4" fill="#45b862" stroke="none"/>
  <circle cx="19.5" cy="13.5" r="2.1" fill="#8fe0a8"/>
</svg>`;

function loadTreeIcon() {
  return new Promise((resolve) => {
    const img = new Image(48, 48);
    img.onload = () => { map.addImage("tree-icon", img); resolve(); };
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(TREE_SVG)}`;
  });
}

// ---- map layers ---------------------------------------------------------------
map.on("load", async () => {
  await loadTreeIcon();
  map.addSource("trees", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "trees",
    type: "circle",
    source: "trees",
    filter: ["<", ["coalesce", ["get", "score"], 0], 0.55],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 4, 18, 9],
      "circle-color": [
        "interpolate", ["linear"], ["coalesce", ["get", "score"], 0],
        0, "#b0563b", 0.4, "#c9922e", 0.7, "#2e9e5b",
      ],
      "circle-opacity": 0.85,
      "circle-stroke-color": "#0c0f13",
      "circle-stroke-width": 1,
    },
  });
  map.addLayer({
    id: "trees-icons",
    type: "symbol",
    source: "trees",
    filter: [">=", ["coalesce", ["get", "score"], 0], 0.55],
    layout: {
      "icon-image": "tree-icon",
      "icon-size": ["interpolate", ["linear"], ["zoom"], 12, 0.5, 18, 1.05],
      "icon-allow-overlap": true,
      "icon-anchor": "bottom",
    },
    paint: { "icon-opacity": 0.85 },
  });

  map.addSource("radius", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "radius", type: "fill", source: "radius",
    paint: { "fill-color": "#4ea36b", "fill-opacity": 0.08 },
  });
  map.addLayer({
    id: "radius-line", type: "line", source: "radius",
    paint: { "line-color": "#4ea36b", "line-opacity": 0.5, "line-width": 1 },
  });

  map.addSource("poly", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "poly", type: "line", source: "poly",
    paint: { "line-color": "#6b4ea3", "line-width": 2, "line-dasharray": [2, 1] },
  });

  map.on("click", onMapClick);
  for (const layer of ["trees", "trees-icons"]) {
    map.on("click", layer, onTreeClick);
    map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }

  search();
});

function emptyFC() { return { type: "FeatureCollection", features: [] }; }

function onMapClick(e) {
  if (polygonMode) {
    polygon.push([e.lngLat.lng, e.lngLat.lat]);
    drawPolygon();
    return;
  }
  searchPoint = [e.lngLat.lng, e.lngLat.lat];
  if (searchMarker) searchMarker.remove();
  searchMarker = new maplibregl.Marker({ color: "#4ea36b" })
    .setLngLat(searchPoint).addTo(map);
  drawRadius();
}

// ---- radius circle (approx polygon) ------------------------------------------
function drawRadius() {
  if (!searchPoint) return;
  const r = parseFloat($("radius").value) || 500;
  map.getSource("radius").setData(circlePolygon(searchPoint, r));
}
function circlePolygon(center, radiusM, steps = 64) {
  const [lon, lat] = center;
  const coords = [];
  const dLat = radiusM / 111320;
  const dLon = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * 2 * Math.PI;
    coords.push([lon + dLon * Math.cos(t), lat + dLat * Math.sin(t)]);
  }
  return { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Polygon", coordinates: [coords] } }] };
}

// ---- polygon draw -------------------------------------------------------------
function drawPolygon() {
  const line = polygon.length ? [...polygon, polygon[0]] : [];
  map.getSource("poly").setData({
    type: "FeatureCollection",
    features: line.length ? [{ type: "Feature", geometry: { type: "LineString", coordinates: line } }] : [],
  });
}
function pointInPolygon(pt, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
    const intersect = yi > pt[1] !== yj > pt[1] &&
      pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

// ---- distance helpers -----------------------------------------------------------
function distanceM(a, b) {
  const R = 6371000, toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(b[1] - a[1]), dLon = toRad(b[0] - a[0]);
  const s = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
function fmtDistance(m) { return m < 950 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`; }

// ---- static data loading --------------------------------------------------------
async function loadManifest() {
  if (cityManifest.length) return cityManifest;
  const resp = await fetch("data/cities.json");
  cityManifest = await resp.json();
  return cityManifest;
}
async function loadCityTrees(entry) {
  if (!cityTrees[entry.source_id]) {
    setStatus(`Loading ${entry.city} snapshot (${entry.count} trees)…`);
    const resp = await fetch(entry.file);
    cityTrees[entry.source_id] = await resp.json();
  }
  return cityTrees[entry.source_id];
}
function nearestCity(pt) {
  let best = null, bestD = 80000; // must be within 80 km of a city center
  for (const c of cityManifest) {
    const d = distanceM(pt, c.center);
    if (d <= bestD) { best = c; bestD = d; }
  }
  return best;
}

// ---- search (client-side filter over the snapshot) ------------------------------
async function search() {
  if (!searchPoint) {
    const c = map.getCenter();
    searchPoint = [c.lng, c.lat];
  }
  setStatus("Searching…");
  try {
    await loadManifest();
    const cityEntry = nearestCity(searchPoint);
    if (!cityEntry) {
      map.getSource("trees").setData(emptyFC());
      setStatus("No snapshot city within 80 km — pick one from the selector.");
      return;
    }
    const rows = await loadCityTrees(cityEntry);
    const radius = parseFloat($("radius").value) || 500;
    const publicOnly = $("public_only").checked;
    const tiersOn = {
      high: $("conf-high").checked,
      med: $("conf-med").checked,
      low: $("conf-low").checked,
    };

    let trees = rows.filter((t) =>
      distanceM(searchPoint, [t.lon, t.lat]) <= radius &&
      tiersOn[confTier(t.confidence || 0)] &&
      (!publicOnly || t.eligible !== false));
    trees.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    trees = trees.slice(0, 500);

    let feats = trees.map((t) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [t.lon, t.lat] },
      properties: { score: t.score, confidence: t.confidence, _raw: JSON.stringify(t) },
    }));
    if (polygon.length >= 3) {
      feats = feats.filter((f) => pointInPolygon(f.geometry.coordinates, polygon));
    }
    map.getSource("trees").setData({ type: "FeatureCollection", features: feats });
    setStatus(`${feats.length} candidate tree(s) — ${cityEntry.city} snapshot. ` +
      `Ranked candidates, NOT a safety certification.`);
  } catch (err) {
    setStatus(`Search failed: ${err.message}`);
  }
}

// ---- reach-match FORM GUESS, ported from score/reach.py -------------------------
// v1 has no per-branch data, so this is the same degradation path the server
// runs: species scaffold-form + trunk-size plausibility. NOT a measured ladder.
function fromWhy(why, feature, key) {
  for (const w of why || []) if (w && w.feature === feature) return w[key];
  return undefined;
}
function reachGuess(t) {
  const weight = parseFloat($("weight").value) || 70;
  const dMin = parseFloat($("d_min").value) || 10;
  const effDmin = Math.round(dMin * Math.cbrt(weight / 70) * 100) / 100;

  const scaffold = fromWhy(t.why_scored, "species", "scaffold_form");
  const fDbh = fromWhy(t.why_scored, "dbh", "value");
  const estimated = !!fromWhy(t.why_scored, "dbh", "estimated");

  if (scaffold == null && fDbh == null) {
    return { mode: "form_based_guess", is_measured_ladder: false, reachable: false,
             plausibility: null, confidence: 0.05, effective_d_min_cm: effDmin };
  }
  const form = scaffold == null ? 0.4 : scaffold;
  const size = fDbh == null ? 0.3 : fDbh;
  const plausibility = Math.round((0.65 * form + 0.35 * size) * 10000) / 10000;
  let conf = 0.35;
  if (scaffold == null) conf -= 0.15;
  if (estimated) conf -= 0.10;
  conf = Math.max(0.05, Math.round(conf * 1000) / 1000);
  return { mode: "form_based_guess", is_measured_ladder: false,
           reachable: plausibility >= 0.4, plausibility,
           confidence: conf, effective_d_min_cm: effDmin };
}

// ---- detail panel ---------------------------------------------------------------
function onTreeClick(e) {
  const t = JSON.parse(e.features[0].properties._raw);
  showDetail(t);
}

let currentTree = null;   // for the photo-analyzer inventory cross-check

function showDetail(t) {
  currentTree = t;
  $("detail").classList.remove("hidden");
  $("d-common").textContent = t.common || t.genus || "Unknown tree";
  $("d-sci").textContent = t.scientific || "";

  const rm = reachGuess(t);

  // short facts — the at-a-glance summary (max 5)
  const tier = confTier(t.confidence || 0);
  const facts = [
    `Score <strong>${pct(t.score)}</strong> · ${tier} confidence`,
  ];
  if (t.height_m != null) facts.push(`Height ~<strong>${Math.round(t.height_m)} m</strong>`);
  if (t.dbh_cm != null) facts.push(`Trunk <strong>${Math.round(t.dbh_cm)} cm</strong> thick`);
  if (rm.plausibility != null) {
    facts.push(`First branch not measured — low-branch likelihood <strong>${pct(rm.plausibility)}</strong>`);
  }
  if (searchPoint) {
    facts.push(`<strong>${fmtDistance(distanceM(searchPoint, [t.lon, t.lat]))}</strong> from your search point`);
  }
  $("d-facts").innerHTML = facts.slice(0, 5).map((f) => `<li>${f}</li>`).join("");

  // match category: label + what it means, in plain language
  $("d-reach").innerHTML = rm.is_measured_ladder
    ? `<span class="badge high">measured ladder</span>
       <div class="hint">Someone actually measured this tree's branches — the
       match is based on real branch positions, not a guess.</div>`
    : `<span class="badge guess">form-based guess</span>
       <div class="hint">An educated guess from this species' typical shape and
       trunk size — nobody has measured this tree's branches yet.</div>`;

  // score breakdown: short friendly titles, whole percentages, no sub-notes
  const FEATURE_TITLES = {
    species: "Species wood & form",
    dbh: "Trunk size plausibility",
    street_geometry: "Street-level branch measurements",
    _aggregate: "Overall weighted score",
    _eligibility: "Eligibility & hazard gate",
  };
  const why = t.why_scored || [];
  $("d-why").innerHTML = why.map((w) => {
    const title = FEATURE_TITLES[w.feature] || w.feature.replace(/_/g, " ");
    const v = typeof w.value === "number" ? `<strong>${pct(w.value)}</strong>`
      : (w.value == null ? "<em>not available</em>" : w.value);
    return `<li>${title}: ${v}</li>`;
  }).join("");

  // provenance
  const prov = t.provenance || {};
  $("d-prov").innerHTML =
    `Signals: ${(prov.signals || []).join(", ")}<br>` +
    `Source: ${prov.source_id || "—"}<br>` +
    `License: ${prov.license || "—"}<br>` +
    (prov.source_url ? `<a href="${prov.source_url}" target="_blank" rel="noopener">source</a><br>` : "") +
    `<em>${prov.disclaimer || "Static snapshot — ranked candidates, not a safety certification."}</em>`;

  loadTreePhoto(t);
}

// ---- tree photo: Mapillary street-level (browser-direct), else Wikipedia --------
async function loadTreePhoto(t) {
  const slot = $("d-photo");
  slot.innerHTML = `<div class="photo-placeholder">Loading photo…</div>`;
  try {
    const info = await mapillaryPhoto(t.lat, t.lon);
    if (info) {
      // CC BY-SA: contributor + Mapillary logo/link must render with the image.
      slot.innerHTML =
        `<img class="species-photo" src="${info.image}" alt="street-level photo at this tree" loading="lazy" />` +
        `<div class="photo-credit">© ${info.creator || "contributor"} · ` +
        `<a href="${info.url}" target="_blank" rel="noopener"><span class="mly-logo" aria-label="Mapillary"></span> Mapillary</a>` +
        ` CC BY-SA${info.date ? ` · ${info.date}` : ""}</div>`;
      return;
    }
  } catch (e) { /* fall through to species photo */ }
  await loadSpeciesPhoto(t);
}

async function mapillaryPhoto(lat, lon, radiusM = 50) {
  const dLat = radiusM / 111320;
  const dLon = radiusM / (111320 * Math.max(0.2, Math.cos((lat * Math.PI) / 180)));
  const q = new URLSearchParams({
    access_token: MLY_TOKEN,
    bbox: `${lon - dLon},${lat - dLat},${lon + dLon},${lat + dLat}`,
    fields: "id,thumb_1024_url,computed_geometry,captured_at,creator",
    limit: 20,
  });
  const data = await (await fetch(`https://graph.mapillary.com/images?${q}`)).json();
  let best = null, bestD2 = Infinity;
  for (const img of data.data || []) {
    const c = (img.computed_geometry || {}).coordinates || [];
    if (c.length !== 2 || !img.thumb_1024_url) continue;
    const dx = (c[0] - lon) * Math.cos((lat * Math.PI) / 180), dy = c[1] - lat;
    if (dx * dx + dy * dy < bestD2) { best = img; bestD2 = dx * dx + dy * dy; }
  }
  if (!best) return null;
  return {
    image: best.thumb_1024_url,
    url: `https://www.mapillary.com/app/?focus=photo&pKey=${best.id}`,
    creator: (best.creator || {}).username,
    date: best.captured_at ? new Date(best.captured_at).toISOString().slice(0, 7) : null,
  };
}

// ---- species reference photo (Wikipedia REST, CORS-open) ------------------------
async function loadSpeciesPhoto(t) {
  const slot = $("d-photo");
  try {
    let d = null;
    for (const name of [t.scientific, t.common, t.genus]) {
      if (!name) continue;
      const slug = encodeURIComponent(name.trim().replace(/ /g, "_"));
      const resp = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${slug}`);
      if (!resp.ok) continue;
      const data = await resp.json();
      if (data.thumbnail && data.thumbnail.source) { d = data; break; }
    }
    if (d) {
      const page = ((d.content_urls || {}).desktop || {}).page;
      slot.innerHTML =
        `<img class="species-photo" src="${d.thumbnail.source}" alt="${d.title}" loading="lazy" />` +
        `<div class="photo-credit"><strong>${d.title}</strong> — species reference` +
        (page ? `<br><a href="${page}" target="_blank" rel="noopener">Wikipedia (CC BY-SA)</a>` : "") +
        `</div>`;
    } else {
      slot.innerHTML = `<div class="photo-placeholder">No photo found.</div>`;
    }
  } catch (e) {
    slot.innerHTML = `<div class="photo-placeholder">Photo unavailable.</div>`;
  }
}

$("detail-close").onclick = () => $("detail").classList.add("hidden");

// ---- city selector ---------------------------------------------------------------
async function loadCities() {
  try {
    await loadManifest();
    const sel = $("city");
    for (const c of cityManifest) {
      const opt = document.createElement("option");
      opt.value = JSON.stringify(c.center);
      opt.textContent = `${c.city} (${c.count})`;
      sel.appendChild(opt);
    }
  } catch (e) { /* selector stays empty; map still works */ }
}
$("city").onchange = (e) => {
  if (!e.target.value) return;
  const center = JSON.parse(e.target.value);
  searchPoint = center;
  if (searchMarker) searchMarker.remove();
  searchMarker = new maplibregl.Marker({ color: "#4ea36b" }).setLngLat(center).addTo(map);
  map.flyTo({ center, zoom: 15 });
  drawRadius();
  map.once("moveend", search);
};
loadCities();

// ---- controls ---------------------------------------------------------------------
$("search-here").onclick = search;
$("radius").oninput = drawRadius;
for (const id of ["conf-high", "conf-med", "conf-low"]) $(id).onchange = search;

// ---- terms & waiver pop-up ---------------------------------------------------------
if (!localStorage.getItem("treesWaiverAccepted")) {
  $("waiver-modal").classList.remove("hidden");
}
$("waiver-check").onchange = (e) => ($("waiver-accept").disabled = !e.target.checked);
$("waiver-accept").onclick = () => {
  localStorage.setItem("treesWaiverAccepted", new Date().toISOString());
  $("waiver-modal").classList.add("hidden");
};

// polygon toggle button injected into the map
const polyBtn = document.createElement("button");
polyBtn.textContent = "▱ polygon";
polyBtn.style.cssText = "position:absolute;top:10px;right:10px;width:auto;z-index:4;";
polyBtn.onclick = () => {
  polygonMode = !polygonMode;
  polyBtn.textContent = polygonMode ? "▱ drawing… (dbl-click to finish)" : "▱ polygon";
  if (polygonMode) { polygon = []; drawPolygon(); }
};
document.body.appendChild(polyBtn);
map.on("dblclick", (e) => {
  if (polygonMode) {
    e.preventDefault();
    polygonMode = false;
    polyBtn.textContent = "▱ polygon";
  }
});

/* ---- photo analyzer: assisted single-photo geometry -----------------------------
 * Same pinhole model as tierC/geometry.py (metric_width / heights_from_rows):
 * meters-per-pixel = distance / focal-length-px, focal from the horizontal FOV.
 * The user supplies what the heavy CV models would otherwise detect — the four
 * tap points. Estimates carry error bands; nothing here is a load rating.
 */
const PH_STEPS = [
  "1 of 4 — tap the trunk base, right where it meets the ground 🌱",
  "2 of 4 — tap the LEFT edge of the trunk at about chest height",
  "3 of 4 — tap the RIGHT edge of the trunk at the same height",
  "4 of 4 — tap the lowest branch you'd climb (where it joins the trunk) 🌿",
];
const PH_COLORS = ["#e2574c", "#3e8ef7", "#3e8ef7", "#2e9e5b"];
const ph = { canvas: $("ph-canvas"), ctx: null, img: null, clicks: [] };

$("ph-file").onchange = (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const img = new Image();
  img.onload = () => {
    ph.img = img;
    ph.clicks = [];
    // cap canvas resolution; CSS scales it to panel width
    const w = Math.min(img.naturalWidth, 1400);
    ph.canvas.width = w;
    ph.canvas.height = Math.round(img.naturalHeight * (w / img.naturalWidth));
    ph.ctx = ph.canvas.getContext("2d");
    ph.canvas.style.display = "block";
    $("ph-reset").style.display = "block";
    $("ph-result").innerHTML = "";
    phDraw();
    $("ph-steps").textContent = PH_STEPS[0];
    URL.revokeObjectURL(img.src);
  };
  img.src = URL.createObjectURL(file);
};

function phDraw() {
  ph.ctx.drawImage(ph.img, 0, 0, ph.canvas.width, ph.canvas.height);
  ph.clicks.forEach(([x, y], i) => {
    ph.ctx.beginPath();
    ph.ctx.arc(x, y, 7, 0, 2 * Math.PI);
    ph.ctx.fillStyle = PH_COLORS[i];
    ph.ctx.fill();
    ph.ctx.lineWidth = 3;
    ph.ctx.strokeStyle = "#fff";
    ph.ctx.stroke();
  });
  if (ph.clicks.length >= 3) {   // breast-height width line
    const [l, r] = [ph.clicks[1], ph.clicks[2]];
    ph.ctx.beginPath(); ph.ctx.moveTo(l[0], l[1]); ph.ctx.lineTo(r[0], r[1]);
    ph.ctx.strokeStyle = "#3e8ef7"; ph.ctx.lineWidth = 2.5; ph.ctx.stroke();
  }
  if (ph.clicks.length === 4) {  // base -> branch height line
    const [b, br] = [ph.clicks[0], ph.clicks[3]];
    ph.ctx.beginPath(); ph.ctx.moveTo(b[0], b[1]); ph.ctx.lineTo(b[0], br[1]);
    ph.ctx.strokeStyle = "#2e9e5b"; ph.ctx.lineWidth = 2.5; ph.ctx.stroke();
  }
}

ph.canvas.onclick = (e) => {
  if (!ph.img || ph.clicks.length >= 4) return;
  const rect = ph.canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (ph.canvas.width / rect.width);
  const y = (e.clientY - rect.top) * (ph.canvas.height / rect.height);
  ph.clicks.push([x, y]);
  phDraw();
  if (ph.clicks.length < 4) {
    $("ph-steps").textContent = PH_STEPS[ph.clicks.length];
  } else {
    $("ph-steps").textContent = "Done! Here's your tree:";
    phAnalyze();
  }
};

$("ph-reset").onclick = () => {
  ph.clicks = [];
  $("ph-result").innerHTML = "";
  if (ph.img) { phDraw(); $("ph-steps").textContent = PH_STEPS[0]; }
};

function phAnalyze() {
  const dist = parseFloat($("ph-dist").value);
  const fovDeg = parseFloat($("ph-fov").value) || 66;
  if (!(dist > 0)) {
    $("ph-result").innerHTML = `<div class="guess-note">Enter your distance to the trunk first, then Start over.</div>`;
    return;
  }
  // focal length in px of the (possibly downscaled) canvas image
  const fPx = (ph.canvas.width / 2) / Math.tan(((fovDeg * Math.PI) / 180) / 2);
  const mPerPx = dist / fPx;

  const [base, left, right, branch] = ph.clicks;
  const dbhCm = Math.abs(right[0] - left[0]) * mPerPx * 100;
  const branchM = Math.max(0, (base[1] - branch[1]) * mPerPx);
  const dbhBand = dbhCm * 0.15, branchBand = branchM * 0.20;

  // mount check against YOUR body (same rule as score/reach.py)
  const h = parseFloat($("h").value) || 1.75;
  const alpha = parseFloat($("alpha").value) || 1.22;
  const mountCeiling = alpha * h + 0.30;
  const canMount = branchM <= mountCeiling;

  const rows = [
    `Trunk ≈ <strong>${dbhCm.toFixed(0)} cm</strong> across (±${dbhBand.toFixed(0)})` +
      (currentTree && currentTree.dbh_cm
        ? ` — inventory says ${Math.round(currentTree.dbh_cm)} cm`
        : ""),
    `First branch ≈ <strong>${branchM.toFixed(1)} m</strong> up (±${branchBand.toFixed(1)})`,
    canMount
      ? `Within your reach (~${mountCeiling.toFixed(1)} m incl. a small pull-up) — you could mount this tree 🎉`
      : `Above your reach (~${mountCeiling.toFixed(1)} m incl. a small pull-up) — you couldn't mount without aid`,
  ];
  $("ph-result").innerHTML =
    `<ul class="facts">${rows.map((r) => `<li>${r}</li>`).join("")}</ul>` +
    `<div class="hint">Single-photo estimate: assumes a level camera, a roughly
     vertical trunk, and your distance guess. Branch <em>thickness</em> is not
     measurable from taps — this is a reach check, never a load rating.</div>`;
}
