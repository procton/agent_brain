# Development guide (MVP slice)

## Repository layout

```
backend/
  alembic.ini, migrations/      Alembic environment + initial migration (0001)
  app/
    config.py                   settings + credential/dashboard-code files (0600)
    main.py                     create_app(): migrations, state wiring, prod static
    schemas/                    base.py (kinds, state map) · source.py (v1 wire)
                                · normalized.py (stored/view models)
    database/                   engine.py (async engine + pragmas)
                                · models.py (SQLAlchemy) · migrations.py runner
    services/                   ingest.py · hub.py (broadcast) · views.py
    api/                        events.py (batch) · sessions.py · ws.py · health.py
  tests/                        45 tests: ingestion, auth, sessions, live WS on a
                                real uvicorn socket, restart persistence, static
collector/
  spool.py                      atomic publication, pending/quarantine, limits
  sanitization.py               allowlist extraction (shared by future receiver)
  demo_events.py                synthetic fixture materialization
  daemon.py                     batching, retry/backoff, report-driven deletion
  cli.py                        observatory {demo-publish,collector,doctor}
  tests/                        30 tests incl. concurrent publication + retries
frontend/
  src/api/                      typed client (cookie session; no ingest token here)
  src/features/
    timeline/feed.ts            pure dedupe/order/resume state
    timeline/useLiveSession.ts  snapshot → ws → reconnect hook (reducer-held)
    timeline/ActivityTimeline.tsx
    sessions/SessionBar.tsx     selector, project label, status pill
  src/components/               States.tsx, AccessCodeGate.tsx
  src/test/                     steps + App tests w/ MockWebSocket + fetch mock
fixtures/synthetic/             explicitly synthetic demo fixture
```

## Conventions

- **Python**: 3.12+, `from __future__ import annotations`, SQLAlchemy 2.0
  typed mappings, Pydantic v2, absolute imports (`backend.app.…`,
  `collector.…`). Ruff (`check` + `format`) is the lint/format authority.
- **Blocking DB work** is only allowed in migration startup (Alembic); the
  app uses aiosqlite everywhere else.
- **Tests use temporary data dirs only** (`OBSERVATORY_DATA_DIR` fixture) —
  never the developer's real home data; nothing here touches Claude Code
  settings.
- **Frontend**: TS strict; React 19 function components; pure feed state so
  reducer composition is testable; ESLint flat config with react-hooks
  recommended; Vitest + RTL + jsdom, no global stubbing surprises: tests
  explicitly `cleanup()` because globals are off.

## Test-writing rules of thumb learned in this slice

- Test the *protocol invariant*, not the implementation detail: e.g.
  reconnect-with-after must deliver every missed event and no already-delivered
  one (see `backend/tests/test_replay_ws.py`).
- Always drive ingestion in live-server tests **through the HTTP API**, not
  direct service calls — keeps every async primitive inside the server loop.
- Frontend DOM assertions that can legitimately match several nodes must use
  scoped selections (`within`, class selectors) or `getAllBy…`.
- No payload content may end up in test logs: if your failure output could
  contain a prompt or file content, assert on ids/counts instead.

## Commands

```bash
./brain/bin/python -m pytest backend/tests collector/tests   # Python: 74
./brain/bin/ruff check backend collector && ./brain/bin/ruff format backend collector
cd frontend && npm test && npm run lint && npm run build      # Frontend: 14
```

## Adding a new event kind

1. Extend `EVENT_KINDS` in `backend/app/schemas/base.py` and add its
   conservative state mapping (or explicitly map to "no state change").
2. No frontend change is required to *display* it (falls back to the raw
   kind with a label key missing); add a `KIND_LABELS` entry for polish.
3. Extend the fixture and add/adjust tests (schema validation is automatic).
