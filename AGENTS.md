# AGENT.md — Claude Code Activity Observatory MVP

## 1. Project purpose

Build a web application that visualizes the observable activity of Claude Code while users continue working in their existing terminals.

The application should feel like a live representation of an agent’s “brain at work,” while clearly distinguishing actual telemetry from inferred expertise.

The MVP is a passive companion. It must not launch, control, approve actions for, or replace Claude Code.

### Primary user flow

1. The user installs the local collector and configures Claude Code hooks.
2. The user starts Claude Code normally in a terminal.
3. The user opens the dashboard in a browser.
4. The dashboard displays session activity, tool events, and inferred expertise in near real time.
5. The user continues working without interacting with the dashboard.

### Core principle

**The visualization must be evidence-backed, and the dashboard must never become a dependency of the coding workflow.**

---

## 2. MVP scope

### In scope

- Claude Code integration through lifecycle hooks.
- A lightweight Python hook receiver.
- A durable local event spool.
- A Python collector that forwards events to FastAPI.
- FastAPI backend with SQLite persistence.
- React frontend with a brain-inspired SVG expertise map.
- Session selection and live activity timeline.
- Evidence panels explaining expertise classifications.
- WebSocket updates and reconnect recovery.
- Metadata-first collection and local sanitization.
- Safe hook installation and removal.
- Automated tests and developer documentation.

### Out of scope

- Codex and OpenCode integrations.
- Remote/cloud deployment and multi-user accounts.
- Agent control, command execution, or approval handling.
- Access to hidden chain-of-thought or model internals.
- A second LLM for classification.
- Full transcript ingestion.
- File content or full tool-output collection.
- Automatic retrospective attachment to arbitrary running sessions.
- Comprehensive skill invocation detection.
- Mobile applications.
- Distributed backend deployment.

Keep internal event models source-neutral so other agents can be added later, but do not implement their adapters now.

---

## 3. Technology choices

### Backend and local integration

- Python 3.12 or newer.
- FastAPI.
- Pydantic for validation.
- SQLAlchemy with SQLite.
- Alembic for database migrations.
- HTTPX for collector-to-backend communication.
- pytest for tests.
- Ruff for linting and formatting.

### Frontend

- React.
- TypeScript.
- Vite.
- Custom SVG expertise visualization.
- Vitest and React Testing Library.
- Playwright for essential end-to-end coverage.

Use current compatible stable dependency versions at implementation time. Commit dependency lockfiles.

Do not add Redis, a message broker, Kubernetes, or a graph database.

Run the MVP backend as a single process. Multi-worker WebSocket coordination is outside scope.

---

## 4. Architecture

```text
Claude Code in the user's terminal
                 |
                 | lifecycle hook payload via stdin
                 v
        Python hook receiver
        - validate input size
        - sanitize metadata
        - atomically spool event
        - exit promptly
                 |
                 v
         Local event spool
                 |
                 v
        Python collector daemon
        - read queued events
        - deliver batches
        - retry with backoff
                 |
                 | authenticated local HTTP
                 v
           FastAPI backend
        - normalize events
        - classify expertise
        - persist in SQLite
        - broadcast updates
                 |
                 | same-origin WebSocket
                 v
          React dashboard
```

### Deployment model

Run the collector and backend on the same PC as Claude Code.

Bind the backend to loopback by default.

In production mode, serve the built frontend from FastAPI so the UI and API share an origin.

Allow a Vite development server through an explicit development-only origin allowlist.

---

## 5. Repository structure

Use this structure unless a clear implementation constraint requires a small adjustment:

```text
/
├── AGENT.md
├── README.md
├── pyproject.toml
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   ├── schemas/
│   │   ├── database/
│   │   ├── services/
│   │   ├── classification/
│   │   └── adapters/
│   │       └── claude_code.py
│   ├── migrations/
│   └── tests/
├── collector/
│   ├── hook_receiver.py
│   ├── daemon.py
│   ├── spool.py
│   ├── sanitization.py
│   ├── installer.py
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── sessions/
│   │   │   ├── expertise-map/
│   │   │   └── timeline/
│   │   └── types/
│   └── tests/
├── fixtures/
│   └── claude_code/
└── docs/
    ├── architecture.md
    ├── claude-code-integration.md
    ├── privacy.md
    └── development.md
```

Use platform-appropriate application data directories for the database, credentials, spool, and diagnostic logs. Do not store runtime data inside the repository.

---

## 6. Claude Code integration

### Verify before implementing

