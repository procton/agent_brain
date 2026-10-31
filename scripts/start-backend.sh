#!/usr/bin/env bash
# Terminal 1 — backend (serves the API and, in production mode, the built UI).
# The dashboard access code is printed here at startup.
# Overridable: OBSERVATORY_PORT, OBSERVATORY_DATA_DIR, OBSERVATORY_ENV.
# Extra args are forwarded to uvicorn.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export OBSERVATORY_ENV="${OBSERVATORY_ENV:-production}"
export OBSERVATORY_PORT="${OBSERVATORY_PORT:-8041}"

if [ ! -f frontend/dist/index.html ]; then
  echo "[start-backend] frontend/dist missing — run: (cd frontend && npm run build)" >&2
  echo "[start-backend] continuing: the API works, only the SPA at / is absent." >&2
fi

exec ./brain/bin/uvicorn backend.app.main:app \
  --host "${OBSERVATORY_HOST:-127.0.0.1}" \
  --port "$OBSERVATORY_PORT" \
  --log-level warning "$@"
