"""Session live WebSocket with replay-based reconnect.

Client protocol:
- open WS, send: {"type": "subscribe", "after": <cursor int>}
- receive:
    {"type": "events", "events": [...], "last_cursor": N, "replay": true}
    {"type": "replay_done", "last_cursor": N}
    {"type": "session", "session": {...}}     -- state/metadata updates
    {"type": "ready", "session": {...}}
- on any drop: reconnect with `after = last delivered cursor`; history is
  replayed from SQLite, so refreshes and reconnects recover missed events.

Gap-freedom: the subscription queue is registered *under the publish lock*
before SQLite replay runs. Ingestion persists (and commits) before publishing,
so an event is either visible to the replay query or queued in the live queue.
Queue items already replayed are skipped via a cursor watermark; ordering on
the wire stays increasing. This can only duplicate, never lose, events.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket
from sqlalchemy import select

from backend.app.database.models import Event, Session as SessionRow
from backend.app.schemas.normalized import SessionView
from backend.app.security import cookie_from_scope
from backend.app.services.hub import Broadcast, Subscription
from backend.app.services.views import to_normalized_event, to_session_view

router = APIRouter()

MAX_REPLAY_CHUNK = 200


@router.websocket("/sessions/{session_id}/live")
async def session_live(websocket: WebSocket, session_id: str) -> None:
    settings = websocket.app.state.settings
    browser_sessions = websocket.app.state.browser_sessions

    # Authentication happens before sending anything meaningful so browsers
    # get a clean refusal. WS requires an explicit allowlisted Origin header.
    origin = websocket.headers.get("origin")
    if not origin or origin not in settings.allowed_origins:
        await _accept_then_fail(websocket, "origin not allowed")
        return
    token = cookie_from_scope(websocket.scope)
    if not token or not browser_sessions.validate_token(token):
        await _accept_then_fail(websocket, "dashboard session required")
        return

    async with websocket.app.state.sessions() as db:
        row = (
            await db.execute(select(SessionRow).where(SessionRow.id == session_id))
        ).scalar_one_or_none()
    if row is None:
        await _accept_then_fail(websocket, "session not found")
        return
    session_row = row
    hub = websocket.app.state.hub

    await websocket.accept()

    # Register under the publish lock BEFORE replaying, so no event can slip
    # between the two phases.
    subscription: Subscription = await hub.subscribe(session_id)
    try:
        await websocket.send_json(
            {"type": "ready", "session": to_session_view(session_row).model_dump(mode="json")}
        )
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        after = raw.get("after", 0) if isinstance(raw, dict) else 0
        after = max(0, int(after))
    except Exception:
        await hub.unsubscribe(session_id, subscription)
        return

    try:
        watermark = await _replay(websocket, session_id, after)
        while True:
            broadcast: Broadcast | None = await subscription.queue.get()
            if broadcast is None:
                if subscription.closed:
                    break
                continue  # spurious wakeup
            if _is_stale(broadcast, watermark):
                continue
            await websocket.send_json(_message_for(broadcast))
    except Exception:
        pass  # client went away
    finally:
        await hub.unsubscribe(session_id, subscription)


def _is_stale(broadcast: Broadcast, watermark: int) -> bool:
    """Events replayed from the DB are already covered by the watermark."""
    return broadcast.event is not None and broadcast.cursor is not None and broadcast.cursor <= watermark


async def _accept_then_fail(websocket: WebSocket, detail: str) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "error", "detail": detail})
    await websocket.close()


async def _replay(websocket: WebSocket, session_id: str, after: int) -> int:
    """Send every persisted event with cursor > after; return the watermark."""
    watermark = after
    db_factory = websocket.app.state.sessions
    while True:
        async with db_factory() as db:
            rows = (
                (
                    await db.execute(
                        select(Event)
                        .where(Event.session_id == session_id, Event.cursor > after)
                        .order_by(Event.cursor.asc())
                        .limit(MAX_REPLAY_CHUNK)
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            break
        await websocket.send_json(
            {
                "type": "events",
                "events": [to_normalized_event(row).model_dump(mode="json") for row in rows],
                "last_cursor": rows[-1].cursor,
                "replay": True,
            }
        )
        watermark = max(watermark, rows[-1].cursor)
        if len(rows) < MAX_REPLAY_CHUNK:
            break
    await websocket.send_json({"type": "replay_done", "last_cursor": watermark})
    return watermark


def _message_for(broadcast: Broadcast) -> dict:
    if broadcast.event is not None:
        return {
            "type": "events",
            "events": [broadcast.event.model_dump(mode="json")],
            "last_cursor": broadcast.event.cursor,
        }
    if broadcast.session_view is not None:
        return {
            "type": "session",
            "session": broadcast.session_view.model_dump(mode="json"),
            "last_cursor": broadcast.session_view.latest_cursor,
        }
    return {"type": "noop"}


__all__ = ["router", "SessionView", "MAX_REPLAY_CHUNK"]
