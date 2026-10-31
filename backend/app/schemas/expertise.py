"""Response models for the expertise/skills snapshot endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EvidenceItem(BaseModel):
    """One evidence pointer backing an expertise label."""

    model_config = ConfigDict(extra="forbid")

    event_id: str | None = None
    cursor: int | None = None
    kind: str | None = None
    ts: str | None = None
    tool: str | None = None
    target: str | None = None
    command: str | None = None
    basis: str  # observed | inferred (observed only for explicit skill usage)
    rule_id: str
    confidence: str  # low | medium | high (qualitative only)


class RegionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    state: str  # active | fading | idle | inactive
    intensity: float
    evidence: list[EvidenceItem]
    evidence_count: int


class SkillRow(BaseModel):
    """An explicitly verified skill activation (never inferred)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    first_activated_at: str | None = None
    last_activated_at: str | None = None
    activation_count: int
    evidence_event_ids: list[str]
    recent: bool


class ExpertiseSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    session_id: str
    source: str
    generated_at: str
    regions: list[RegionRow]
    skills: list[SkillRow]
    # Honesty fields: the last event seen (any age) and how stale it is on the
    # backend clock. `stale` says "no events received lately"; it never claims
    # anything about agent activity between events.
    last_event_at: str | None = None
    stale_seconds: int | None = None
    stale: bool = False
    config: dict[str, float | int]
    notes: str
