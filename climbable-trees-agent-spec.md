# Climbable-Trees Mapping — Coding Agent Specification

**Status:** implementation spec, v1. Grounded in verified primary sources (repos + papers) as of 2026-07. Where a claim is unverified or a design choice is a judgment call, it is marked **[UNVERIFIED]** or **[DECISION]**.

**One-line scope:** given a location and a user's body dimensions, return a *ranked, confidence-tagged* list of nearby trees that are plausibly climbable via a reachable ladder of sufficiently-thick branches. The system **filters and ranks; it never certifies safety.** A waiver covers residual risk. This is a hard product constraint, not a disclaimer — it determines which algorithms are fit for purpose (we never need per-branch load certification, only a plausibility prior).

---

## 0. Design invariants (do not violate)

1. **No certification.** Output is always a ranked candidate list with explicit confidence, never a binary safe/unsafe. Every branch-level number is an estimate with an error band.
2. **Evidence tiers are explicit and separable.** Every tree carries a `confidence` and a `provenance` object naming which tiers contributed. The UI must surface this; do not present uniform-looking coverage over non-uniform evidence.
3. **Public/eligible trees only.** Prefer government-managed street/park trees (already the bias of the inventory data). Gate out private parcels. This is both a legal and a data-quality feature.
4. **Cheapest reliable signal first.** Species → wood/form prior and trunk DBH come free with inventory records and anchor the score. Street-level CV only *refines* and *raises confidence* where it exists; it is never a prerequisite.
5. **Licensing is load-bearing.** Mapillary imagery is CC-BY-SA 4.0: derived measurements are fine, but any displayed thumbnail requires the Mapillary logo + link attribution, and redistribution of the imagery itself carries share-alike. Do not build features that redistribute raw imagery without attribution.

---

## 1. Architecture overview

```
                        ┌─────────────────────────────────────────┐
                        │  OFFLINE BATCH (ingestion + scoring)      │
                        └─────────────────────────────────────────┘
 [Tier A source]  OpenTrees + live city open-data portals
        │              (ArcGIS Hub / Socrata / CKAN)
        ▼
   normalize ──► trees(location, species, dbh, height, health, public_flag, source, captured_at)
        │
        ├─[Tier B]  aerial crown detection (DeepForest / Detectree2) for cities w/o inventory
        │             + parcel/land-use reconciliation (public vs private, hazard gate)
        │
        ├─[Tier C]  street-level geometry from Mapillary sequences
        │             (trunk seg + metric depth → DBH cross-check + COARSE lowest-branch height)
        │
        └─[Premium] crowdsourced phone-LiDAR → QSM (per-tree, opt-in "verified")
        │
        ▼
   climbability feature extraction  ─►  confidence-weighted score  ─►  reach-match filter
        │
        ▼
   PostGIS (scored trees, H3-bucketed) 
                        ┌─────────────────────────────────────────┐
                        │  ONLINE (serving)                         │
                        └─────────────────────────────────────────┘
   API (viewport / radius query, user body params) ─► MapLibre GL JS frontend
        (per-tree detail: species, why-scored, confidence badge, Mapillary photo+attribution, waiver, report control)
```

Build order (Section 9) ships Tier A as a complete product first. B and C are coverage/confidence add-ons.

---

## 2. Data layer (Tier A source of truth)

