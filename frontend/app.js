/* Climbable-Trees — candidate finder frontend.
 *
 * MapLibre GL JS. Radius + polygon selection, body-param inputs, per-tree
 * detail panel with confidence badge, why-scored trace, Mapillary attribution
 * slot, waiver, and a report control feeding the correction/label queue.
 *
 * Confidence is rendered honestly: circle color = score, circle opacity =
 * confidence, and the detail panel labels the reach-match a "form-based guess".
 */

const API = ""; // same origin

const map = new maplibregl.Map({
  container: "map",
  // OpenFreeMap: real street/building basemap, free, no API key (self-host for
  // production traffic — https://openfreemap.org). Replaces the detail-less
  // MapLibre demo style that rendered as a flat green landmass when zoomed in.
  style: "https://tiles.openfreemap.org/styles/liberty",
  center: [-122.4194, 37.7749], // San Francisco (dense real data on load)
  zoom: 15,
});
map.addControl(new maplibregl.NavigationControl(), "top-left");

let searchPoint = null;      // [lon, lat]
let searchMarker = null;
let polygon = [];            // array of [lon,lat] while drawing
let polygonMode = false;

const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function setStatus(msg) { statusEl.textContent = msg || ""; }

// ---- confidence -> badge tier -------------------------------------------------
function confTier(c) {
  if (c >= 0.55) return "high";
  if (c >= 0.3) return "med";
  return "low";
}

// ---- map layers ---------------------------------------------------------------
map.on("load", () => {
  map.addSource("trees", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "trees",
    type: "circle",
    source: "trees",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 4, 18, 9],
      // color by score (low=amber, high=green)
      "circle-color": [
        "interpolate", ["linear"], ["coalesce", ["get", "score"], 0],
        0, "#b0563b", 0.4, "#c9922e", 0.7, "#2e9e5b",
      ],
      // opacity by confidence — never imply uniform coverage
      "circle-opacity": ["max", 0.25, ["coalesce", ["get", "confidence"], 0.25]],
      "circle-stroke-color": "#0c0f13",
      "circle-stroke-width": 1,
    },
  });

  map.addSource("radius", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "radius",
    type: "fill",
    source: "radius",
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
  map.on("click", "trees", onTreeClick);
  map.on("mouseenter", "trees", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "trees", () => (map.getCanvas().style.cursor = ""));

  // Auto-run a search at the initial map center so candidate trees are visible
  // immediately (otherwise the map loads empty until the user clicks).
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

// ---- search -------------------------------------------------------------------
async function search() {
  if (!searchPoint) {
    const c = map.getCenter();
    searchPoint = [c.lng, c.lat];
  }
  const params = new URLSearchParams({
    lon: searchPoint[0], lat: searchPoint[1],
    radius_m: $("radius").value || 500,
    h: $("h").value, weight: $("weight").value,
    delta: $("delta").value, d_min: $("d_min").value, alpha: $("alpha").value,
    public_only: $("public_only").checked,
    min_score: $("min_score").value,
  });
  setStatus("Searching…");
  try {
    const resp = await fetch(`${API}/api/trees?${params}`);
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    const data = await resp.json();
    let feats = data.trees.map((t) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [t.lon, t.lat] },
      properties: { ...t, _raw: JSON.stringify(t) },
    }));
    if (polygon.length >= 3) {
      feats = feats.filter((f) => pointInPolygon(f.geometry.coordinates, polygon));
    }
    map.getSource("trees").setData({ type: "FeatureCollection", features: feats });
    setStatus(`${feats.length} candidate tree(s). ${data.disclaimer}`);
  } catch (err) {
    setStatus(`Search failed: ${err.message}. Is the API + DB running and ingested?`);
  }
}

// ---- detail panel -------------------------------------------------------------
function onTreeClick(e) {
  const props = e.features[0].properties;
  const t = JSON.parse(props._raw);
  showDetail(t);
}

