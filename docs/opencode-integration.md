# OpenCode integration (passive listener)

Validated against **OpenCode 2.2.0** on 2026-10-30 (live service on
`http://127.0.0.1:<port>`). All facts below were observed on a running
service; nothing here is assumed from the OpenAPI spec alone.

## How the connector works

OpenCode's background service exposes an **SSE event stream** that any local
API client can subscribe to. The observatory connector
(`collector/opencode_listener.py`) subscribes *read-only* like any other
client:

```text
OpenCode (background service, already running)
  │  GET /api/event   (text/event-stream, Basic auth)
  ▼
observatory opencode-listen        ← passive listener, zero OpenCode config
  │  strict event-type allowlist + metadata sanitization
  ▼
local spool  →  observatory collector  →  FastAPI  →  SQLite  →  dashboard
```

Passivity guarantee: the listener only ever issues `GET /api/event`. It never
writes to OpenCode (no `POST`, no config change, no plugin install, no
restart of OpenCode). Unsubscribing is as simple as stopping the process —
`Ctrl+C` or `kill` (SIGTERM is handled; the collector keeps any queued events
and the backend keeps its history).

## Discovery and authentication

The service URL and credentials are resolved in this order:

1. `--server <url>` CLI flag (or `OBSERVATORY_OPENCODE_SERVER` env).
2. Automatic discovery via `opencode service status` — the binary prints its
   URL (e.g. `http://127.0.0.1:49374`), which starts with `http://`/`https://`.
3. Password: `--password-file <path>`, else `OBSERVATORY_OPENCODE_PASSWORD`,
   else the standard file `~/.config/opencode/service.json` (XDG-aware),
   which contains `{"password": "..."}`.

The HTTP stream requires **Basic auth with username `opencode`**:

```text
Authorization: Basic base64("opencode:" + password)
```

(Verified: `Bearer <password>`, raw `Authorization: <password>` and
`x-opencode-password` all return 401; Basic form returns 200.)

The password is never printed, logged, or persisted by the observatory. It
lives only in process memory. If you want to rotate it, `opencode service
restart` regenerates it (the OpenCode TUI reconnects on its own).

## Wire format and mapping

Verified stream shape (every `data:` line is one JSON event, heartbeat
comments appear as `: heartbeat` lines):

```json
{
  "id": "evt_...",
  "created": 1793377985603,
  "type": "session.tool.called",
  "location": { "directory": "/home/you/project" },
  "data": { "sessionID": "ses_...", "...": "..." },
  "durable": { "aggregateID": "ses_...", "seq": 3013, "version": 1 }
}
```

Only an **allowlist of 16 event types** is ever forwarded — everything else
(text/reasoning deltas, usage counters, PTY/shell noise…) is dropped at the
listener (`dropped_unmapped` counter), before any spool write:

| OpenCode event                   | Observatory kind    | Notes |
|----------------------------------|---------------------|-------|
| `session.created`                | `session.started`   | session title deliberately **not** stored (free text) |
| `session.step.started`           | `turn.started`      | summary carries sanitized `agent` + `model` id |
| `session.execution.started`      | `turn.started`      | no agent/model fields on the wire |
| `session.tool.input.started`     | *(not published)*   | consumed only to resolve the tool name by part id |
| `session.tool.called`            | `tool.requested`    | summary built from allowlisted input keys |
| `session.tool.success`           | `tool.completed`    | reuses the sanitized summary captured at call time |
| `session.tool.failed`            | `tool.failed`       | same |
| `session.skill.activated`        | `skill.activated`   | *verified explicit skill usage*; name required |
| `permission.asked`               | `agent.notification`| action=`permission-requested`; **never** interpreted as an approval |
| `permission.replied`             | `agent.notification`| action=`permission-replied` |
| `session.idle`                   | `turn.completed`    | outcome=`idle` |
| `session.execution.succeeded`    | `turn.completed`    | outcome=`succeeded` |
| `session.execution.failed`       | `turn.completed`    | outcome=`failed` |
| `session.execution.interrupted`  | `turn.completed`    | outcome=`interrupted` |
| `session.archived`               | `session.ended`     | |
| `session.deleted`                | `session.ended`     | uses the session id even without `sessionID` |

