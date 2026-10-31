"""Mapping stored rows to dashboard view models.

`is_synthetic` marks sessions whose `source` is the explicitly synthetic
fixture source (`synthetic`) so the dashboard can label demo data honestly.
"""

from __future__ import annotations

from backend.app.database.models import Event, Session
from backend.app.schemas.normalized import NormalizedEvent, SessionView

SYNTHETIC_SOURCE = "synthetic"


def is_synthetic_source(source: str) -> bool:
    return source == SYNTHETIC_SOURCE


def to_session_view(row: Session) -> SessionView:
    return SessionView(
        id=row.id,
        source=row.source,
        source_session_id=row.source_session_id,
        machine_id=row.machine_id,
        is_synthetic=row.is_synthetic,
        project_label=row.project_label,
        display_title=row.display_title,
        state=row.state,
        event_count=row.event_count,
        first_event_at=row.first_event_at,
        last_activity_at=row.last_activity_at,
        latest_cursor=row.latest_cursor,
    )


def to_normalized_event(row: Event) -> NormalizedEvent:
    return NormalizedEvent(
        schema_version=1,
        event_id=row.event_id,
        cursor=row.cursor,
        machine_id=row.machine_id,
        session_id=row.session_id,
        source=row.source,
        source_event=row.source_event,
        kind=row.kind,
        occurred_at=row.occurred_at,
        received_at=row.received_at,
        correlation=dict(row.correlation or {}),
        summary=dict(row.summary or {}),
        expertise=list(row.expertise) if row.expertise is not None else None,
    )