function showDetail(t) {
  $("detail").classList.remove("hidden");
  $("d-common").textContent = t.common || t.genus || "Unknown tree";
  $("d-sci").textContent = t.scientific || "";

  const rm = t.reach_match || {};

  // short facts — the at-a-glance summary (max 5)
  const tier = confTier(t.confidence || 0);
  const facts = [
    `Score <strong>${(t.score ?? 0).toFixed(2)}</strong> · ${tier} confidence`,
  ];
  if (t.height_m != null) facts.push(`Height ~<strong>${Math.round(t.height_m)} m</strong>`);
  if (t.dbh_cm != null) facts.push(`Trunk <strong>${Math.round(t.dbh_cm)} cm</strong> thick (DBH)`);
  if (rm.is_measured_ladder && (rm.ladder || []).length) {
    facts.push(`First branch at <strong>${rm.ladder[0].height_m} m</strong> (measured)`);
  } else if (rm.plausibility != null) {
    facts.push(`First branch not measured — low-branch likelihood <strong>${rm.plausibility.toFixed(2)}</strong>`);
  }
  if (searchPoint) {
    facts.push(`<strong>${fmtDistance(distanceM(searchPoint, [t.lon, t.lat]))}</strong> from your search point`);
  }
  $("d-facts").innerHTML = facts.slice(0, 5).map((f) => `<li>${f}</li>`).join("");

  // reach-match: a measured ladder when street geometry exists, else a guess
  let reachHtml = "";
  if (rm.is_measured_ladder) {
    reachHtml = `<div>Measured ladder to <strong>${rm.reachable_height_m} m</strong> (${rm.ladder.length} branches).</div>`;
  } else {
    const p = rm.plausibility == null ? "—" : rm.plausibility.toFixed(2);
    reachHtml =
      `<span class="badge guess">form-based guess</span>` +
      `<div class="guess-note"><strong>Not a measured ladder.</strong> No measured
       branch geometry for this tree yet. Plausibility that this species at this
       trunk size offers a low, climbable scaffold: <strong>${p}</strong>.
       Effective d_min for your weight: ${rm.effective_d_min_cm} cm.</div>`;
  }
  if (!$("waiver").checked) {
    reachHtml += `<div class="hint">Accept the waiver to acknowledge residual risk.</div>`;
  }
  $("d-reach").innerHTML = reachHtml;

  // why-scored trace
  const why = t.why_scored || [];
  $("d-why").innerHTML = why.map((w) => {
    const v = w.value == null ? "null" : (typeof w.value === "number" ? w.value.toFixed(3) : w.value);
    return `<li><strong>${w.feature}</strong>: ${v}<br><span class="hint">${w.note || ""}</span></li>`;
  }).join("");

  // provenance
  const p = t.provenance || {};
  $("d-prov").innerHTML =
    `Signals: ${(p.signals || []).join(", ")}<br>` +
    `Source: ${p.source_id || "—"}<br>` +
    `License: ${p.license || "—"}<br>` +
    (p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener">source</a><br>` : "") +
    `<em>${p.disclaimer || ""}</em>`;

  $("d-report-send").onclick = () => submitReport(t);
  $("d-report-status").textContent = "";

  loadTreePhoto(t);
}

// ---- distance from search point ------------------------------------------------
function distanceM(a, b) {
  const R = 6371000, toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(b[1] - a[1]), dLon = toRad(b[0] - a[0]);
  const s = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
function fmtDistance(m) { return m < 950 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`; }

// ---- tree photo: real street-level photo of the spot, else species reference ---
async function loadTreePhoto(t) {
  const slot = $("d-photo");
  slot.innerHTML = `<div class="photo-placeholder">Loading photo…</div>`;
  // 1) Try a photo of the ACTUAL location (Mapillary, else Google Street View).
  try {
    const q = new URLSearchParams({ lat: t.lat, lon: t.lon });
    const info = await (await fetch(`${API}/api/tree_photo?${q}`)).json();
    if (info && info.available && info.provider === "mapillary") {
      // CC BY-SA: contributor + Mapillary logo/link must render with the image.
      slot.innerHTML =
        `<img class="species-photo" src="${info.image}" alt="street-level photo at this tree" loading="lazy" />` +
        `<div class="photo-credit">© ${info.creator || "contributor"} · ` +
        `<a href="${info.url}" target="_blank" rel="noopener"><span class="mly-logo" aria-label="Mapillary"></span> Mapillary</a>` +
        ` CC BY-SA${info.date ? ` · ${info.date}` : ""}</div>`;
      return;
    }
    if (info && info.available) {
      const iq = new URLSearchParams({ lat: t.lat, lon: t.lon });
      if (info.heading != null) iq.set("heading", info.heading);
      slot.innerHTML =
        `<img class="species-photo" src="${API}/api/tree_photo/image?${iq}" alt="street view of this tree" loading="lazy" />` +
        `<div class="photo-credit">Street view at this location` +
        (info.date ? ` (${info.date})` : "") +
        `<br>${info.attribution || ""}</div>`;
      return;
    }
  } catch (e) { /* fall through to species photo */ }
  // 2) Fall back to a species reference photo (Wikipedia).
  await loadSpeciesPhoto(t);
}

// ---- species reference photo (Wikipedia) --------------------------------------
async function loadSpeciesPhoto(t) {
  const slot = $("d-photo");
  try {
    const q = new URLSearchParams({
      scientific: t.scientific || "",
      common: t.common || "",
      genus: t.genus || "",
    });
    const resp = await fetch(`${API}/api/species_photo?${q}`);
    const d = await resp.json();
    if (d && d.image) {
      const title = (d.title || t.common || t.scientific || "species").replace(/"/g, "&quot;");
      const credit = d.source_url
        ? `<a href="${d.source_url}" target="_blank" rel="noopener">${d.credit}</a>`
        : (d.credit || "");
      slot.innerHTML =
        `<img class="species-photo" src="${d.image}" alt="${title}" loading="lazy" />` +
        `<div class="photo-credit"><strong>${title}</strong> — species reference photo` +
        `<br>${credit}</div>`;
    } else {
      slot.innerHTML = `<div class="photo-placeholder">No reference photo found for this species.</div>`;
    }
  } catch (e) {
    slot.innerHTML = `<div class="photo-placeholder">Photo unavailable.</div>`;
  }
}

$("detail-close").onclick = () => $("detail").classList.add("hidden");

async function submitReport(t) {
  const body = {
    tree_id: t.tree_id,
    kind: $("d-report-kind").value,
    payload: { note: $("d-report-note").value, tree: { genus: t.genus, species: t.species } },
  };
  try {
    const resp = await fetch(`${API}/api/reports`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await resp.json();
    $("d-report-status").textContent = resp.ok ? `Queued (${data.report_id}). Thanks.` : "Failed.";
  } catch (e) {
    $("d-report-status").textContent = "Failed: " + e.message;
  }
}

// ---- city selector ------------------------------------------------------------
async function loadCities() {
  try {
    const resp = await fetch(`${API}/api/cities`);
    const data = await resp.json();
    const sel = $("city");
    for (const c of data.cities) {
      const opt = document.createElement("option");
      opt.value = JSON.stringify(c.center);
      opt.textContent = c.city;
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

// ---- controls -----------------------------------------------------------------
$("search-here").onclick = search;
$("radius").oninput = drawRadius;
$("min_score").oninput = () => ($("min_score_val").textContent = $("min_score").value);

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
