#!/usr/bin/env sh
# Production entrypoint: migrate, (optionally) seed, then serve under gunicorn
# with uvicorn workers. Configure via environment (see .env.example / DEPLOY.md).
set -e

: "${API_HOST:=0.0.0.0}"
: "${API_PORT:=8000}"
: "${WEB_CONCURRENCY:=4}"        # gunicorn workers; ~2*CPU + 1 is a good start

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[start] applying migrations…"
  python -m db.migrate
fi

if [ "${SEED_SAMPLE:-0}" = "1" ]; then
  echo "[start] seeding offline sample…"
  python -m ingest.run_ingest --source portland_parks_trees \
         --sample data/sample_portland.geojson --to-db || true
fi

echo "[start] serving on ${API_HOST}:${API_PORT} with ${WEB_CONCURRENCY} workers"
exec gunicorn api.main:app \
  --workers "${WEB_CONCURRENCY}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "${API_HOST}:${API_PORT}" \
  --access-logfile - --error-logfile - --timeout 60
