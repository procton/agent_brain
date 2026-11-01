"""Deterministic expertise classification (AGENTS.md §9).

No LLM, no hidden-state inference: labels derive from sanitized evidence that
was actually observed (tool names, target extensions, allowlisted command
categories, outcomes), and every label carries its evidence. Bases in use:
regions are rule-based inference (`basis="inferred"`); knowhow tags are
metadata-observed (`basis="observed"`) or skill-name-verified
(`basis="verified"`, exact vocabulary match on the OpenCode
`session.skill.activated` signal); the snapshot's skills list holds verified
activations only.

Two axes exist:
- expertise REGIONS (wider competence areas, `rules.py`), and
- the KNOWHOW axis (which technology an action implies: `knowhow.py`, e.g.
  python/typescript/sql/git…), tagged per event and aggregated with the same
  decay in the snapshot.
"""

from backend.app.classification.engine import ExpertiseConfig, build_snapshot
from backend.app.classification.knowhow import VOCABULARY, classify_knowhow
from backend.app.classification.rules import REGIONS, classify_event

__all__ = [
    "REGIONS",
    "VOCABULARY",
    "ExpertiseConfig",
    "build_snapshot",
    "classify_event",
    "classify_knowhow",
]
