# Agent Activity Observatory — MVP (vertical slice)

A local, **metadata-first** dashboard that visualizes observable agent coding
activity while the agent keeps working in the user's terminal. This repository
currently contains the **first working vertical slice** of the product — no
Claude Code integration is configured or claimed:

```
synthetic sanitized event → durable local spool → Python collector
→ FastAPI → SQLite → WebSocket → React activity timeline
```

Everything in this docs set is validated against the end-to-end scenario below.
**Real agent hook capture is not implemented yet**; the only events in the
system are explicitly synthetic demo fixtures. See
[docs/claude-code-integration.md](docs/claude-code-integration.md) for the
honest status of the planned hook integration.

---

## 1. What this slice includes

| Area | Status |
|---|---|
| Versioned event schemas (sanitized source + normalized, cursor-based) | ✅ implemented, tested |
| Atomic local spool (one file/event, `os.replace` publication, bounded, fail-open) | ✅ implemented, tested |
| Collector daemon (batching, retry + backoff, delete-only-after-accepted, quarantine) | ✅ implemented, tested |
| FastAPI backend (ingest auth, sessions, snapshot, paginated history, live WebSocket) | ✅ implemented, tested |
| SQLite persistence + Alembic migrations, restart-safe, dedup by event id | ✅ implemented, tested |
| Replay/reconnect protocol (snapshot → `subscribe(after=cursor)` → replay+live) | ✅ implemented, tested |
| React dashboard: session selector, live timeline, states, demo labeling | ✅ implemented, tested |
| Local security: loopback binding, ingest credential, dashboard access code + HttpOnly cookie, origin allowlist, no CORS | ✅ implemented, tested |
| Privacy: allowlist sanitization, no network in capture path, no raw payloads in spool/logs | ✅ implemented at the demo-publisher level |
| Hook receiver for Claude Code, installer, doctor (real integration) | ⛔ next milestone — nothing installed by this code |
| Expertise classification, brain SVG map | ⛔ deliberately out of scope for this slice |
| Playwright end-to-end coverage | ⛔ planned (Vitest + RTL coverage exists) |

Core principles honored in this slice:

- **Passive observation only.** Nothing here launches, controls, or approves
  anything for any agent.
- **Metadata first.** Prompts, file contents, unrestricted command text and
  tool output are never persisted; the spool contains only allowlisted
  summary fields (tool names, project-relative paths, coarse command
  categories).
- **Evidence over inference.** No expertise labels, no hidden-reasoning
  claims, no fabricated telemetry. Session states derive only from observed
  event kinds.
- **The dashboard is not a dependency of the workflow.** If the backend goes
  down, the collector queues locally and Claude Code (in future milestones)
  is never blocked.

See [AGENTS.md](AGENTS.md) (the project specification) for the full product
scope and constraints.

---

## 2. Quick start (3 terminals, no agent required)

