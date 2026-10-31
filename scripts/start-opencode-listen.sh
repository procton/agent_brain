#!/usr/bin/env bash
# Terminal 3 — passive OpenCode listener (subscribes to the local background
# service SSE stream and publishes sanitized events into the shared spool).
# Read-only toward OpenCode; discovery + password come from
# `opencode service status` / ~/.config/opencode/service.json unless overridden
# with OBSERVATORY_OPENCODE_SERVER / OBSERVATORY_OPENCODE_PASSWORD or
# --server/--password-file (extra args are forwarded to `opencode-listen`).
# Overridable: OBSERVATORY_DATA_DIR.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

exec ./brain/bin/observatory opencode-listen "$@"
