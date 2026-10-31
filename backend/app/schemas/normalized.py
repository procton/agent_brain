"""Layer 2: normalized events persisted by the backend and shown in the UI.

`NormalizedEvent` is what the backend stores and what the browser receives.
`cursor` is a server-assigned, globally increasing sequence number used for
replay ordering. `event_id` stays identical to the sanitized source event so
deduplication and collector retries are safe.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.app.schemas.base import SCHEMA_VERSION as SOURCE_SCHEMA_VERSION

NormalizedSchemaVersion = Literal[1]


class NormalizedEvent(BaseModel):
    """A normalized, persisted event as exposed to the dashboard."""

    model_config = ConfigDict(extra="forbid")

    schema_version: NormalizedSchemaVersion = SOURCE_SCHEMA_VERSION
    event_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    cursor: int = Field(..., ge=1)
    machine_id: str
    session_id: str
    source: str
    source_event: str
    kind: str
    occurred_at: str | None = None
    received_at: str
    correlation: dict[str, str | None] = Field(default_factory=dict)
    summary: dict[str, str] = Field(default_factory=dict)
    # Deterministic expertise labels computed at ingest (see classification/):
    # [{label, basis, rule_id, confidence, evidence_event_id}]. None for legacy
    # rows; the schemas stay additive (still schema_version 1).
    expertise: list[dict] | None = None


class SessionView(BaseModel):
    """Dashboard view of a session. States stay conservative (see base.py)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    source_session_id: str
    machine_id: str
    is_synthetic: bool
    project_label: str | None = None
    display_title: str
    state: str
    event_count: int
    first_event_at: str | None = None
    last_activity_at: str | None = None
    latest_cursor: int = 0


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionView]
    generated_at: str


class SnapshotResponse(BaseModel):
    """Session view plus the most recent events, with the cursor to resume from.

    `events` covers the latest `window` events; earlier history must be fetched
    through the paginated history endpoint when needed.
    """

    model_config = ConfigDict(extra="forbid")

    session: SessionView
    events: list[NormalizedEvent]
    latest_cursor: int
    first_loaded_cursor: int | None
    has_older_events: bool


class EventsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[NormalizedEvent]
    has_more: bool
    next_after: int | None


class IngestReport(BaseModel):
    """Per-event, per-batch acceptance report.

    The collector deletes spool files only for events confirmed here, so
    duplicates and invalid events cannot cause data loss.
    """

    model_config = ConfigDict(extra="forbid")

    accepted: list[str]
    duplicates: list[str] = []
    rejected: list[IngestRejection] = []


class IngestRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    event_id: str | None
    reason: str
