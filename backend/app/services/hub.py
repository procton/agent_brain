"""In-process WebSocket broadcast hub.

Single-process design (per AGENT.md): every live subscription owns an asyncio
queue. Ingestion persists *before* broadcasting, and broadcasts are serialized
by a lock so cursor order is preserved on the wire.

Reconnect safety: clients subscribe with `after=<cursor>`. The server registers
the listener under the same lock used when accepting new broadcasts, then
replays older events straight from SQLite. Because persistence happens before
broadcast, ordering here can yield duplicates but never gaps; clients dedupe
by cursor.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from backend.app.schemas.normalized import NormalizedEvent, SessionView


@dataclass(eq=False)
class Broadcast:
    """Everything a session subscriber might care about, attached to a cursor."""

    cursor: int | None
    event: NormalizedEvent | None = None
    session_view: SessionView | None = None
    notify_session: bool = False


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[Broadcast | None] = field(default_factory=asyncio.Queue)
    closed: bool = False

    def close(self) -> None:
        self.closed = True
        # `None` wakes any waiting reader observing `closed`.
        self.queue.put_nowait(None)


class BroadcastHub:
    def __init__(self) -> None:
        self._session_subs: dict[str, set[Subscription]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> Subscription:
        """Register under the publish lock to eliminate gaps (duplicates ok)."""
        subscription = Subscription()
        async with self._lock:
            self._session_subs.setdefault(session_id, set()).add(subscription)
        return subscription

    async def unsubscribe(self, session_id: str, subscription: Subscription) -> None:
        subscription.close()
        async with self._lock:
            group = self._session_subs.get(session_id)
            if group is not None:
                group.discard(subscription)
                if not group:
                    self._session_subs.pop(session_id, None)

    def close_all(self) -> None:
        """Wake every listener at shutdown (most callers will be closing WS)."""
        for group in list(self._session_subs.values()):
            for subscription in group:
                subscription.close()
        self._session_subs.clear()

    async def publish_for_session(self, session_id: str, broadcast: Broadcast) -> None:
        """Deliver to all live listeners of one session; persist caller-side."""
        async with self._lock:
            targets = {sub for sub in self._session_subs.get(session_id, set()) if not sub.closed}
            for subscription in targets:
                subscription.queue.put_nowait(broadcast)


def make_session_notification(session_view: SessionView) -> Broadcast:
    """A lightweight update carrying no event payload (state/metadata only)."""
    return Broadcast(
        cursor=session_view.latest_cursor, session_view=session_view, notify_session=True
    )
