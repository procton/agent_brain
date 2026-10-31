"""Expertise/skills snapshot endpoint.

`GET /api/sessions/{id}/expertise` returns the current region map: intensity,
activation state, evidence pointers, and verified skill activations for that
session. Computed on read from persisted, classified events — the decay clock
is the backend clock, so all connected browsers agree on the map.

Region intensity is recent observed activity (documented decay), NOT effort,
proficiency, or model-internal anything. See classification/engine.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from backend.app.classification import ExpertiseConfig, build_snapshot
from backend.app.database.models import Event
from backend.app.database.models import Session as SessionRow
from backend.app.schemas.expertise import ExpertiseSnapshot

router = APIRouter()

# Evidence window underlying each snapshot (bounded query; reply data only).
EXPERTISE_EVENT_WINDOW = 500


@router.get("/sessions/{session_id}/expertise")
async def session_expertise(request: Request, session_id: str) -> ExpertiseSnapshot:
    from backend.app.api.sessions import require_dashboard

    require_dashboard(request)

    async with request.app.state.sessions() as db:
        session_row = (
            await db.execute(select(SessionRow).where(SessionRow.id == session_id))
        ).scalar_one_or_none()
        if session_row is None:
            raise HTTPException(status_code=404, detail="session not found")

        rows = (
            await db.execute(
                select(
                    Event.event_id,
                    Event.cursor,
                    Event.kind,
                    Event.occurred_at,
                    Event.received_at,
                    Event.summary,
                )
                .where(Event.session_id == session_row.id)
                .order_by(Event.cursor.desc())
                .limit(EXPERTISE_EVENT_WINDOW)
            )
        ).all()

    events = [
        {
            "event_id": row.event_id,
            "cursor": row.cursor,
            "kind": row.kind,
            "occurred_at": row.occurred_at,
            "received_at": row.received_at,
            "summary": dict(row.summary or {}),
        }
        for row in rows
    ]
    snapshot = build_snapshot(
        events,
        config=ExpertiseConfig.from_settings(request.app.state.settings),
        now=datetime.now(UTC),
    )
    return ExpertiseSnapshot(
        session_id=session_row.id,
        source=session_row.source,
        generated_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
        **snapshot,
    )