Consult current official Claude Code documentation before writing hook configuration or payload parsing.

Record in `docs/claude-code-integration.md`:

- Documentation references.
- Claude Code version tested.
- Supported hooks.
- Payload fields actually observed.
- Any platform limitations.
- Installation and restart requirements.

Do not invent payload fields or assume identifiers exist.

### Target hooks

Implement support for these hooks where documented and available in the tested version:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `SubagentStart`
- `SubagentStop`
- `Notification`
- `Stop`
- `SessionEnd`

If a hook is unavailable, document the limitation and degrade gracefully.

Preserve the distinction between:

- Tool requested and tool confirmed as executing.
- Tool success and tool failure.
- Agent turn finished and session ended.
- Collector connectivity and agent activity.

Do not interpret all notifications as approval requests.

### Hook receiver requirements

The hook receiver must:

- Read the hook JSON from stdin.
- Enforce a configurable payload-size limit.
- Extract only allowlisted metadata.
- Sanitize before writing to disk.
- Assign a unique event ID.
- Write one event per spool file.
- Use temporary-file-plus-atomic-rename publication.
- Produce no Claude-facing stdout.
- Never emit approval decisions or model instructions.
- Catch recoverable errors and exit successfully.
- Perform no network requests.
- Avoid expensive processing.

Sanitize before persistence: raw prompts, file contents, command output, and unrestricted tool inputs must not be written to the spool.

Failures should be logged locally using sanitized diagnostics.

### Installer requirements

Provide CLI commands equivalent to:

```text
observatory install --project <path>
observatory uninstall --project <path>
observatory collector
observatory doctor
```

The installer must:

- Prefer project-local opt-in configuration.
- Preserve existing settings and hooks.
- Be idempotent.
- Back up settings before modification.
- Avoid modifying tracked shared configuration by default.
- Correctly quote executable paths on supported platforms.
- Identify its own entries precisely.
- Remove only its own entries during uninstall.
- Explain that a fresh Claude Code session should be used for validation.

If existing configuration cannot be safely parsed or updated, stop and provide manual instructions rather than overwriting it.

---

## 7. Event model

Maintain three separate schema layers:

1. Sanitized source events written by the receiver.
2. Normalized backend events.
3. Frontend view models.

Version the source and normalized schemas.

