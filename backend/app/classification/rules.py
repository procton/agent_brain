"""Per-event expertise rules.

Pure functions over sanitized event attributes:
- `kind` (one of the shared event kinds),
- `summary` (sanitized metadata: `tool`, `target`, `command`, `project`).

Interpretation rules per AGENTS.md §9:
- reading a file supports code exploration (and may support frontend if the
  extension is frontend-flavoured) — it does not prove React expertise;
- a recognized test command supports testing; a migration path supports
  database/schema activity; a Dockerfile target supports infrastructure;
- a failed command alone DOES NOT prove debugging — debugging requires
  repeated failures and is computed by the snapshot engine (see engine.py),
  never stored per-event.

Labels always carry: label, basis, rule_id, confidence, evidence_event_id.
Absence of evidence yields no label (never a guessed region).
"""

from __future__ import annotations

from backend.app.schemas.base import EVENT_KINDS, EventKind  # noqa: F401  (EVENT_KINDS: discoverable kind vocabulary)

# Fixed taxonomy for the skills/abilities map (documented, source-neutral).
REGIONS: tuple[str, ...] = (
    "code_exploration",
    "frontend",
    "backend",
    "testing",
    "database",
    "infrastructure",
    "debugging",
)

REGION_LABELS: dict[str, str] = {
    "code_exploration": "Code exploration",
    "frontend": "Frontend",
    "backend": "Backend",
    "testing": "Testing",
    "database": "Database",
    "infrastructure": "Infrastructure",
    "debugging": "Debugging",
}

# Tools that evidence browsing/reading code (case-insensitive match).
_EXPLORATION_TOOLS = frozenset({"read", "glob", "grep", "view", "cat", "ls", "list"})

_FRONTEND_EXTENSIONS = frozenset({".tsx", ".jsx", ".css", ".scss", ".html", ".vue", ".svelte"})
_FRONTEND_DIRS = frozenset({"components", "ui"})

_BACKEND_EXTENSIONS = frozenset({".py", ".go", ".rs", ".java", ".rb", ".php", ".cs", ".kt", ".c", ".h"})

_TESTING_EXTENSIONS = frozenset(
    {".spec.ts", ".spec.tsx", ".spec.js", ".spec.mjs", ".test.ts", ".test.tsx", ".test.js"}
)
_TESTING_SEGMENTS = frozenset({"tests", "test", "__tests__", "spec"})

_DATABASE_EXTENSIONS = frozenset({".sql", ".prisma"})
_DATABASE_SEGMENTS = frozenset({"migrations", "migrate", "migration"})

_INFRA_BASENAMES = frozenset({"dockerfile", "compose.yml", "compose.yaml"})
_INFRA_SEGMENTS = frozenset({".github", "workflows", "infra", "infrastructure", "deploy", "ci"})

_CONFIDENCE = {
    "read-tools": "medium",
    "target-frontend-ext": "medium",
    "target-frontend-dir": "low",
    "target-backend-ext": "medium",
    "command-python-category": "low",
    "target-test-path": "high",
    "command-test-signature": "high",
    "target-db-path": "high",
    "command-schema-migration": "high",
    "target-infra-name": "high",
    "target-infra-dir": "medium",
    "command-container-cli": "high",
}


def _extensions(target: str) -> list[str]:
    """Suffixes of the target filename, longest first (`.spec.tsx` and `.tsx`)."""
    lowered = target.rsplit("/", 1)[-1].lower()
    suffixes: list[str] = []
    while True:
        dot = lowered.find(".")
        if dot == -1:
            break
        suffix = lowered[dot:]
        lowered = lowered[:dot]
        suffixes.append(suffix)
    return suffixes


def _segments(target: str) -> set[str]:
    name_part = target.rsplit("/", 1)[0]
    return {segment.lower() for segment in name_part.split("/") if segment}


def _basename(target: str) -> str:
    return target.rsplit("/", 1)[-1].lower()


def _label(region: str, rule_id: str, evidence_event_id: str) -> dict:
    return {
        "label": region,
        "basis": "inferred",
        "rule_id": rule_id,
        "confidence": _CONFIDENCE.get(rule_id, "low"),
        "evidence_event_id": evidence_event_id,
    }


def _target_region_labels(kind: EventKind, summary: dict[str, str], evidence_id: str) -> list[dict]:
    """Region labels derived from an allowlisted target path (file edits, reads…)."""
    labels: list[dict] = []
    target = summary.get("target")
    if not target:
        return labels
    suffixes = _extensions(target)
    segments = _segments(target)
    basename = _basename(target)

    if any(ext in _TESTING_EXTENSIONS for ext in suffixes) or segments & _TESTING_SEGMENTS:
        labels.append(_label("testing", "target-test-path", evidence_id))
    elif any(ext in _DATABASE_EXTENSIONS for ext in suffixes) or segments & _DATABASE_SEGMENTS:
        labels.append(_label("database", "target-db-path", evidence_id))
    elif basename in _INFRA_BASENAMES or segments & _INFRA_SEGMENTS:
        labels.append(_label("infrastructure", "target-infra-name", evidence_id))
    elif any(ext in _FRONTEND_EXTENSIONS for ext in suffixes) or segments & _FRONTEND_DIRS:
        rule = (
            "target-frontend-ext"
            if any(ext in _FRONTEND_EXTENSIONS for ext in suffixes)
            else "target-frontend-dir"
        )
        labels.append(_label("frontend", rule, evidence_id))
    elif any(ext in _BACKEND_EXTENSIONS for ext in suffixes):
        labels.append(_label("backend", "target-backend-ext", evidence_id))
    return labels


def _command_region_labels(summary: dict[str, str], evidence_id: str) -> list[dict]:
    """Region labels derived from the allowlisted, coarse command category.

    The original command text never reaches this module; only its signature
    (`summary["command"]`) that the capture-path sanitizer produced.
    """
    labels: list[dict] = []
    category = summary.get("command")
    if not category:
        return labels
    if category in ("pytest", "npm-script"):
        labels.append(_label("testing", "command-test-signature", evidence_id))
    elif category == "schema-migration":
        labels.append(_label("database", "command-schema-migration", evidence_id))
    elif category == "container-cli":
        labels.append(_label("infrastructure", "command-container-cli", evidence_id))
    elif category == "python":
        labels.append(_label("backend", "command-python-category", evidence_id))
    return labels


def classify_event(kind: str, summary: dict[str, str], *, evidence_event_id: str) -> list[dict]:
    """All region labels supported by one event's sanitized metadata."""
    labels: list[dict] = []

    tool = (summary.get("tool") or "").lower()
    if tool in _EXPLORATION_TOOLS:
        labels.append(_label("code_exploration", "read-tools", evidence_event_id))

    # Editing/running tools carry targets; read tools usually do too (file_path).
    if kind in ("tool.requested", "tool.completed", "tool.failed"):
        labels.extend(_target_region_labels(kind, summary, evidence_event_id))

    if kind in ("tool.requested", "tool.completed", "tool.failed"):
        labels.extend(_command_region_labels(summary, evidence_event_id))

    return labels


__all__ = ["REGIONS", "REGION_LABELS", "classify_event"]
