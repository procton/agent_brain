"""Metadata-first sanitization.

The capture path extracts ONLY allowlisted fields from any source payload:
- allowlisted top-level keys (`tool_name`, `tool_input` allowlist, session ids...)
- project-relative path strings, truncated
- nothing else is ever written

Unknown fields are dropped rather than best-effort redacted (allowlist-based
extraction beats pattern-based redaction). This module performs no network or
filesystem I/O of its own.
"""

from __future__ import annotations

from typing import Any

MAX_VALUE_LENGTH = 200
MAX_SUMMARY_KEYS = 8

# Fields admitted into `summary` from tool inputs. Everything else in a tool
# input (prompts, command text, file contents, output) is discarded here.
TOOL_INPUT_ALLOWLIST = {
    "file_path",
    "notebook_path",
    "path",
    "directory",
    "command",
    "description",
    "pattern",
    "command_name",
}

# Values containing command-substitution or newlines are dropped entirely:
# command-like content is never stored verbatim.
_DISALLOWED_VALUE_SNIPPETS = ("$((", "`", "\n")


def sanitize_string(value: Any, *, max_length: int = MAX_VALUE_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:max_length]


# Summary vocabulary remapping: tool-input keys (first match wins).
_TARGET_KEYS = ("file_path", "notebook_path", "path")


def sanitize_tool_input(tool_input: Any) -> dict[str, str]:
    """Keep only allowlisted metadata keys about a tool invocation.

    Any value that looks like unrestricted command text or script injection is
    dropped; a shell command is reduced to a coarse approved category.
    """
    if not isinstance(tool_input, dict):
        return {}
    sanitized: dict[str, str] = {}
    target = None
    for key, value in tool_input.items():
        if key == "command":
            cleaned = sanitize_string(value)
            token = sanitized_command_signature(cleaned.lower()) if cleaned else None
            if token:
                sanitized["command"] = token
            continue
        if key == "description":
            # Set at the payload level; dropped from tool_input summaries.
            continue
        cleaned = sanitize_string(value)
        if cleaned is None:
            continue
        if any(snippet in cleaned for snippet in _DISALLOWED_VALUE_SNIPPETS):
            continue  # command-like content is never stored verbatim
        if key not in TOOL_INPUT_ALLOWLIST:
            continue
        if key in _TARGET_KEYS and target is None:
            target = cleaned
            continue
        if key not in sanitized:  # other allowlisted metadata
            sanitized[key] = cleaned
    if target:
        sanitized["target"] = target
    return sanitized


def sanitized_command_signature(command: str) -> str | None:
    """Map a shell command onto a coarse allowlisted category.

    Original command text is discarded; only the category name survives.
    """
    if command.startswith(("pytest ", "pytest")):
        return "pytest"
    if command.startswith("npm test") or command.startswith("npm run"):
        return "npm-script"
    if command.startswith(("ruff ", "eslint", "prettier")):
        return "lint-format"
    if command.startswith(("docker ", "docker-compose", "podman")):
        return "container-cli"
    if command.startswith(("alembic", "prisma", "flyway", "migrate")):
        return "schema-migration"
    if command.startswith(("git ",)):
        return "git"
    if command.startswith(("python ", "python3 ", "pip ", "uv ")):
        return "python"
    if command.startswith(("node ", "npx ", "deno ")):
        return "javascript-runtime"
    return None


def make_summary_from_payload(
    payload: dict[str, Any],
    *,
    extra_fields: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the sanitized `summary` dict from arbitrary source payloads.

    Recognized, allowlisted fields (already used by our scaffolding):
    - `tool_name`, `tool_input`, `description`
    - `cwd_project_relative` when caller supplied it
    `extra_fields` must already be sanitized strings.
    """
    summary: dict[str, str] = {}
    if not isinstance(payload, dict):
        return summary
    tool_name = sanitize_string(payload.get("tool_name"), max_length=64)
    if tool_name:
        summary["tool"] = tool_name
    description = sanitize_string(payload.get("description"))
    if description:
        summary["description"] = description
    nested = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    # Some sources emit flat tool fields; respect the allowlist there too.
    flat = {key: payload[key] for key in TOOL_INPUT_ALLOWLIST if key in payload}
    summary.update(sanitize_tool_input({**flat, **nested}))
    if extra_fields:
        for key, value in extra_fields.items():
            cleaned = sanitize_string(value)
            if cleaned:
                summary[key] = cleaned
    # Prevent summary explosion: cap the number of keys.
    summary = dict(sorted(summary.items())[:MAX_SUMMARY_KEYS])
    return summary
