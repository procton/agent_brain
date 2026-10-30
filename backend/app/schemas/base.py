"""Event kinds and session states shared by the schema layers.

Names follow the AGENT.md event model. The source layer (collector -> backend)
and the normalized layer (backend -> browser) both use this vocabulary, so the
naming stays source-neutral everywhere.
"""

from __future__ import annotations

from typing import Literal

EventKind = Literal[
    "session.started",
    "prompt.submitted",
    "tool.requested",
    "tool.completed",
    "tool.failed",
    "subagent.started",
    "subagent.completed",
    "agent.notification",
    "turn.completed",
    "session.ended",
]

SessionState = Literal["unknown", "turn_active", "turn_finished", "ended"]

EVENT_KINDS: frozenset[str] = frozenset(EventKind.__args__)  # type: ignore[attr-defined]

SCHEMA_VERSION = 1

# Conservative state transitions derived only from event kinds actually seen.
SESSION_STATE_BY_KIND: dict[str, str] = {
    "session.started": "unknown",
    "prompt.submitted": "turn_active",
    "tool.requested": "turn_active",
    "tool.completed": "turn_active",
    "tool.failed": "turn_active",
    "subagent.started": "turn_active",
    "subagent.completed": "turn_active",
    "agent.notification": "turn_active",
    "turn.completed": "turn_finished",
    "session.ended": "ended",
}


def should_update_state(current: str, incoming: str) -> bool:
    """Conservative session-state updates.

    - An ended session stays ended.
    - `unknown` never downgrades a more specific state.
    - A new prompt re-activates a finished turn (a subsequent agent turn),
      which is directly evidenced by the event itself.
    """
    if current == "ended":
        return False
    if incoming == "unknown":
        return False
    if current == incoming:
        return False
    return True