The OpenAPI schema (`GET /openapi.json`) exposes 94 event types and a
`?types=` filter parameter on `/api/event`; the filter is verified to exist
but deliberately unused (client-side allowlisting keeps behavior independent
of server filtering semantics). `V2EventEncoded` is opaque in the schema, so
wire shapes were verified from a live capture instead of the spec.

## Deliberately dropped signals

Metadata-first rules (also in `docs/privacy.md`) applied to this source:

- **Session titles** are not mapped (free text, may contain prompt content).
- **Text/reasoning/tool-input deltas** (`session.text.delta`,
  `session.reasoning.delta`, `session.tool.input.ended` `text`, …) — arbitrary
  model output; never persisted.
- **Token usage** (`session.usage.updated`) — usage counters are forbidden as
  intensity inputs (AGENTS.md §9); never persisted.
- **Tool outputs** (`content` in `session.tool.success`) — discarded.
- **Unlisted tool-input keys** (`workdir`, `timeout`, `description`, …) —
  dropped; only tool-name, target-ish paths, and the coarse command category
  survive sanitization.
- **Paths are made project-relative** using `location.directory` as the
  project root; absolute paths outside the project collapse to their basename
  (no usernames, no home-directory paths).

## Sanitization summary

- Shell commands are reduced to a coarse **category token** only
  (`pytest`, `git`, `container-cli`, `schema-migration`, `lint-format`, …);
  unmatched commands are dropped entirely. The original text never reaches
  the spool.
- Verified live on the running project: ingested summaries contained only
  `{tool, project}`, `{tool, route}`-level keys; a sweep for `/home/` and the
  username over every persisted summary returned zero hits.

## Known limitations (observed, not guessed)

- **No native "session end" on normal exit** — OpenCode does not emit an end
  event when a session is merely left/idle; only `session.archived` /
  `session.deleted` map to `session.ended`. Sessions stay listed as
  `turn_finished`/`unknown` instead of `ended`.
- **Bash-command failure ≠ tool failure.** A non-zero exit inside the shell
  tool still terminates as `tool.completed` (the tool itself worked), so the
  dashboard's debugging region — driven by real `tool.failed` events — does
  not light up for ordinary command failures. It appears exactly ≥2 true tool
  failures (e.g. malformed invocations) within 10 minutes.
- **Tool names must be recovered from a side event**: `session.tool.called`
  carries the input but not the tool name; the listener joins it with
  `session.tool.input.started` via the part id (256-entry bounded cache).
  If the input-started event is missed under extreme lag, the summary keeps
  `tool` empty rather than guessing.
- **No prompt.submitted kind** — OpenCode has no distinct user-prompt hook in
  the verified set; turn starts are `turn.started` (from
  `session.step.started` / `session.execution.started`).
- Events lost while the listener is offline (or OpenCode was closed) are
  simply absent: like every observatory source, the map shows observed
  evidence only; it never fabricates coverage for gaps.

## Running it

```bash
# terminal 1: backend (any port), serving the built UI in production mode
OBSERVATORY_ENV=production OBSERVATORY_PORT=8041 ./brain/bin/uvicorn \
  backend.app.main:app --host 127.0.0.1 --port 8041 --log-level warning

# terminal 2: collector (spool → backend, same data dir)
OBSERVATORY_DATA_DIR=~/.local/share/agent-brain-observatory \
  ./brain/bin/observatory --backend http://127.0.0.1:8041 collector

# terminal 3: the OpenCode listener (same data dir)
OBSERVATORY_DATA_DIR=~/.local/share/agent-brain-observatory \
  ./brain/bin/observatory opencode-listen
```

`doctor` still verifies local diagnostics. Bounded capture (useful for a
smoke test) exists too: `observatory opencode-listen --seconds 5`.

## Test provenance

- `collector/tests/test_opencode_listener.py` — 13 tests on synthetic
  shape-only fixtures (mapping, sanitization, discovery, live SSE against a
  real HTTP server, spool-outage resilience).
- Live acceptance (this repo, 2026-10-30/31): real tool calls from a running
  OpenCode session ingested end-to-end; summaries verified sanitized
  (project-relative, no usernames, no command text); expertise regions lit
  for `code_exploration` and `testing` through the public API. No real
  transcript ever entered fixtures or the repo.
