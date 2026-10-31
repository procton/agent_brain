"""Ingestion: validate, deduplicate, persist, then broadcast.

Guarantees (per AGENT.md):
- Deduplicate ingestion using `event_id` — collector retries and late duplicate
  events are safe.
- Persist before broadcasting to the in-process hub.
- Broadcasts are serialized so cursors arrive in order on the wire.
- Sessions are upserted by (machine_id, source, source_session_id) identity; a
  missing session identifier can never be attributed to an arbitrary session.
- Session state changes are conservative and driven only by observed kinds.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from backend.app.classification.rules import classify_event
from backend.app.config import Settings
from backend.app.database.engine import SessionFactory
from backend.app.database.models import Event, Machine, utc_now_iso
from backend.app.database.models import Session as SessionRow
from backend.app.schemas.base import SESSION_STATE_BY_KIND, should_update_state
from backend.app.schemas.normalized import SessionView
from backend.app.schemas.source import EventBatch, SourceEvent
from backend.app.services.hub import Broadcast, BroadcastHub
from backend.app.services.views import (
    is_synthetic_source,
    to_normalized_event,
    to_session_view,
)


class IngestResult:
    def __init__(self) -> None:
        self.accepted: list[str] = []
        self.duplicates: list[str] = []
        self.last_event_row: Event | None = None
        self.last_session_row: SessionRow | None = None

    @property
    def accepted_any(self) -> bool:
        return bool(self.accepted)

    @property
    def session_view(self) -> SessionView | None:
        return to_session_view(self.last_session_row) if self.last_session_row is not None else None


class IngestionService:
    def __init__(self, settings: Settings, sessions: SessionFactory, hub: BroadcastHub) -> None:
        self.settings = settings
        self.sessions = sessions
        self.hub = hub
        # Serializes cursor-order broadcast across concurrent ingestion tasks.
        self._broadcast_lock = asyncio.Lock()

    async def ingest_batch(self, batch: EventBatch) -> IngestResult:
        result = IngestResult()
        persisted: list[Event] = []
        affected_sessions: dict[str, SessionRow] = {}

        # One lock spans persist + commit + broadcast. This keeps wire cursor
        # order strictly increasing: a cursor can never be assigned, committed
        # late, and published after a higher cursor (which would make replay
        # watermarks unsound).
        async with self._broadcast_lock:
            async with self.sessions() as db:
                async with db.begin():
                    for source_event in batch.events:
                        existing = await db.execute(
                            select(Event.event_id).where(Event.event_id == source_event.event_id)
                        )
                        if existing.scalar_one_or_none() is not None:
                            result.duplicates.append(source_event.event_id)
                            continue
                        session_row = await self._get_or_create_session(db, source_event)
                        stored = await self._persist_event(db, source_event, session_row.id)
                        self._update_session_from_event(session_row, source_event, stored)
                        await self._touch_machine(db, source_event)
                        persisted.append(stored)
                        affected_sessions[session_row.id] = session_row
                        result.last_event_row = stored
                        result.last_session_row = session_row
                        result.accepted.append(source_event.event_id)

            if persisted:
                # Everything is durable now; deliver live listeners in order.
                for row in persisted:
                    await self.hub.publish_for_session(
                        row.session_id,
                        Broadcast(cursor=row.cursor, event=to_normalized_event(row)),
                    )
                for session_row in affected_sessions.values():
                    await self.hub.publish_for_session(
                        session_row.id,
                        Broadcast(
                            cursor=session_row.latest_cursor,
                            session_view=to_session_view(session_row),
                            notify_session=True,
                        ),
                    )
        return result

    async def _get_or_create_session(self, db, source_event: SourceEvent) -> SessionRow:
        row = (
            await db.execute(
                select(SessionRow).where(
                    SessionRow.source == source_event.source,
                    SessionRow.machine_id == source_event.machine_id,
                    SessionRow.source_session_id == source_event.session_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = SessionRow(
                id=str(uuid.uuid4()),
                source=source_event.source,
                source_session_id=source_event.session_id,
                machine_id=source_event.machine_id,
                is_synthetic=is_synthetic_source(source_event.source),
                project_label=source_event.summary.get("project"),
                display_title=session_title(source_event),
                state="unknown",
                created_at=utc_now_iso(),
                event_count=0,
                latest_cursor=0,
            )
            db.add(row)
            await db.flush()
        return row

    async def _persist_event(self, db, source_event: SourceEvent, session_row_id: str) -> Event:
        labels = classify_event(
            source_event.kind,
            source_event.summary,
            evidence_event_id=source_event.event_id,
        )
        row = Event(
            event_id=str(source_event.event_id),
            session_id=session_row_id,
            machine_id=str(source_event.machine_id),
            source=str(source_event.source),
            source_event=str(source_event.source_event),
            kind=str(source_event.kind),
            occurred_at=source_event.occurred_at,
            received_at=utc_now_iso(),
            correlation=source_event.correlation.model_dump(),
            summary=source_event.summary,
            expertise=labels or None,
        )
        db.add(row)
        await db.flush()  # assigns the cursor
        return row

    @staticmethod
    def _update_session_from_event(
        session_row: SessionRow, source_event: SourceEvent, stored: Event
    ) -> None:
        incoming_state = SESSION_STATE_BY_KIND[source_event.kind]
        if should_update_state(session_row.state, incoming_state):
            session_row.state = incoming_state
        activity_at = source_event.occurred_at or stored.received_at
        if session_row.first_event_at is None or activity_at < session_row.first_event_at:
            session_row.first_event_at = activity_at
        if session_row.last_activity_at is None or activity_at > session_row.last_activity_at:
            session_row.last_activity_at = activity_at
        session_row.event_count = session_row.event_count + 1
        session_row.latest_cursor = max(session_row.latest_cursor, stored.cursor)
        project = source_event.summary.get("project")
        if project and not session_row.project_label:
            session_row.project_label = project[:200]

    async def _touch_machine(self, db, source_event: SourceEvent) -> None:
        now = utc_now_iso()
        machine = (
            await db.execute(select(Machine).where(Machine.id == source_event.machine_id))
        ).scalar_one_or_none()
        if machine is None:
            db.add(Machine(id=source_event.machine_id, first_seen_at=now, last_seen_at=now))
        else:
            machine.last_seen_at = now


def session_title(source_event: SourceEvent) -> str:
    base = source_event.summary.get("project") or source_event.session_id
    return f"{source_event.source}: {base}"[:300]
