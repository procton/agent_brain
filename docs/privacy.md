# Privacy policy (MVP slice)

## Collection policy (what leaves the "capture" boundary)

Persisted event payloads contain **only**:

- tool names (e.g. `Read`, `Edit`, `Bash`)
- project-relative paths explicitly allowlisted from tool inputs
  (`file_path`, `path`, `notebook_path`, `directory`, `pattern`, …)
- a coarse allowlisted **command-category** token (`pytest`, `npm-script`,
  `container-cli`, `schema-migration`, …) — the original command text is
  discarded by the sanitizer, never stored
- identifiers the source itself supplied (session id, tool call id) and
  timestamps

Never collected or persisted anywhere in this slice (allowlist-based
extraction, not pattern redaction):

- full user prompts, transcripts, or model output
- file contents
- unrestricted shell command text
- environment variables, credentials, usernames, home-directory paths
  (project-relative paths are truncated at 200 chars)
- (OpenCode source) session titles (free text, may embed prompt content),
  text/reasoning/tool-input deltas, tool outputs, and token-usage counters

## OpenCode capture specifics

The OpenCode listener (`collector/opencode_listener.py`) subscribes read-only
to the local background service SSE stream and applies the same allowlist
discipline upstream of the spool (`docs/opencode-integration.md` has the full
verified mapping):

- exactly 16 wire event types are forwarded; everything else — including all
  deltas and usage events — is dropped before any file is written;
- `~/.config/opencode/service.json` is read only to obtain the loopback
  service password, which stays in process memory (never printed, logged, or
  persisted);
- targets and paths are made **project-relative using the directory OpenCode
  itself reports** (`location.directory`); absolute paths outside the project
  collapse to their basename;
- tool failures are reported as such — a failed *shell command* is metadata
  (a coarse category or nothing); the original text never survives.

Absent/unknown payload fields are dropped, never guessed. The demo publisher
is explicitly synthetic: `fixtures/synthetic/demo_session.json` contains no
captured data whatsoever.

## Where data lives

| Item | Location (default) | Permissions |
|---|---|---|
| SQLite database | `~/.local/share/agent-brain-observatory/observatory.db` (WAL) | user |
| Ingest credential | …/collector_credential | 0600 |
| Dashboard access code | …/dashboard_code | 0600 |
| Spool (pending/quarantine) | …/spool (or `OBSERVATORY_SPOOL_DIR`) | user |
| Diagnostics log | …/spool/diagnostics.log | user |
| (OpenCode listener) | reads `~/.config/opencode/service.json` only, in memory | no writes |

Runtime data is never written inside the repository. Deleting the data
directory (backend stopped) deletes all captured state:

```bash
rm -r ~/.local/share/agent-brain-observatory
```

## Network exposure

- Backend binds `127.0.0.1` by default. Nothing listens beyond loopback.
- Ingestion is authenticated with the local credential; foreign-origin
  browser requests are rejected even with the token.
- Dashboard access requires the access code (POST body; never a URL) in
  exchange for an HttpOnly, SameSite=Strict cookie. Origins are validated
  against an explicit allowlist; permissive CORS is never enabled.
- The capture path (spool publication) performs **zero network I/O**.
- The collector talks only to `http://127.0.0.1:8000` by default.

## Residual risks (honesty section)

1. **Loopback binding is not a security boundary.** Any process or user with
   your OS account can read the DB/credential files. On multi-user machines,
   use an OS-level boundary, run with a dedicated user, or accept the product
   is designed for a workstation, not a shared server.
2. **The dashboard access code gates browser UI, not local files.** If a
   hostile local process reads `collector_credential`, it can ingest forged
   events (persisted synthetic badge won't apply — forged sessions show as
   non-synthetic). Provenance hardening is a future milestone.
3. **In-memory browser sessions** vanish on backend restart (privacy-positive,
   UX-negative).
4. **Unbounded WS queue**: a dashboard that stops reading could accumulate
   memory locally (no other process is harmed); a future protocol version
   will close-with-resync-hint instead.
5. **Diagnostics keep counters only** (e.g. "dropped 12 oldest"), never
   payloads; if you publish a bug report, sanity-check the diagnostics file
   first.
6. **The demo page and synthetic fixtures are clearly labeled** by contract
   (`is_synthetic`); any labeling regression would be a bug — flag it.
