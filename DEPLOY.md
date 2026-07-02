# Deploying Climbable-Trees

A single FastAPI service (gunicorn + uvicorn workers) backed by PostGIS, serving
a static MapLibre frontend. There is **one unified assessment** — no tiers: each
tree gets one `score`, one `confidence`, and a flat `provenance.signals` list
naming what contributed (`species_prior`, `trunk_size`, `eligibility`, `hazard`,
`aerial_detection`, `street_geometry`).

## 1. Prerequisites

- Docker + Docker Compose (simplest), **or** Python 3.11 + a PostGIS 15/16 database.
- Outbound HTTPS from the browser to `tiles.openfreemap.org` for the basemap
  (or self-host tiles — see §5).

## 2. Fastest path — Docker Compose

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, and ALLOWED_ORIGINS to your domain
docker compose up --build -d
```

Compose brings up PostGIS, waits for health, then the API container runs
`start.sh` → migrations → seeds the bundled offline sample (`SEED_SAMPLE=1`) →
serves. Open <http://localhost:8000>.

- App / map: `/`
- API docs: `/docs`
- Health: `/api/health` → `{"status":"ok", ...}`

## 3. Loading real data

The sample is 5 Portland trees. For real coverage, ingest live city portals into
the running DB (schema already migrated):

```bash
docker compose exec api python -m ingest.run_ingest --list
docker compose exec api python -m ingest.run_ingest --source nyc_street_trees_2015 --to-db
docker compose exec api python -m ingest.run_ingest --source portland_parks_trees --to-db
# ...add sources in ingest/sources.yaml
```

Eligibility/hazard reconciliation (OSM parcels + power lines) runs as a batch:

```bash
docker compose exec api python -m tierB.run_reconcile \
  --trees data/<your_trees>.geojson --osm data/<osm_extract>.geojson
```

Street-level geometry (measured branch ladders + ground photos) is an **offline
enrichment** — it needs a Mapillary token and the heavy ML extra
(`requirements-tierc.txt`, GPU recommended). It writes measured branch geometry
back onto tree rows, after which the unified score uses it automatically.

## 4. Manual (no Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export POSTGRES_HOST=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=...
export ALLOWED_ORIGINS="https://trees.example.com"
export WEB_CONCURRENCY=4
./start.sh          # migrate + serve under gunicorn/uvicorn workers
```

### Look without a database (demo mode)

```bash
DEMO_MODE=1 uvicorn api.main:app --port 8000
```

Serves the bundled sample from memory (no PostGIS). For local inspection only —
not a deployment target.

## 5. Production notes

- **Reverse proxy / TLS:** terminate TLS at nginx/Caddy/an ALB in front of the
  API; set `ALLOWED_ORIGINS` to your exact origin(s) — never `*` in production.
- **Workers:** tune `WEB_CONCURRENCY` (~`2*CPU + 1`). Reach-match runs per
  request in Python but is cheap (no feature recompute — features are stored).
- **Database:** use managed PostGIS or a persistent volume (compose ships
  `pgdata`). Indexes (GiST on `geom`, H3 buckets, `eligible`) are created by the
  migrations. Back up the volume.
- **Basemap at scale:** OpenFreeMap's public endpoint is free but best-effort;
  for production traffic self-host OpenFreeMap/OpenMapTiles or use a keyed
  provider (MapTiler, etc.) and update the `style` URL in `frontend/app.js`.
- **Attribution:** if you display Mapillary ground photos, the CC-BY-SA logo +
  link + contributor credit must render (the slot + `provenance ... attribution`
  already carry it). This is a licensing obligation, not optional.
- **Health/monitoring:** container `HEALTHCHECK` hits `/api/health`; wire it to
  your orchestrator's liveness/readiness probes.

## 6. What the service promises (and refuses)

It returns a **ranked, confidence-tagged candidate list and never certifies that
a tree is safe to climb.** Every number carries an error band; reach-match is a
form-based guess unless measured branch geometry exists. A user waiver covers
residual risk. Keep this framing in any UI you build on top of the API.
