#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".env" ]; then
  echo "Missing .env in $ROOT_DIR. Copy .env.example to .env and set ADMIN_TOKEN and WORKER_SECRET first." >&2
  exit 1
fi

export PYTHONIOENCODING="utf-8"
exec python3 "$ROOT_DIR/backend/run_cluster.py"
