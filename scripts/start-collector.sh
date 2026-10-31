#!/usr/bin/env bash
# Terminal 2 — collector daemon (deliveres spool events to the backend).
# Same data directory as the other terminals (default: platform app data dir).
# Overridable: OBSERVATORY_PORT (default 8041), OBSERVATORY_DATA_DIR.
# Extra args are forwarded after `collector` (e.g. --once).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${OBSERVATORY_PORT:-8041}"

exec ./brain/bin/observatory --backend "http://127.0.0.1:${PORT}" collector "$@"
