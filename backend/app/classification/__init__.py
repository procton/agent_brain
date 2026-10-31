"""Deterministic expertise classification (AGENTS.md §9).

No LLM, no hidden-state inference: labels derive from sanitized evidence that
was actually observed (tool names, target extensions, allowlisted command
categories, outcomes). Every label explains its evidence and marks whether it
is an explicitly observed skill usage (`basis="observed"` — only wired for the
OpenCode `session.skill.activated` signal) or a rule-based inference
(`basis="inferred"`).
"""

from backend.app.classification.engine import ExpertiseConfig, build_snapshot
from backend.app.classification.rules import REGIONS, classify_event

__all__ = ["REGIONS", "ExpertiseConfig", "build_snapshot", "classify_event"]
