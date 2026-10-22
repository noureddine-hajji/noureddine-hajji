#!/bin/sh
# Serve immediately; if no warehouse exists yet, ingest + build in the background.
# /healthz answers at once, /readyz and the API return 503 until the build finishes.
set -e
DB="${SUPTRACKER_DB:-${SUPTRACKER_DATA:-/data}/suptracker.duckdb}"
export SUPTRACKER_DB="$DB"
if [ ! -f "$DB" ] && [ "${SUPTRACKER_AUTOBUILD:-1}" = "1" ]; then
  echo "[entrypoint] no warehouse at $DB: fetching SIES data and building in background"
  (python -m suptracker.ingest && python -m suptracker.build \
     && python scripts/verify_ground_truth.py --out "${SUPTRACKER_DATA:-/data}/reports" \
     || echo "[entrypoint] build FAILED, see logs above") &
fi
exec uvicorn suptracker.api:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
