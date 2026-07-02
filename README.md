# Climbable-Trees Mapping — v1 (Tier A)

Given a location and a user's body dimensions, return a **ranked,
confidence-tagged list of nearby trees** plausibly climbable via a reachable
ladder of sufficiently-thick branches.

> **This tool filters and ranks. It never certifies that a tree is safe to
> climb.** Every number carries an error band; a waiver covers residual risk.

This repository is the **v1 / Tier A** release: OpenTrees-style ingestion →
species prior + DBH size → **form-based** reach-match → PostGIS → MapLibre.
Zero novel ML, zero legal risk. **Tier B (aerial detection + eligibility/hazard
reconciliation) and Tier C (street-level geometry) are now implemented** (see
below); Premium (phone-LiDAR → QSM) remains **intentionally deferred** — a clean
module seam is left for it (see "Module seams" below).

---

## Tier B — aerial detection + eligibility/hazard reconciliation (`tierB/`)

Tier B's purpose is **narrow and explicitly NOT climbability** (spec §4): aerial
detectors see the canopy from above and recover neither trunk nor branch
structure. It contributes **eligibility gates and score penalties only**:

| Piece | Module | What it does |
|---|---|---|
| Crown detection | `tierB/detect.py` | Finds trees where **no inventory exists**. `DeepForest` backend (torchvision RetinaNet, MIT) is lazily imported behind the optional `requirements-tierb.txt` extra; a dependency-free `GridStubDetector` drives tests/demos. |
| Orthophoto tiling | `tierB/tiling.py` | Windowing + **cross-seam NMS** + stitching — the real CPU/IO cost (spec §4.2). Pure, no imagery/torch needed. |
| Georeferencing | `tierB/detect.py` | Rasterio-order affine geotransform maps detection pixels → lon/lat crowns. |
| Reconciliation | `tierB/parcels.py` | OSM land-use containment → `public_flag` gate (**private parcel ⇒ excluded**, invariant #3); hazard proximity to `power=line` / `highway` / `waterway` → graded **multiplicative penalties**. Overpass or offline GeoJSON. |
| Scoring hook | `score/climbability.py` | New optional `tierb=` arg: gates (`eligible`) + applies the hazard penalty. **Never adds a positive term.** Absent ⇒ v1 behaviour is byte-for-byte unchanged. |
| Storage/serving | `db/migrations/002_tierb.sql`, `db/repository.py` | Adds `detected`, `eligible`, `hazards`, `tierb_penalty`; the API serves only `public_flag AND eligible` trees. |

Run the offline reconciliation demo (no network, no torch):

```bash
python -m tierB.run_reconcile \
    --trees data/sample_portland.geojson \
    --osm   data/sample_portland_osm.geojson
# -> Silver Maple EXCLUDED (private parcel); Douglas Fir penalised ×0.25 (power line)
```

Aerial detection over real imagery needs the extra + a source orthophoto (e.g.
NAIP): `pip install -r requirements-tierb.txt`, then drive
`tierB.detect.detect_orthophoto(...)`. **Detectree2** (better F1, needs
Detectron2) is documented but not wired — add it in a dedicated env.

---

## Tier C — street-level geometry (`tierC/`)

The hard, valuable part (spec §5). Recovers, from opportunistic **Mapillary**
street imagery, a **trunk DBH cross-check** (reliable-ish) and a **COARSE,
low-confidence branch ladder** — the branch-ladder signal that no inventory
carries. Trunk-DBH-from-photo is an established sub-area; per-branch geometry
from street imagery is barely in the literature, so **branch outputs are
confidence-gated by construction** and never claim published accuracies.

| Piece | Module | What it does |
|---|---|---|
| Imagery | `tierC/mapillary.py` | Mapillary API v4: tile coverage, Graph metadata, **nearest-image-to-point** (fetch tile → filter radius client-side), **`is_pano` exclusion**, and the mandatory **CC-BY-SA attribution** block for any displayed thumbnail. Network I/O is injectable → tests run offline. |
| Camera | `tierC/camera.py` | Pinhole model + back-projection; **refuses equirectangular frames** (pinhole invalid, spec §5.1). Intrinsics from `camera_parameters` or a depth model that predicts them. |
| Geometry | `tierC/geometry.py` | Trunk-width→DBH with error band; **Kåsa circle fit** for a back-projected cross-section; branch-ladder extraction from mask discontinuities with per-rung confidence decaying with height. |
| Backends | `tierC/backends.py` | Lazy **UniDepthV2** (metric depth + intrinsics) + trunk segmenter behind `requirements-tierc.txt`; dependency-free stubs drive the pipeline offline. |
| Pipeline A | `tierC/pipeline.py` | Single-frame monocular: segment → depth → measure. Emits the §5.3 contract (`dbh_cm_streetcv`, `lowest_branch_h_m`, `branch_ladder`, `tierC_confidence`), **withholding branch outputs below `BRANCH_GATE`**. |
| Pipeline B | `tierC/multiview.py` | Feed-forward multiview (**VGGT / MapAnything**) — documented seam, not wired. |
| Integration | `score/reach.py`, `score/climbability.py` | A gated ladder feeds `reach_match(branches=…, ladder_confidence=tierC_confidence)` → the **measured** path replaces the v1 form-based guess; `streetcv_feature(...)` activates the previously-dormant `w_c` term in the score. |
| Storage | `db/migrations/003_tierc.sql` | `dbh_cm_streetcv`, `lowest_branch_h_m`, `branch_ladder`, `tierc_confidence`, `f_streetcv`, `tierc` (full output incl. attribution). |

**Honesty:** `lowest_branch_h_m` and `branch_ladder` are the least-supported
outputs in the whole system (spec §5.3, §11). They ship behind `tierC_confidence`
(capped ≤ 0.70 for monocular) and must be validated against a hand-labelled set
before being trusted un-hedged. Running real geometry needs
`pip install -r requirements-tierc.txt` + a Mapillary token — **verify UniDepth /
VGGT licenses before commercial use** (spec §12).

---

## What v1 does

| Stage | Module | Summary |
|---|---|---|
| Ingest | `ingest/` | Declarative `sources.yaml` (crosswalk registry ported from OpenTrees) + a Python fetcher for ArcGIS Hub / Socrata / CKAN / GeoJSON. Applies per-source field crosswalks, unit conversions (DBH in→cm ×2.54, height ft→m ÷3.28084), a faithful `cleanTree` port (genus/species split, prune vacant/removed/stump, null unknown species), and dedup on `(source_id, source_ref)` then spatial ~1 m. |
| Species prior | `features/species_prior.py` | genus (→ species override → family) → `{wood_strength, scaffold_form, shed_risk}` from a curated ~130-genus qualitative table. Coarse tiers → `[0,1]`; **no fabricated MOR numbers**; unknown genus → `wood_strength=None` (lowers confidence, does not zero the score). Basis: USDA FPL Wood Handbook + Global Wood Density DB. |
| DBH feature | `features/dbh_feature.py` | Monotone, saturating size score (sapling floor, ~60 cm saturation). Height→DBH allometric fallback when DBH is null but height present, marked `estimated`. **DBH is trunk diameter at 1.3 m — not branch geometry**; kept honest in names/docs. |
| Score | `score/climbability.py` | Transparent confidence-weighted sum `S = w_sp·f_species + w_db·f_dbh + w_c·f_streetcv`. In Tier-A-only v1 `w_sp`/`w_db` dominate and `w_c` (street CV) is **dormant**. Emits a machine-readable `why_scored` trace, `confidence`, and `provenance`. No black box. |
| Reach-match | `score/reach.py` | Mount + ladder logic parameterised by user body (`h`, `weight`, `Δ`, `d_min`, `α`). **v1 has no real branch data, so it runs the DEGRADATION path**: a species-form + DBH plausibility score explicitly labelled a *form-based guess* — never a fake ladder. Load side (section modulus ∝ d³) only scales `d_min`; never a load rating. |
| Storage | `db/` | PostGIS with the exact `trees` schema; migrations; GiST index on `geom` **and** H3 bucket columns for viewport aggregation; per-tree `why_scored`/`confidence`/`provenance` stored. |
| API | `api/` | FastAPI. Viewport/radius query taking body params; reach-match runs **server-side per query** against stored features (no feature recompute). |
| Frontend | `frontend/` | MapLibre GL JS: radius + polygon selection, body-param inputs, per-tree detail panel (species, why-scored trace, **confidence badge**, Mapillary photo slot **with required attribution scaffolding**, waiver acceptance, report control feeding a correction/label queue). Confidence is rendered as badges + circle opacity + a "form-based guess" label — never implying uniform coverage. |

---

## Run it

### Option A — Docker (PostGIS + API + frontend)

```bash
cp .env.example .env
docker compose up --build
```

This starts PostGIS, applies migrations, seeds the bundled **offline sample**
(`data/sample_portland.geojson`, no network needed), and serves the app.

- App / map:  http://localhost:8000/
- API docs:   http://localhost:8000/docs
- Health:     http://localhost:8000/api/health

### Option B — local Python + local PostGIS

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Point at a PostGIS instance (see .env.example for vars)
export POSTGRES_HOST=localhost POSTGRES_USER=trees POSTGRES_PASSWORD=trees POSTGRES_DB=trees

python -m db.migrate                                    # create schema + indexes
python -m ingest.run_ingest --source portland_parks_trees \
       --sample data/sample_portland.geojson --to-db     # seed offline sample
uvicorn api.main:app --reload                            # serve at :8000
```

### Ingesting real data

```bash
python -m ingest.run_ingest --list                       # show configured sources
python -m ingest.run_ingest --source nyc_street_trees_2015 --max 5000 --to-db
python -m ingest.run_ingest --all --out data/trees.json  # dry run to JSON (no DB)
```

Add a new city by appending an entry to `ingest/sources.yaml` — **no code
change required**. Path 2 (live-portal querying) keeps `captured_at` fresh by
paging ArcGIS Feature Services / Socrata endpoints directly.

### Tests

```bash
pip install -r requirements.txt
pytest            # cleanTree, crosswalk, species prior, DBH, climbability,
                  # reach-match, ingest pipeline, API
```

---

## Example API call

```
GET /api/trees?lon=-122.6765&lat=45.5231&radius_m=1000&h=1.8&weight=95&d_min=10
```

Returns each candidate with `score`, `confidence`, full `why_scored`,
`provenance`, and a per-request `reach_match` block. In v1 every `reach_match`
has `"is_measured_ladder": false`, `"mode": "form_based_guess"`, and an empty
`ladder` — because there is no branch data to build a real ladder from.

---

## Module seams left for later tiers (not built in v1)

- **Tier C street CV** — `score_tree(..., f_streetcv=…)` already accepts the
  signal; passing it activates `w_c` and adds `C:street_cv` to provenance. The
  frontend has a **Mapillary photo slot with attribution scaffolding** wired.
- **Real branch ladders** — `score/reach.py::reach_match(branches=[(h,d),…])`
  runs the full mount+ladder logic today; it is exercised in tests. v1 simply
  never has `branches`, so it degrades to the form-based guess.
- **Tier B eligibility gates / hazard penalties** — `public_flag` gating is
  live; parcel/power-line gates plug into `query_trees` and the score.

---

## Honest residual gaps (read this)

These are **product-defining limitations**, not TODOs to hide:

1. **The branch-ladder is the least-supported piece of the whole system.** No
   tree inventory on earth records lowest-branch height or per-branch diameters
   (confirmed across ~228 OpenTrees crosswalks). Recovering per-branch geometry
   from street imagery is largely unproven, and even phone-LiDAR QSM only
   cleanly recovers limbs ≥ ~30 cm diameter. **In v1 the reach-match is a
   form-based guess about crown architecture, not a measurement.**
2. **Published monocular-vision accuracies come from controlled capture** and
   will not transfer to opportunistic street imagery unmeasured. We do not
   claim them.
3. **Coverage is doubly gated and anti-correlated with demand.** A tree is
   well-covered only where (a) the city publishes an inventory **and** (b)
   ground-level imagery exists. The deep-park trees a climber most wants are
   exactly where both are thinnest. The UI renders this via confidence badges
   and map opacity; it never implies uniform coverage.
4. **The anthropometric & load constants are placeholders/tunables, not
   physical truths.** `α` (ground-reach coefficient ≈ 1.2–1.25), `Δ`
   (inter-branch step), and `d_min` (≈ 10 cm, scaled by body weight via section
   modulus) are exposed as knobs, not asserted facts.
5. **No safety certification.** The output is always a ranked, confidence-tagged
   *candidate* list. The waiver covers residual risk. Do not climb a tree
   because this tool ranked it highly.

---

## Design invariants (hard constraints, enforced in code)

1. **No certification** — ranked candidates only; every number carries an error
   band. `confidence` is hard-capped at 0.75 in Tier-A-only mode.
2. **Evidence tiers explicit & separable** — every tree carries `confidence` +
   `provenance.tiers`; the UI surfaces both.
3. **Public/eligible trees only** — `public_flag` gate defaults on; most sources
   are government street/park trees.
4. **Cheapest reliable signal first** — species prior + DBH anchor the score;
   nothing else is a prerequisite in v1.
5. **Licensing is load-bearing** — any displayed Mapillary thumbnail requires
   logo + link + contributor attribution; the slot exists even though Tier C
   imagery is not wired in v1.

---

## Attribution & licenses

- Tree data: per-source, see `provenance.license` on each tree and
  `ingest/sources.yaml`. Approach ported from **stevage/opentrees-data (MIT)**.
- Map: **MapLibre GL JS (BSD-3)**, demo tiles from MapLibre.
- Wood/form priors: qualitative tiers grounded in **USDA FPL Wood Handbook
  (FPL-GTR-282)** and the **Global Wood Density Database (Zanne et al. 2009)**.
  No species-level MOR values are fabricated.
