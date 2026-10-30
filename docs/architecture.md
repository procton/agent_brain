# Architecture (MVP slice)

This documents the implementation as it exists today (v0.1.0). It follows
AGENT.md §4 and deviates from it exactly where noted.

```
┌───────────────────────────────────────────────────────────────────────┐
│ demo publisher (observatory demo-publish)                             │
│  · loads fixtures/synthetic/demo_session.json                         │
│  · fresh UUIDs per publish, same synthetic session id                 │
│  · writes ONLY allowlisted summary fields                             │
└──────────────┬────────────────────────────────────────────────────────┘
               │ json file per event (Spool.publish: tmp+os.replace)
               ▼         ┌───────────────────────────────┐
        durable spool    │ collector/collector/spool.py  │
       NaN-timestamp     │ pending/ + quarantine/ + log  │
       ordered files     └───────────────────────────────┘
               │ collector daemon polls (0.5 s), assembles bounded batches
               │ Authorization: Bearer <collector_credential>
               ▼                          HTTP only here
┌──────────────────────────────────────────────────────────────────────┐
│ FastAPI backend (backend/app) — single process                        │
│  POST /api/events/batch   auth + size limits + schema v1 validation   │
│  services/ingest.py       dedupe(event_id) → upsert → persist →       │
│                           broadcast (one lock spans cursor order)     │
│  database (SQLite WAL + Alembic)                                      │
│    machines · sessions · events(cursor PK, unique event_id, idx       │
│    (session_id, cursor)) · __schema_metadata__                        │
│  api/sessions.py          list / snapshot(≤200) / events(after, limit)│
│  api/ws.py                subscribe(after) → replay+live, watermark   │
└──────────────────┬───────────────────────────────────────────────────┘
                   │ same-origin HTTP + WebSocket (cookie-authenticated)
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ React dashboard (frontend/src)                                        │
│  useLiveSession: snapshot → WS subscribe(after) → replay+live →       │
│  reconnect w/ backoff; pure-feed dedupe/ordering (features/timeline/  │
│  feed.ts); states: loading / live / reconnecting / error /            │
│  auth_required; demo sessions carry an explicit synthetic badge       │
└──────────────────────────────────────────────────────────────────────┘
```

## Schema layers

1. **Source event** (`backend/app/schemas/source.py`, v1) — the wire format
   between spool and backend: `event_id, machine_id, session_id, source,
   source_event, kind, occurred_at?, recorded_at, correlation, summary`.
   Unknown fields are ignored upstream, never persisted.
2. **Normalized event** (`schemas/normalized.py`) — what is stored and shown:
   adds the server-assigned `cursor` and backend `received_at`; keeps the
   source `event_id` for dedup. `occurred_at` stays null when the source has
   no credible timestamp.
3. **Frontend view models** (`frontend/src/api/types.ts`) — typed mirror of
   layer 2 plus timeline item projection.

Schema versions are part of every envelope; the DB stores its version in a
dedicated table and Alembic owns table migrations.

## Session identity and state

- Identity = `machine_id + source + source_session_id`; sessions without
  identifiers cannot be attributed to anything.
- State machine (`schemas/base.py`): `unknown → turn_active →
  turn_finished → ended` strictly from observed kinds. `session.started`
  never *downgrades* a specific state; `session.ended` is terminal; a new
  prompt after a finished turn is evidence of a new turn.
- Transport connectivity is a separate concern (dashboard status pill), never
  conflated with agent activity.

## Reconnect protocol (tested, gap-free)

1. Browser: `GET /snapshot` → `{session, events, latest_cursor}`.
2. Browser: connect `WS /live`, send `{"type":"subscribe","after":<cursor>}`.
3. Server registers the listener **under the publish lock**, replays
   SQLite events `> after` in chunks, then streams live pushes.
4. Clients dedupe by `event_id`/`cursor`; server watermark-skips queued
   duplicates.

Because ingestion persists before publishing, an event is always in at least
one of {replay result, live queue} → **no gaps, possible duplicates only**.

## Deviations from AGENT.md

- `collector/demo_events.py` is added (the synthetic demo publisher); the
  hook `receiver` and `installer` modules are the next milestone and
  intentionally absent (no Claude Code settings are touched).
- No `brain visualization` or `classification` directories exist yet.

## Notable design decisions

- **One lock spans persist+commit+broadcast**: guarantees wire cursor order
  even when batches race; replay watermarks remain sound.
- **Global cursor**: a session's cursors are globally sparse (other sessions
  interleave). Snapshot "contiguous" therefore means *session-visible range
  loaded and complete*, and `resumeAfter()` asks for a full replay whenever
  contiguity is uncertain (dedupe makes the cost tiny).
- **Fail-open spool**: overflow drops the oldest pending events and only
  writes a sanitized diagnostics line. Claude Code (future milestone) is
  never blocked by telemetry concerns.
