#!/usr/bin/env bash
set -euo pipefail

PORT="${WORKER_PORT:-8001}"
INTERVAL="${WORKER_TELEMETRY_INTERVAL:-1.5}"

# WORKER_SECRET and CB_API_KEY (if set) are read automatically from environment variables.
python -m worker.agent \
  --worker-id "${WORKER_ID:-worker-1}" \
  --ip-address "${WORKER_IP:-worker-1}" \
  --port "${PORT}" \
  --interval "${INTERVAL}" \
  --controller-url "${CONTROLLER_URL:-http://controller:8000}" &

exec uvicorn worker.executor:app --host 0.0.0.0 --port "${PORT}" --workers 1