Requirements: **Python ≥ 3.12** (the repo's `./brain` venv uses 3.14) and
**Node 22+**. Linux/macOS primary; Windows supported in principle but
untested yet.

```bash
# terminal 1 — backend
cd ~/Documents/agent_brain
./brain/bin/pip install -e .                      # first run only
./brain/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# -> backend serves /api on 127.0.0.1:8000 (loopback only)
# -> prints the dashboard access code location:
#    e.g. ~/.local/share/agent-brain-observatory/dashboard_code  (mode 0600)

# terminal 2 — collector
cd ~/Documents/agent_brain
./brain/bin/observatory collector
# watches the spool and delivers events to http://127.0.0.1:8000

# terminal 3 — publish the synthetic demo events (no agent install needed)
cd ~/Documents/agent_brain
./brain/bin/observatory demo-publish            # writes through the REAL spool
# then EITHER let the running collector deliver it (terminal 2),
# or deliver once and stop:
./brain/bin/observatory collector --once
```

Browser session (one-time per browser):

```bash
./brain/bin/observatory doctor    # shows the dashboard access code location
cat ~/.local/share/agent-brain-observatory/dashboard_code
```

Start the frontend and paste the code:

```bash
cd frontend
npm install                       # first run only
npm run dev                       # http://127.0.0.1:5173
```

Open <http://127.0.0.1:5173>, choose the session
`Synthetic demo session`, enter the access code once — the HttpOnly cookie is
set and the timeline starts streaming live. Events arrive in < 1 s on a
virtualized localhost when the collector polls on its default interval.

> **The demo never touches the UI directly:** `demo-publish` only writes
> sanitized events into the spool; the real collector daemon delivers them to
> the real backend, which persists them before broadcasting.

### Publishing again / when the backend is down

`observatory demo-publish` generates **fresh event IDs per run** for the same
demo session, so you can:

- run it repeatedly — events append, never duplicate;
- run it while the backend is stopped — the collector retries with backoff
  and delivers the same event IDs after recovery (see the acceptance
  scenario below).

Useful switches: `--repetitions N` (N passes over the fixture), `--fixture
path.json`, `--session-id custom-id`, `--data-dir path` and `--backend URL`
(globals, before the subcommand).

---

## 3. Acceptance scenario (the one this slice was built for)

Run in this order and compare with the checks:

```bash
# 1. backend (terminal 1), frontend (terminal 3 instructions above)
# 2. publish + deliver
./brain/bin/observatory demo-publish
./brain/bin/observatory collector --once

# 3. verify in the UI: synthetic session visible, events streaming
#    (session bar shows "demo · synthetic data" and "live (connected)")

# 4. STOP the backend (Ctrl+C in terminal 1), then publish more events
./brain/bin/observatory demo-publish
# collector now blocks with backoff ("temporary backend failure"), events stay queued

# 5. restart the backend
./brain/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 6. same event IDs are delivered once
./brain/bin/observatory collector --once
# ui note: the timeline appends the queued events without duplicates

# 7. refresh the browser (or kill/reopen the tab)
#    -> snapshot loads persisted history, WS resumes from the snapshot cursor,
#       no gaps between snapshot and live subscription, no duplicates
```

Automated equivalents (running against mocks/fixtures, no manual steps):
`backend/tests/test_replay_ws.py` (real uvicorn + real websockets client:
replay, live delivery, reconnect-without-loss, origin/cookie rejection) and
`backend/tests/test_persistence_restart.py` (restart + duplicate replay).

---

## 4. Exact commands

### Setup

```bash
# Python (using the repo's existing venv, or create your own)
./brain/bin/pip install -e ".[dev]"     # editable install with test tooling
# or pinned to the lockfile:
./brain/bin/pip install -r requirements.txt && ./brain/bin/pip install -e .

# Frontend
cd frontend && npm install
```

### Run

| Command | What it does |
|---|---|
| `./brain/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` | backend API + WebSocket (loopback) |
| `./brain/bin/observatory collector` | collector daemon (clean shutdown on Ctrl+C) |
| `./brain/bin/observatory collector --once` | deliver queued events, exit |
| `./brain/bin/observatory demo-publish` | publish synthetic events through the spool |
| `./brain/bin/observatory doctor` | local diagnostics (read-only) |
| `cd frontend && npm run dev` | Vite dev server on 127.0.0.1:5173 (proxies `/api`) |

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OBSERVATORY_DATA_DIR` | platform data dir (`~/.local/share/agent-brain-observatory`) | DB, credentials, spool, dashboard code |
| `OBSERVATORY_SPOOL_DIR` | `$OBSERVATORY_DATA_DIR/spool` | spool root |
| `OBSERVATORY_HOST` / `OBSERVATORY_PORT` | `127.0.0.1` / `8000` | bind address **and the port used to derive allowed browser origins — keep it matching `uvicorn --port`** |
| `OBSERVATORY_ENV` | `development` | `production` also serves `frontend/dist` |
| `OBSERVATORY_DEV_ORIGINS` | `http://localhost:5173 …` | explicit dev-only origin allowlist extras |

### Tests / checks

```bash
# Python (backend + collector): 74 tests
./brain/bin/python -m pytest backend/tests collector/tests

# Lint + format (Python)
./brain/bin/ruff check backend collector
./brain/bin/ruff format backend collector

# Frontend: 14 tests
cd frontend && npm test

# Frontend lint + typecheck + production build
cd frontend && npm run lint && npm run build
```

### Production-style build (served by FastAPI, single origin)

```bash
cd frontend && npm run build      # emits frontend/dist
# OBSERVATORY_PORT must match --port (it derives the allowed dashboard origins)
OBSERVATORY_ENV=production ./brain/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# SPA is served from the same origin; cookie and origins are same-host now
```

---

## 5. Data flow and guarantees

```
observatory demo-publish (synthetic fixture, allowlist-sanitized payloads)
        │  writes JSON files (tmp + os.replace → atomic publication, no locking)
        ▼
      spool/                     ── one file per event: <nanotimestamp>-<event_id>.json
        │
observatory collector (daemon; ~pol every 0.5 s, batch ≤ 50 events, ≤ 256 KiB)
        │  POST /api/events/batch  (Authorization: Bearer <local credential>)
        │  retry on transport errors / 5xx / 429 / 413 with exponential backoff + jitter
        │  deletion only after the per-event acceptance report;
        │  permanently invalid events are quarantined, never logged
        ▼
FastAPI backend (single process)
        │  validates schema (v1), dedupes by event_id, upserts session+machine rows
        │  assigns global cursor, PERSISTS, then broadcasts (persist-before-publish)
        ▼
SQLite (WAL)  — machines, sessions, events(+cursor, event_id unique,…)
        │
        │ HTTP: GET /api/sessions, /api/sessions/{id}/snapshot,
        │       /api/sessions/{id}/events?after=<cursor>&limit=…
        │ WS:   /api/sessions/{id}/live  (send {"type":"subscribe","after":N})
        ▼
React dashboard
```

Guarantees implemented and tested in this slice:

- **Idempotent ingestion**: a retry of the same batch is reported as
  duplicates; late/out-of-order events are accepted with a new cursor, keeping
  their `occurred_at`.
- **No-loss reconnects**: the WS listener is registered under the publish
  lock *before* SQLite replay, so an event is either replayed from the DB or
  queued live. The client dedupes by cursor/event id. Overflow policy is
  fail-open, honest diagnostics (see `docs/privacy.md`).
- **Session states stay conservative**: `unknown / turn_active /
  turn_finished / ended` mapped only from observed event kinds; `ended`
  never re-activates; missing tool completions leave "unresolved" badges.
- **Persist-before-broadcast**, and broadcasts are serialized so cursor order
  on the wire matches SQLite order.
- **Bounded payloads**: batch ≤ 100 events and ≤ 512 KiB per post (413/422
  otherwise); spool caps at 5000 files / 20 MiB, dropping the OLDEST events
  (fail-open) with a sanitized diagnostics note.

---

## 6. Security model (short version; details in docs/privacy.md)

- Backend binds **127.0.0.1** by default; never exposes ingress without intent.
- **Ingestion** requires `Bearer` token → generated file `collector_credential`
  (0600 data dir). The token is never rendered into frontend assets or URLs.
- **Dashboard** needs an access code shown by the backend (file
  `dashboard_code`, 0600) — exchanged for an **HttpOnly, SameSite=Strict
  cookie** via POST body, never via URL. Login + API + WS validate the
  **origin allowlist**; permissive CORS is never enabled.
- Everything is local-only; data deletion = remove the data directory (below).

### Managing local data

```bash
# where is the data?
./brain/bin/observatory doctor

# delete everything (backend stopped): the data dir is disposable
rm -r ~/.local/share/agent-brain-observatory
# or a test/demo dir directly:
rm -r /tmp/opencode/<your-dir>
```

---

## 7. Known limitations

1. **No real agent integration.** The capture path is validated end-to-end
   with explicitly synthetic fixtures only. No Claude Code hooks were
   configured or tested (this was an explicit task constraint).
2. **Single process backend.** SQLite + in-process broadcasting; multi-worker
   WebSocket fanout is out of scope by spec.
3. **Browser sessions are in-memory.** A backend restart logs out the
   dashboard (the access code flow makes this cheap). The session cookie is
   not bound to a stored session table.
4. **Snapshot window.** The snapshot returns the latest 200 events of a
   session; older history must be paginated explicitly (no auto older-scroll
   yet, timeline simply notes when older events were not loaded).
5. **WS queue is unbounded.** A slow dashboard could accumulate memory in
   exceptional cases; honest behavior (no silent event dropping) was chosen
   per spec.
6. **Delivery order/cursor note.** WS-replayed and live events may interleave
   slightly out of order; the feed re-orders and dedupes by cursor/event-id.
7. **Command allowlist is a starter set.** `pytest`, `npm`, `ruff/eslint`,
   `docker`, `alembic`, `git`, `python`, `node` signatures recognized; other
   commands produce no coarse category (sanitization keeps them out of the
   spool entirely).
8. **No auth beyond loopback.** Local threats beyond plain loopback binding
   are documented in docs/privacy.md — the residual risk items are listed
   there explicitly.
9. **Playwright E2E** not yet added (task scope: this slice only).

---

## 8. Documentation map

- [AGENTS.md](AGENTS.md) — project specification (source of truth)
- [docs/architecture.md](docs/architecture.md) — components, protocol, models
- [docs/claude-code-integration.md](docs/claude-code-integration.md) — verified
  integration status (currently: **not yet verified**, plans only)
- [docs/privacy.md](docs/privacy.md) — collection policy, residual risks,
  data deletion
- [docs/development.md](docs/development.md) — repo layout, module map, testing
  conventions
- [LICENSE](LICENSE) — Apache License 2.0

---

*Last validated* (on this working copy, with a disposable `OBSERVATORY_DATA_DIR`):
the §3 acceptance scenario was executed for real — 13 events delivered, 13
published during a backend outage, backend restarted, and the queued 13
recovered with their original event IDs (39 unique events, cursors contiguous
1 → 39, zero duplicates); a WebSocket client subscribed before delivery and
received the 13 fresh events live; the Vite dev proxy (login + WS through it)
and production static serving were verified the same way. Checks: 74 Python +
14 frontend tests passing, ruff and eslint clean, production build clean.
