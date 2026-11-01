"""Knowhow axis: which technologies observed actions actually imply.

The second classification axis (orthogonal to the fixed expertise regions):
per-event technology tags computed at ingest time from already-sanitized,
allowlisted metadata only (AGENTS.md §9/§12):

- file extensions / path segments / filenames in `target`,
- the coarse command-category token produced by the capture path
  (original command text never reaches this module),
- an explicit skill activation ONLY when the verified skill name exactly
  matches this vocabulary (`basis: verified`).

Honesty rules, same spirit as the region rules:
- a tag says "technology seen in recent observed activity" — it never measures
  proficiency, effort, or paradigm use (a list of extensions cannot say
  "object oriented"; nothing here can);
- unknown/ambiguous evidence yields NO tag;
- `lint-format` intentionally maps to nothing (ruff/py/eslint/prettier are
  indistinguishable in the coarse token).

Row shape: {name, basis, rule_id, confidence, evidence_event_id}.
"""

from __future__ import annotations

from backend.app.schemas.base import EventKind

VOCABULARY: tuple[str, ...] = (
    "python",
    "javascript",
    "typescript",
    "go",
    "rust",
    "c-family",
    "java",
    "ruby",
    "php",
    "sql",
    "containers",
    "git",
    "css",
    "html",
)

_NAME = set(VOCABULARY)

KNOWNHOW_KINDS = ("tool.requested", "tool.completed", "tool.failed")
SKILL_EVENT_KIND: EventKind = "skill.activated"

_EXTENSIONS: dict[str, frozenset[str]] = {
    "python": frozenset({".py", ".pyi"}),
    "javascript": frozenset({".js", ".jsx", ".mjs", ".cjs"}),
    "typescript": frozenset({".ts", ".tsx", ".mts", ".cts", ".d.ts"}),
    "go": frozenset({".go"}),
    "rust": frozenset({".rs"}),
    "c-family": frozenset({".c", ".h", ".cpp", ".hpp", ".cc", ".cs"}),
    "java": frozenset({".java"}),
    "ruby": frozenset({".rb"}),
    "php": frozenset({".php"}),
    "sql": frozenset({".sql"}),
    "css": frozenset({".css", ".scss", ".sass", ".less"}),
    "html": frozenset({".html", ".htm"}),
}

# Filenames that say "containers" regardless of extension (Dockerfile: none).
_BASENAMES: dict[str, str] = {
    "dockerfile": "containers",
    "compose.yml": "containers",
    "compose.yaml": "containers",
}

# Path segments implying a technology. Deliberately tiny: "migrations"
# usually implies a database schema but not always — hence low confidence.
_SEGMENTS: dict[str, str] = {"migrations": "sql"}

# Capture-path command tokens -> technology. Coarse on purpose: the token is
# an ecosystem marker, and the confidence leaks that coarseness.
_COMMAND_TOKENS: dict[str, tuple[str, str, str]] = {
    # token: (knowhow, rule_id, confidence)
    "python": ("python", "python-command", "medium"),
    "pytest": ("python", "pytest-command", "high"),
    "javascript-runtime": ("javascript", "runtime-command", "medium"),
    "npm-script": ("javascript", "npm-command", "low"),
    "container-cli": ("containers", "container-command", "high"),
    "git": ("git", "git-command", "high"),
    "schema-migration": ("sql", "schema-migration-command", "low"),
}

_CONFIDENCE = {
    "tech-extension": "medium",
    "container-basename": "high",
    "migration-segment": "low",
    "python-command": "medium",
    "pytest-command": "high",
    "runtime-command": "medium",
    "npm-command": "low",
    "container-command": "high",
    "git-command": "high",
    "schema-migration-command": "low",
    "skill-name-verified": "high",
}


def _extensions(target: str) -> list[str]:
    """Suffixes of the target filename, longest first (`.spec.tsx`, `.tsx`)."""
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


def _tag(name: str, rule_id: str, evidence_event_id: str, *, basis: str = "observed") -> dict:
    return {
        "name": name,
        "basis": basis,
        "rule_id": rule_id,
        "confidence": _CONFIDENCE.get(rule_id, "low"),
        "evidence_event_id": evidence_event_id,
    }


def classify_knowhow(kind: str, summary: dict[str, str], *, evidence_event_id: str) -> list[dict]:
    """All knowhow tags supported by one event's sanitized metadata.

    Deduplicated by technology name; priority: skill-verified evidence wins
    over command tokens, over basenames, then extensions, then segments.
    """
    tag_by_name: dict[str, dict] = {}

    def put(tag: dict) -> None:
        tag_by_name.setdefault(tag["name"], tag)

    if kind == SKILL_EVENT_KIND:
        skill_name = (summary.get("skill") or "").strip().lower()
        if skill_name in _NAME:
            put(_tag(skill_name, "skill-name-verified", evidence_event_id, basis="verified"))
        return list(tag_by_name.values())

    if kind not in KNOWNHOW_KINDS:
        return []

    # Priority order (first match per tech wins): command tokens beat
    # container basenames, then migration segments, then plain extensions.
    category = summary.get("command")
    if category and category in _COMMAND_TOKENS:
        tech, rule_id, _ = _COMMAND_TOKENS[category]
        put(_tag(tech, rule_id, evidence_event_id))

    target = summary.get("target")
    if target:
        base = _basename(target)
        if base in _BASENAMES:
            put(_tag(_BASENAMES[base], "container-basename", evidence_event_id))
        matched_segment = _segments(target) & set(_SEGMENTS)
        for segment in matched_segment:
            put(_tag(_SEGMENTS[segment], "migration-segment", evidence_event_id))
        suffixes = set(_extensions(target))
        for tech, tech_extensions in _EXTENSIONS.items():
            if suffixes & tech_extensions:
                put(_tag(tech, "tech-extension", evidence_event_id))

    return list(tag_by_name.values())


__all__ = ["VOCABULARY", "classify_knowhow"]