A normalized event should include:

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "cursor": 123,
  "machine_id": "local-id",
  "session_id": "source-session-id",
  "source": "claude_code",
  "source_event": "PreToolUse",
  "occurred_at": null,
  "received_at": "ISO-8601 timestamp",
  "kind": "tool.requested",
  "correlation": {
    "tool_call_id": null,
    "agent_id": null,
    "parent_agent_id": null
  },
  "summary": {
    "tool": "Edit",
    "target": "src/components/Checkout.tsx"
  },
  "expertise": [
    {
      "label": "frontend",
      "basis": "inferred",
      "rule_id": "file-extension-tsx",
      "confidence": "medium",
      "evidence_event_id": "uuid"
    }
  ]
}
```

The example is an application schema, not a claim about Claude Code's native payload.

### Event kinds

Start with:

```text
session.started
prompt.submitted
tool.requested
tool.completed
tool.failed
subagent.started
subagent.completed
agent.notification
turn.completed
session.ended
```

### Event semantics

- Use source timestamps only when genuinely available.
- Otherwise leave `occurred_at` null and use `received_at`.
- Use server cursors for replay order.
- Populate correlation IDs only when source evidence supports them.
- Never fabricate subagent relationships.
- Deduplicate ingestion using `event_id`.
- Treat late and duplicate events safely.
- Do not infer a successful file change solely from an edit request.
- Do not guess sessions from working directory alone.

If a required session identifier is missing, record a sanitized integration diagnostic rather than attributing the event to an arbitrary session.

---

## 8. Persistence and delivery

### SQLite entities

At minimum:

- Machines.
- Sessions.
- Events.
- Classification results or classifications embedded in persisted events.

Create indexes for:

- Session and cursor.
- Event ID.
- Session last activity.

Persist an event before broadcasting it.

For synchronous database access, keep blocking work out of the async event loop.

### Collector behavior

- Use bounded batches.
- Retry temporary failures with exponential backoff and jitter.
- Delete spool files only after confirmed acceptance.
- Preserve event IDs across retries.
- Quarantine invalid files without logging sensitive contents.
- Support clean shutdown.
- Define configurable spool size and retention limits.
- Surface dropped-event or overflow conditions honestly.

Never block Claude Code because the spool is full. Fail open, record a sanitized diagnostic where possible, and make the telemetry gap visible.

### API

Implement:

```text
POST /api/events/batch
GET  /api/sessions
GET  /api/sessions/{id}/snapshot
GET  /api/sessions/{id}/events?after={cursor}
WS   /api/sessions/{id}/live
GET  /api/health
```

Use bounded pagination for event history.

Snapshot responses should contain the current session view and an associated cursor.

Design reconnect handling to avoid gaps between snapshot loading and live subscription. Use replay plus client-side deduplication, or an equivalent tested protocol.

Do not silently skip events when a live client falls behind.

---

## 9. Expertise classification

Use deterministic, configurable rules. Do not introduce an LLM.

Initial expertise regions:

- Code exploration.
- Frontend.
- Backend.
- Testing.
- Database.
- Infrastructure.
- Debugging.

Rules may use sanitized:

- Tool names.
- File extensions.
- Project-relative path patterns.
- Allowlisted command signatures.
- Event outcomes.

Do not retain unrestricted shell commands just to classify them. Extract approved command categories locally and discard the original command.

### Interpretation rules

- Reading a file supports code exploration.
- A `.tsx` target may support frontend/TypeScript-related activity.
- It does not prove React expertise.
- A recognized test command supports testing.
- A migration path may support database/schema activity.
- A Dockerfile target may support infrastructure activity.
- A failed command alone does not prove debugging.

Each classification must explain its evidence.

Use qualitative confidence values rather than unsupported numerical probabilities.

Keep the concepts separate:

- Observed action.
- Explicit skill usage.
- Inferred expertise.

Do not display explicit skill activation unless the adapter has verified evidence. Leaving this feature absent is preferable to inventing activations.

### Activity intensity

Compute region intensity from a documented combination of recent relevant events and supported outstanding actions.

Intensity means **recent observed activity**, not:

- Cognitive effort.
- Expertise proficiency.
- Attention inside the model.
- Token allocation.
- Confidence in the agent’s answer.

Make the decay function configurable and test it with a controlled clock.

---

## 10. Session state

Use conservative states such as:

```text
unknown
turn_active
turn_finished
ended
```

Track transport status separately:

```text
connected
disconnected
```

A collector heartbeat does not establish that Claude is generating a response.

Hooks do not guarantee continuous inference telemetry. Gaps between events must not be narrated as known thinking.

If tool completion is missing, show the action as unresolved rather than indefinitely claiming it is running.

On turn completion, session end, or stale telemetry, reconcile outstanding actions conservatively. Late completion events must still be accepted.

---

## 11. Frontend experience

### Main layout

- Header: session selector, project label, connection status.
- Main panel: brain-inspired SVG expertise map.
- Side panel: selected region or event evidence.
- Bottom panel: chronological activity timeline.

### Visualization behavior

- Pulse when a relevant event arrives.
- Highlight recent activity.
- Fade according to the configured decay function.
- Distinguish observed and inferred labels.
- Show unresolved activity explicitly.
- Show disconnected and empty states.
- Never fabricate activity during telemetry gaps.

### Accessibility

- Support keyboard selection.
- Provide text equivalents for visual activity.
- Do not communicate status through color alone.
- Respect reduced-motion preferences.
- Maintain readable contrast.
- Keep the timeline useful without animation.

### Useful empty state

Explain:

1. Install hooks.
2. Start a fresh Claude Code session.
3. Perform a tool-using task.
4. Run the diagnostic command if no events arrive.

Do not show fabricated live data in the normal application.

Provide a clearly labeled demo/replay mode backed by fixtures for development.

---

## 12. Security and privacy

Metadata-first collection is mandatory.

Do not collect by default:

- Full user prompts.
- Full shell commands.
- File contents.
- Tool output.
- Environment variables.
- Credentials.
- Full transcripts.

Use allowlist-based extraction rather than relying only on secret-pattern redaction.

Prefer project-relative paths. Avoid exposing usernames or home-directory paths in the UI and persisted events.

Additional requirements:

- Bind services to loopback by default.
- Authenticate collector ingestion with a generated local credential.
- Keep ingestion credentials out of frontend assets.
- Restrict configuration-file permissions where supported.
- Validate HTTP and WebSocket origins.
- Use an appropriate browser-session mechanism for dashboard access.
- Do not place credentials in URL query parameters.
- Render event text safely; never inject source-provided HTML.
- Enforce input size and batch limits.
- Document residual privacy risks.
- Provide local data deletion instructions.

Loopback binding alone is not a complete security boundary.

Do not enable permissive CORS to simplify development.

---

## 13. Testing requirements

### Unit tests

Cover:

- Sanitization.
- Unknown and missing payload fields.
- Payload-size limits.
- Event normalization.
- Classification rules.
- Activity decay.
- Session-state transitions.
- Idempotent settings installation/removal.

### Integration tests

Cover:

- Atomic spool publication.
- Concurrent hook receiver invocations.
- Backend downtime and retry.
- Duplicate ingestion.
- Late and out-of-order events.
- Database restart persistence.
- Authentication and origin rejection.
- WebSocket reconnect without event loss.
- Spool overflow behavior.
- Invalid-event quarantine.

### Frontend tests

Cover:

- Empty and disconnected states.
- Evidence display.
- Inferred-label badges.
- Event deduplication.
- Reduced-motion behavior.
- Session switching.

### End-to-end scenarios

Provide a fixture-driven automated scenario and a manual real-Claude scenario.

The real-Claude scenario should verify:

1. Start a terminal session.
2. Ask Claude to inspect a file.
3. Ask it to make a small change.
4. Ask it to run tests.
5. Confirm corresponding telemetry and classifications.
6. Stop the backend while continuing terminal work.
7. Restart the backend and recover queued events.
8. Refresh the browser and recover history.

Use synthetic fixtures initially. Add sanitized fixtures from a tested Claude Code version with provenance documented.

Do not claim a real integration was tested if only fixtures were used.

---

## 14. Implementation milestones

### Milestone 1 — Contracts and scaffold

- Create backend, collector, and frontend packages.
- Define versioned schemas.
- Document verified hook integration details.
- Add fixture-driven event ingestion.
- Establish linting and test commands.

### Milestone 2 — Durable local capture

- Implement sanitization and hook receiver.
- Implement atomic spool and collector retries.
- Implement safe installer, uninstaller, and diagnostics.
- Test backend-outage behavior.

### Milestone 3 — Backend and replay

- Implement SQLite models and migrations.
- Implement session/event APIs.
- Implement classification rules.
- Implement WebSocket delivery and reconnect recovery.

### Milestone 4 — Dashboard

- Implement session selector.
- Implement SVG expertise map.
- Implement timeline and evidence panel.
- Add honest state and connectivity indicators.

### Milestone 5 — Hardening

- Complete security and privacy checks.
- Complete automated and manual acceptance tests.
- Document setup, supported platforms, limitations, and data deletion.

At each milestone, prefer a working vertical slice over broad unfinished abstractions.

---

## 15. Definition of done

The MVP is complete when:

- Users continue using Claude Code in their terminals.
- Real hook events appear in the dashboard.
- Under normal local conditions, persisted events reach connected browsers within one second.
- Hook capture performs no network I/O.
- Backend failures do not interrupt terminal work.
- Queued events recover after restart.
- Browser reconnects recover missed events.
- Expertise labels expose their supporting evidence.
- No hidden-thinking claims appear in the UI.
- Sensitive content is excluded before spooling.
- Installation preserves existing user configuration.
- Uninstallation removes only application-owned entries.
- Tests, linting, and frontend builds pass.
- README documents exact setup and validation steps.

Document measured hook overhead rather than promising an unverified latency figure.

---

## 16. Instructions for the development agent

1. Read this file before making changes.
2. Inspect the repository before creating a new scaffold.
3. Verify current official documentation for hook integration details.
4. Keep the product passive and metadata-first.
5. Prefer simple, typed, testable modules.
6. Avoid premature multi-agent abstractions.
7. Never fabricate source telemetry or skill activations.
8. Keep raw sensitive payloads out of fixtures and logs.
9. Add tests alongside behavior changes.
10. Run relevant checks after each milestone.
11. Document unsupported behavior explicitly.
12. Ask before expanding scope to cloud access, agent control, or transcript collection.
13. Do not modify the developer’s Claude Code settings during tests; use temporary settings files.
14. End development updates with:
    - What changed.
    - What was tested.
    - Known limitations.
    - The next concrete step.

### First development task

Build the smallest end-to-end slice:

**synthetic sanitized event → durable spool → collector → FastAPI → SQLite → WebSocket → React timeline.**

Then connect verified Claude Code hooks, followed by expertise classification and the brain visualization.

opencode -s ses_e76665c34ffeVlam7zAPWfcNTF