### 2.1 Verified facts about the backbone
- **OpenTrees** (`github.com/stevage/opentrees-data`, MIT) is a Node pipeline that harvests ~228 municipal sources across ~20 countries (USA ~67, Canada ~37, Australia ~31, France ~25, Netherlands ~23, Germany ~19, others). It normalizes each source via a per-source `crosswalk` and emits vector tiles. The headline aggregate (~15M trees) is **stale (~2020)**; treat OpenTrees as a *source registry + crosswalk library*, and re-pull from live portals.
- **Field availability across sources (counted from the repo's crosswalks):** `common` ~160, `scientific` ~152, `dbh` ~115, `height` (total tree height) ~93, `health` ~68, `crown` (width) ~35, `maturity` ~25, `family` ~13. **There is no lowest-branch-height field in any source.** Confirmed: the branch-ladder signal must be recovered externally (Tier C / Premium), never read from inventory.
- Most sources cover only government-managed public trees, not private property — this pre-filters toward legally climbable trees.

### 2.2 Ingestion module — `ingest/`
Reuse OpenTrees's source list and crosswalks rather than rebuilding them. Two paths:

- **Path 1 (fast start):** port the OpenTrees `sources/*.js` crosswalk definitions into a declarative config (`sources.yaml`), then implement a Python fetcher that reads each `download` URL (ArcGIS Hub `.zip`/GeoJSON, Socrata CSV, CKAN) and applies the crosswalk. Most US sources are ArcGIS Hub endpoints of the form `https://opendata.arcgis.com/datasets/{id}.geojson` or Socrata (`data.cityofnewyork.us/.../rows.csv`). Keep the unit conversions from the crosswalks (inches→cm for DBH: ×2.54; feet→m for height: ÷3.28084).
- **Path 2 (currency):** for target cities, query the live portal directly (ArcGIS Feature Service `/query?where=1=1&outFields=*&f=geojson`, paginated) so `captured_at` is fresh.

**Normalized schema (`trees` table):**
```
tree_id            uuid (pk)
geom               geometry(Point, 4326)          -- WGS84 lon/lat
source_id          text                            -- e.g. 'nyc', 'pdx-street'
source_ref         text                            -- native id for dedup/update
scientific         text
genus              text
species            text
common             text
dbh_cm             real        -- nullable (~half of sources)
height_m           real        -- total tree height, nullable (~40%)
crown_m            real        -- crown width, nullable
health             text        -- free-text condition, needs per-source mapping
maturity           text
public_flag        boolean     -- from source semantics + parcel reconciliation
captured_at        date
provenance         jsonb       -- {tiers:[...], source_url, license}
ingested_at        timestamptz
```
Dedup across overlapping sources (e.g. a city's street + park layers) on `(source_id, source_ref)` first, then spatial dedup within ~1 m for cross-source overlaps. Preserve the OpenTrees `cleanTree` normalization logic (genus/species splitting, "vacant/removed/stump" pruning, unknown-species nulling) — port it faithfully; it encodes a lot of messy-real-world handling.

---

## 3. Tier A climbability features (the v1 core, zero novel ML)

Two features, computed from inventory fields alone, anchor the whole score.

### 3.1 Species → wood/form prior — `features/species_prior.py`
Build a lookup keyed by genus (fall back to family) → `{wood_strength ∈ [0,1], scaffold_form ∈ [0,1], shed_risk ∈ [0,1]}`.
- **wood_strength:** green-wood modulus of rupture / density prior. Strong: *Quercus* (oak), *Platanus* (plane/sycamore), *Fagus* (beech), *Carpinus*. Brittle/weak: *Salix* (willow), *Populus* (poplar/cottonwood), *Acer saccharinum* (silver maple), *Ailanthus*, *Betula* to a degree.
- **scaffold_form:** does the species typically produce low, near-horizontal, well-spaced scaffold limbs (good) vs. a single clear bole with high canopy (bad for a ladder)? Excurrent conifers and high-pruned street trees score low here even when strong.
- **shed_risk:** self-pruning / limb-drop tendency (poplar, silver maple, some eucalypts).

**[DECISION]** Source these priors from a small curated table (order 100–300 genera covers the vast majority of street-tree records). Do **not** fabricate species-level MOR numbers; use qualitative tiers (strong/medium/brittle) mapped to coarse scores, and cite the Wood Handbook (USDA FPL) / wood-density databases as the reference basis. Flag any genus not in the table as `wood_strength = null` → lowers confidence, doesn't zero the score.

### 3.2 Trunk size — `features/dbh_feature.py`
DBH is the second pillar and the proxy for "reasonably thick enough." Map `dbh_cm` to a monotone size score with a floor (saplings excluded) and saturation (beyond ~60 cm adds little). Where DBH is null but total `height_m` exists, use a genus-specific height→DBH allometric fallback and mark it estimated.

**Important honesty note:** DBH is trunk diameter at breast height (1.3 m). It does **not** tell you branch diameters or the height of the first branch. It is a plausibility prior for structural robustness, correlated with but not equal to climbability. Keep that distinction in variable names and docs.

---

## 4. Tier B — aerial detection (coverage extension + eligibility gate)

**Purpose is narrow:** (a) find trees where no inventory exists; (b) judge isolation/hazard context (proximity to power lines, roads, water); (c) reconcile public vs private. **It does not produce any climbability signal** — aerial detectors see the canopy from above and recover neither trunk nor branch structure. This is verified across every detector below.

### 4.1 Detectors (verified)
- **DeepForest** (`weecology/DeepForest`, MIT; PyPI `deepforest`). torchvision RetinaNet, single-class tree-crown **bounding boxes** from RGB airborne imagery. Ships a pretrained model. Easiest to install; use as the default/fallback.
- **Detectree2** (`PatBall1/detectree2`, MIT; PyPI `detectree2`). Detectron2 **Mask R-CNN**, **polygon** crown delineation, pretrained `model_garden`. Modestly beats DeepForest in independent transfer tests: **F1 ≈ 0.57 vs 0.52** (Gan et al. 2023, *Remote Sensing* 15(3):778, temperate deciduous, UAV RGB). **Install caveat:** requires Detectron2, which is sensitive to the PyTorch/CUDA combo and is not actively maintained against the newest torch — pin versions and build in a dedicated env. Prefer their HF Space / provided weights to avoid training.
- **[DECISION]** Skip newer options (YOLOv11 urban, SAM2-prompted, SelvaBox/OAM-TCD) for v2 unless a target city's imagery defeats the above; they add integration cost for marginal gain on the *eligibility* task, which tolerates modest recall.

### 4.2 Reconciliation — `tierB/parcels.py`
Intersect detected/inventoried points with OSM `landuse`/`leisure=park` and, where available, county parcel polygons. Set `public_flag`. Compute hazard proximities (distance to OSM `power=line`/`tower`, `highway`, `waterway`). These become eligibility gates and score penalties, **not** climbability features.

Inputs: open aerial imagery (NAIP in the US at ~0.6 m/px; national orthophoto services elsewhere). Tiling large orthophotos (windowing + stitching + NMS across tile seams) is the real engineering cost here and is CPU/IO-bound, not GPU-bound.

---

## 5. Tier C — street-level geometry (the hard, valuable part)

This is where the branch-ladder signal *might* be recovered at scale. Be clear-eyed: **trunk DBH-from-photo is an established sub-area; per-branch height and diameter from opportunistic street imagery is barely in the literature.** Treat Tier C branch outputs as coarse and lower-confidence by construction.

### 5.1 Imagery source — Mapillary API v4 — `tierC/mapillary.py`
Verified endpoints and constraints:
- **Auth:** OAuth2; register an app for an access token (`MLY|...`). Token as query param for tiles, as `Authorization: OAuth` header for the Graph API.
- **Coverage / spatial query (use this at scale):** vector tiles `https://tiles.mapillary.com/maps/vtp/mly1_public/2/{z}/{x}/{y}?access_token=…`, max zoom 14. Layers include `image` and `sequence`; recent fields include `quality_score` (added 2026-05) and `is_pano`. Also `mly1_computed_public` for map-matched (CV-corrected) geometries — prefer computed geometry for positioning.
- **Per-image metadata (Graph API):** `https://graph.mapillary.com/{image_id}?fields=…`. Request `thumb_2048_url` (image), `geometry`/`computed_geometry`, `compass_angle`/`computed_compass_angle`, `camera_type`, `camera_parameters`, `captured_at`, `sequence`, `is_pano`, `quality_score`, and (2026-06) `on_foot`. Nearest-image-to-point requires fetching the overlapping tile then filtering by radius client-side (no server-side spatial query on the Graph API).
- **License [CONSTRAINT]:** CC-BY-SA 4.0. Extracted *measurements* (facts) are usable; any displayed thumbnail needs Mapillary logo + link + contributor attribution. Do not redistribute raw imagery in bulk.
- **Panorama gotcha [CONSTRAINT]:** a large share of frames are 360° equirectangular (`is_pano=true`). Pinhole triangulation is invalid on these; either reproject a perspective crop toward the tree's bearing first, or restrict Tier C v1 to `is_pano=false` frames.

### 5.2 Geometry pipeline — `tierC/geometry.py`
Two candidate methods; **[DECISION]** implement (A) first, keep (B) as the higher-fidelity path.

**(A) Single-frame metric monocular.** For each frame near a tree:
1. Segment the trunk (and, ambitiously, visible primary branches). Use a trunk/tree instance segmenter; for trunks a fine-tuned SegFormer or YOLO-seg works. **[UNVERIFIED]** The literature reports street-level DBH errors in the low single-digit percent, but those come from *controlled capture* (deliberate image pairs at known distance with a reference object). Do not carry any specific published accuracy number into this system as an expected value; measure on your own Mapillary data.
2. Metric depth. Use **UniDepthV2** (`lpiccinelli-eth/UniDepth`) — predicts metric depth *and* camera intrinsics jointly, so it works on heterogeneous frames with missing/unreliable EXIF. Alternative: **Metric3Dv2** (needs coarse intrinsics from `camera_parameters`), or **Depth Pro**. All are ViT-based; ViT-L fits comfortably in ≤12 GB, Metric3Dv2-giant wants ~24 GB.
3. Back-project the trunk mask to metric 3D using predicted depth + intrinsics; fit a vertical cylinder to get DBH at 1.3 m; estimate lowest-branch height as the height of the first mask discontinuity / first detected branch junction above the trunk.

**(B) Feed-forward multiview over the sequence (higher fidelity).** Mapillary frames come in *sequences* — consecutive views of the same trees. Feed a short window of frames to a feed-forward geometry model (**VGGT**, or the newer **MapAnything** lineage) to get a metric point cloud without per-scene SfM optimization, then fit trunk/branch geometry on the cloud. This is close to a published template: **UrbanVGGT** (arXiv 2603.22531, 2026) does scalable *sidewalk-width* estimation from street view via exactly this recipe. Multiview resolves scale and occlusion far better than single-frame monocular and is the right long-term Tier C. **This is the one place GPU memory matters** (memory grows with frame count); a 24–48 GB card is comfortable.

### 5.3 Output contract
`tierC` emits per tree, when imagery exists:
```
dbh_cm_streetcv        real   + error_band
lowest_branch_h_m      real   + error_band   -- COARSE, low confidence
branch_ladder          [{height_m, est_diameter_cm, confidence}]  -- often sparse/empty
tierC_confidence       real
```
`lowest_branch_h_m` and `branch_ladder` are the least-supported outputs in the entire system. Ship them behind a confidence gate and validate before trusting.

---

## 6. Premium "verified" tier — phone-LiDAR → QSM

For individual trees a user actually scouts, not a scalable default. This is the only path that directly measures branch geometry.

### 6.1 Verified facts about QSM
- **Quantitative Structure Models** (TreeQSM `InverseTampere/TreeQSM`, MATLAB; AdQSM; Treegraph; PyTLidar) fit cylinders to a **dense 3D point cloud** and read off branch diameters, branching points, and DBH directly.
- **Accuracy regime (verified):** TreeQSM reconstructs ~95% of branches **≥30 cm in *diameter*** (Raumonen et al. lineage; e.g. 279-branch validation samples), with DBH RMSE ~1.3–1.5 cm vs. tape. **Critical caveat:** 30 cm *diameter* is a major structural limb. Accuracy degrades for thinner branches — and climbable footholds are typically ~10–25 cm diameter, i.e. the regime where QSM is *least* reliable. So even the premium tier does not cleanly deliver the full climbing ladder; it reliably delivers the big scaffold limbs and DBH.
- **Input requirement:** dense point clouds, primarily TLS/MLS. Photogrammetry/NeRF clouds work only at sufficient density. **[UNVERIFIED]** Modern iPhone Pro LiDAR clouds feeding AdQSM/Treegraph are plausible for single scouted trees, but iPhone LiDAR is sparse and short-range relative to survey TLS — validate diameter accuracy against tape before promising numbers.

### 6.2 Module — `premium/qsm.py`
Accept an uploaded point cloud (`.ply`/`.las`), run wood-leaf separation if needed, run a QSM backend, return the reconstructed cylinder model + a machine-readable branch ladder with diameters and heights. QSM is **CPU-bound** — no GPU needed; TreeQSM needs MATLAB/Octave or use a Python reimplementation (pyTLidar / Treegraph) to stay in one stack.

---

## 7. Scoring + reach-match

### 7.1 Confidence-weighted climbability score — `score/climbability.py`
Combine features with weights that shift by evidence availability:

$$ S \;=\; w_{sp}\, f_{\text{species}} \;+\; w_{db}\, f_{\text{dbh}} \;+\; w_{c}\, f_{\text{streetcv}} $$

with $w_{sp}, w_{db}$ dominating when only Tier A exists, and $w_c$ activating (and raising overall `confidence`) only where Tier C succeeded. Tier B contributes **eligibility gates and penalties** (private parcel → excluded; power-line proximity → penalty), not positive score. Keep the functional form simple and interpretable — a transparent weighted sum with a written "why scored" trace beats a black box for a product that explicitly refuses to certify. Reserve learn-to-rank (Section 8) for re-weighting once you have report/label data.

### 7.2 Reach-match filter — `score/reach.py`
This applies the sequential-branch-ladder requirement, parameterized by the user's body.

**Model.** Let the user have height $h$ and reach parameters:
- ground standing reach $R_0 \approx \alpha\, h$ with $\alpha \approx 1.2$–$1.25$ **[UNVERIFIED anthropometric constant — expose as a tunable, don't hardcode as truth]**, optionally plus a jump/pull margin $m$.
- comfortable inter-branch vertical step $\Delta$ (default ~0.5–0.7 m, user-tunable).
- minimum load-bearing branch diameter $d_{\min}$ (default ~10 cm **[DECISION]**, raised by user weight).

Given a tree's ordered branch heights $b_1 < b_2 < \dots$ with estimated diameters $d_i$, keep only load-bearing branches $\mathcal{B} = \{b_i : d_i \ge d_{\min}\}$. The tree is climbable to height $H$ iff:
1. **Mount:** $\min \mathcal{B} \le R_0 + m$ (a sturdy branch is reachable from the ground), and
2. **Ladder:** walking up $\mathcal{B}$ in order, every consecutive gap $b_{i+1} - b_i \le \Delta + \text{(reach from a standing position on } b_i)$.

$H$ is the highest branch reachable before the ladder breaks. Output $H$ and the retained ladder, both confidence-tagged.

**Load side (filter, not certificate).** A cantilevered branch's bending capacity scales like its section modulus $\sim \pi d^3/32$ times a species-dependent green-wood strength. Use this only to set/scale $d_{\min}$ as a plausibility filter — **never** emit a load rating. The species prior (Section 3.1) and $d_{\min}$ together answer "plausibly thick enough"; the waiver covers the rest.

**Degradation.** When Tier C branch data is absent (the common case), reach-match cannot run on real branch heights. Fall back to a **species-form + DBH plausibility score** ("this species at this trunk size *typically* offers a low reachable scaffold") and mark it clearly as a form-based guess, not a measured ladder. Do not silently emit a fake ladder.

---

## 8. Serving + frontend

- **Store:** PostGIS. Precompute scores; index with GiST on `geom` and/or bucket by **H3** cell for cheap viewport aggregation. Store per-tree `why_scored` trace and `confidence`.
- **API:** viewport/radius query taking user body params `(h, weight, Δ, d_min)`; reach-match can run server-side per query (cheap) so users get personalized $H$ without recompute of features.
- **Frontend:** MapLibre GL JS. Radius/polygon selection, body-param inputs, per-tree detail panel (species, why-scored trace, confidence badge, Mapillary photo **with required attribution**, waiver acceptance, report control). The report control feeds (a) a takedown/correction queue and (b) learn-to-rank labels for later re-weighting of Section 7.1.
- **Confidence must be visible.** Coverage is doubly gated — by which cities publish inventories (Tier A) and where Mapillary has ground views (Tier C) — and deep-park trees a climber most wants are exactly where both are thinnest. Render confidence honestly (badges, opacity, or explicit "form-based guess" labels); never imply uniform coverage.

---

## 9. Build order / milestones

- **v1 — Tier A only (ship this as a real product).** OpenTrees/live-portal ingestion → species prior + DBH → form-based reach-match → PostGIS → MapLibre. Works for any inventoried city with **zero novel ML and zero legal risk**. Species + DBH already satisfy "reasonably thick enough."
- **v2 — Tier B.** Aerial detection (DeepForest default, Detectree2 where worth the Detectron2 setup) + parcel/hazard reconciliation to extend coverage to un-inventoried areas and harden the public/hazard gates.
- **v3 — Tier C.** Mapillary sequence ingestion → method (A) metric monocular first, then (B) feed-forward multiview. DBH cross-check is the reliable win; treat branch-ladder outputs as coarse and validate against a hand-labeled set before surfacing them un-hedged.
- **Premium — verified tier.** Opt-in phone-LiDAR upload → QSM for individual scouted trees. Reliable for major limbs + DBH; validate iPhone-LiDAR diameter accuracy before promising numbers.

---

## 10. Compute / GPU

Nothing in v1–v2 needs a serious GPU; ingestion and reconciliation are CPU/IO-bound. Only Tier C touches GPU meaningfully:
- Aerial detectors: inference is light (≤8 GB); bottleneck is orthophoto tiling.
- Monocular metric depth (UniDepthV2 / Metric3Dv2 / Depth Pro): ViT-L ≤12 GB; giant variants ~24 GB.
- Feed-forward multiview (VGGT / MapAnything): memory grows with frame count — the one place 24–48 GB helps.
- QSM: CPU-only.

A single mid-range GPU (or the L40S, which is overkill) covers the whole pipeline; batch Tier C offline.

---

## 11. Honest residual gaps (put these in the README, not buried)

1. **The branch-ladder is the least-supported piece of the whole system.** Trunk DBH-from-photo is studied; per-branch height/diameter from opportunistic street imagery is largely unproven. Expect Tier C ladders to be coarse until you either collect LiDAR or build and validate a custom branch model. QSM only cleanly recovers ≥30 cm-diameter limbs, coarser than the footholds a climber needs.
2. **Published monocular accuracies come from controlled capture** and will not transfer to arbitrary-distance, occluded, mixed-camera, sometimes-panoramic Mapillary frames unmeasured. Budget a hand-labeled validation set (DBH + lowest-branch height on N≥50–100 trees with tape/LiDAR ground truth) before trusting any Tier C number.
3. **Coverage is doubly gated and anti-correlated with demand** (deep-park trees are worst-covered). The product's honesty about confidence *is* the feature.
4. **Anthropometric and load constants are placeholders.** Standing-reach ratio, step spacing, and $d_{\min}$ are tunables to calibrate against real users, not physical truths.

---

## 12. Dependency table (verified repos / licenses)

| Component | Package / repo | License | Role | Notes |
|---|---|---|---|---|
| Inventory backbone | `stevage/opentrees-data` | MIT | source registry + crosswalks | port crosswalks + `cleanTree` logic; data is stale, re-pull live |
| Aerial bbox detector | `weecology/DeepForest` (PyPI `deepforest`) | MIT | Tier B default | torchvision RetinaNet, pretrained |
| Aerial polygon detector | `PatBall1/detectree2` (PyPI `detectree2`) | MIT | Tier B (better F1) | needs Detectron2 — pin torch/CUDA |
| Metric depth | `lpiccinelli-eth/UniDepth` (UniDepthV2) | check repo | Tier C (A) | predicts depth **and** intrinsics; best for no-EXIF frames |
| Metric depth alt | Metric3Dv2 (arXiv 2404.15506) / Depth Pro | check repo | Tier C (A) | needs coarse intrinsics |
| Feed-forward MVS | VGGT / MapAnything | check repo | Tier C (B) | multiview over Mapillary sequences; GPU-mem heavy |
| Street imagery | Mapillary API v4 | imagery CC-BY-SA 4.0 | Tier C source | attribution mandatory; handle `is_pano` |
| QSM | `InverseTampere/TreeQSM` (MATLAB) / AdQSM / Treegraph / pyTLidar | check each | Premium | CPU-bound; needs dense clouds |
| DB / index | PostGIS + H3 | open | store/serve | GiST + H3 bucketing |
| Map | MapLibre GL JS | BSD | frontend | radius/polygon + attribution |

**[ACTION for the agent]** Verify the exact license and current install instructions of UniDepth, Metric3Dv2, VGGT/MapAnything, and the QSM backends from their repos at build time — several are research code with non-permissive or ambiguous licenses, which matters for a commercial product.
