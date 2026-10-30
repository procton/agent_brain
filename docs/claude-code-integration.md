# Claude Code integration status

**Status: NOT IMPLEMENTED AND NOT CLAIMED.**

No Claude Code hooks were configured, installed, or tested in this slice —
that constraint was explicit for the first vertical slice. No claim of a
verified integration may be made based on the synthetic demo path alone.

## What exists today

- A **source-neutral event contract** (`backend/app/schemas/source.py` v1)
  sized to admit Claude Code hook payloads later.
- `collectors/sanitization.py` operates on generic hook-shaped payloads
  (`tool_name`, `tool_input`, `description`, …) and enforces the
  metadata-first allowlist. It is written to be reused by the future hook
  receiver, but no receiver binary exists yet.

## What the next milestone must do before any "tested" claim

Per AGENT.md §6, before wiring hooks we must:

1. Consult the **current official Claude Code hooks documentation** and
   record the exact version tested, supported hook events, and *observed*
   payload fields here (docs-live references, never invented fields).
2. Implement `collector/hook_receiver.py` reading hook JSON from stdin with a
   payload-size cap: sanitize → assign event id → atomic spool publish →
   exit promptly with no Claude-facing stdout and no network I/O.
3. Implement `collector/installer.py` (`observatory install --project …`,
   `uninstall`, `doctor`) that is idempotent, backs up settings, only edits
   project-local opt-in configuration, removes only its own entries, and
   stops safely rather than overwriting unparseable configuration.
4. Add sanitized fixtures captured from the *tested* Claude Code version and
   rerun the acceptance scenario (start a session, inspect a file, edit,
   run tests, verify telemetry; backend outage; browser refresh).
5. Only after (4): claim version-pinned integration (e.g. "tested with
   Claude Code vX on Linux").

## Known design intents already in place

- Distinguish requested vs executing vs failed tools through
  `tool.requested` / `tool.completed` / `tool.failed` kinds (a design test —
  `test_session_state_transitions_*` — pins conservative semantics).
- Sessions are attributed strictly by `(machine_id, source, source_session_id)`
  present in hook payloads; anything missing yields a sanitized diagnostics
  line, not an invented attribution.
- `SessionStart`, `Stop`, `SessionEnd`, `Notification`, `PreToolUse`,
  `PostToolUse`, `UserPromptSubmit`, subagent hooks all map onto the kinds in
  `schemas/base.py`; unmapped events are recorded, not dropped silently.
