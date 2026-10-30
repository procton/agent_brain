"""WebSocket replay/reconnect integration on a real uvicorn socket.

Scenario (AGENT.md reconnect requirement): no event may be lost between the
HTTP snapshot and the WS subscription, and a reconnect with `after=<cursor>`
must recover exactly the missed window without duplicates.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from backend.app.schemas.source import SourceEvent
from backend.tests.conftest import (
    TEST_ORIGINS,
    LiveServer,
    browser_login,
    cookie_header,
    make_source_event,
)


def source_event_to_wire(event: dict) -> dict:
    return SourceEvent.model_validate(event).model_dump()


async def _ingest_direct(live: LiveServer, events: list[dict]) -> None:
    """Ingest through the real HTTP API (like the collector does).

    This runs inside the uvicorn server loop, exactly as in production; calling
    async app internals directly from the test loop would break loop-affine
    primitives (locks, queues) shared with the server.
    """
    batch = {
        "schema_version": 1,
        "events": [SourceEvent.model_validate(event).model_dump(mode="json") for event in events],
    }
    async with httpx.AsyncClient(base_url=live.base_url) as client:
        response = await client.post(
            "/api/events/batch",
            json=batch,
            headers={
                "Authorization": f"Bearer {live.app.state.ingest_token}",
            },
        )
        assert response.status_code == 200, response.text


def _ws_url(live: LiveServer, session_id: str) -> str:
    return live.base_url.replace("http://", "ws://") + f"/api/sessions/{session_id}/live"


WS_HEADERS = {
    "Origin": TEST_ORIGINS[0],
}


async def _settle() -> None:
    await asyncio.sleep(0.2)


async def _subscribe_and_collect(
    live: LiveServer, session_id: str, after: int, *, collect_seconds: float = 1.0
) -> tuple[list[dict], int, httpx.Cookies]:
    cookies = await browser_login(live.base_url, live.settings and live.app.state.dashboard_code)
    token = cookie_header(cookies)
    headers = {**WS_HEADERS, "Cookie": f"observatory_dashboard={token}"}
    live_events: list[dict] = []
    latest = after
    async with websockets.connect(_ws_url(live, session_id), additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "subscribe", "after": after}))
        replay_done_seen = False
        deadline = asyncio.get_running_loop().time() + collect_seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=0.2)
            except TimeoutError:
                if replay_done_seen:
                    break
                continue
            data = json.loads(message)
            if data["type"] == "events":
                live_events.extend(data["events"])
                latest = max(latest, data["last_cursor"])
            elif data["type"] == "replay_done":
                replay_done_seen = True
            elif data["type"] in ("ready", "session"):
                pass
    return live_events, latest, cookies


async def test_live_delivery_while_connected(live: LiveServer):
    base_events = [make_source_event(index=i) for i in range(3)]
    await _ingest_direct(live, base_events)
    cookies = await browser_login(live.base_url, live.app.state.dashboard_code)
    token = cookie_header(cookies)
    headers = {**WS_HEADERS, "Cookie": f"observatory_dashboard={token}"}
    session_id = await _only_session_id(live)

    received: list[dict] = []
    async with websockets.connect(_ws_url(live, session_id), additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "subscribe", "after": 0}))
        while True:
            data = json.loads(await ws.recv())
            if data["type"] == "replay_done":
                break
            if data["type"] == "events":
                received.extend(data["events"])

        # events published while connected must arrive without a refresh
        fresh = [make_source_event(index=90 + i) for i in range(2)]
        ingest_task = asyncio.create_task(_ingest_direct(live, fresh))
        expected_ids = {event["event_id"] for event in fresh}
        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            try:
                data = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.3))
            except TimeoutError:
                if ingest_task.done():
                    ingest_task.result()  # surface ingest errors
                    continue
                continue
            if data["type"] == "events":
                received.extend(data["events"])
                if expected_ids.issubset({event["event_id"] for event in received}):
                    break
        await ingest_task
        ids_now = [event["event_id"] for event in received]
        for event in fresh:
            assert event["event_id"] in ids_now, "live event was not delivered"


async def _only_session_id(live: LiveServer) -> str:
    async with httpx.AsyncClient(base_url=live.base_url) as client:
        await client.post(
            "/api/auth/browser-session",
            json={"code": live.app.state.dashboard_code},
            headers={"Origin": TEST_ORIGINS[0]},
        )
        listing = await client.get("/api/sessions")
        return listing.json()["sessions"][0]["id"]


async def test_replay_and_live_delivery_without_gaps(live: LiveServer):
    base_events = [make_source_event(index=i) for i in range(5)]
    await _ingest_direct(live, base_events)

    snapshot_client = httpx.AsyncClient(base_url=live.base_url)
    login_response = await snapshot_client.post(
        "/api/auth/browser-session",
        json={"code": live.app.state.dashboard_code},
        headers={"Origin": TEST_ORIGINS[0]},
    )
    assert login_response.status_code == 200
    listing = await snapshot_client.get("/api/sessions")
    session_id = listing.json()["sessions"][0]["id"]
    snapshot = await snapshot_client.get(f"/api/sessions/{session_id}/snapshot")
    latest_cursor = snapshot.json()["latest_cursor"]
    await snapshot_client.aclose()

    # publish MORE events after the snapshot, before the client subscribes:
    # these are exactly the events a naive live-only subscription would miss.
    late_events = [make_source_event(index=10 + i) for i in range(3)]
    await _ingest_direct(live, late_events)

    events, latest, _ = await _subscribe_and_collect(live, session_id, latest_cursor)
    event_ids = {event["event_id"] for event in events}
    expected = {event["event_id"] for event in late_events}
    assert expected.issubset(event_ids), "events persisted before subscribe must replay"
    assert len(event_ids) == len(events), "no duplicates delivered without the watermark skip"


async def test_refresh_recovers_full_history_and_live(live: LiveServer):
    base_events = [make_source_event(index=i) for i in range(6)]
    await _ingest_direct(live, base_events)
    snapshot_client = httpx.AsyncClient(base_url=live.base_url)
    await snapshot_client.post(
        "/api/auth/browser-session",
        json={"code": live.app.state.dashboard_code},
        headers={"Origin": TEST_ORIGINS[0]},
    )
    session_id = (await snapshot_client.get("/api/sessions")).json()["sessions"][0]["id"]

    # Browser refresh flow: HTTP snapshot...
    snapshot = (await snapshot_client.get(f"/api/sessions/{session_id}/snapshot")).json()
    seen = {event["event_id"]: event["cursor"] for event in snapshot["events"]}
    assert len(seen) == 6

    # ...then WS subscribe from the snapshot's latest cursor.
    during = [make_source_event(index=50)]
    await _ingest_direct(live, during)
    events, latest, _ = await _subscribe_and_collect(live, session_id, snapshot["latest_cursor"])
    for event in events:
        seen.setdefault(event["event_id"], event["cursor"])
    assert {e["event_id"] for e in during} <= set(seen)
    await snapshot_client.aclose()


async def test_reconnect_after_dropped_connection_recovers_missed_events(live: LiveServer):
    base_events = [make_source_event(index=i) for i in range(4)]
    await _ingest_direct(live, base_events)

    cookies = await browser_login(live.base_url, live.app.state.dashboard_code)
    token = cookie_header(cookies)
    headers = {**WS_HEADERS, "Cookie": f"observatory_dashboard={token}"}
    snapshot_client = httpx.AsyncClient(base_url=live.base_url)
    await snapshot_client.post(
        "/api/auth/browser-session",
        json={"code": live.app.state.dashboard_code},
        headers={"Origin": TEST_ORIGINS[0]},
    )
    session_id = (await snapshot_client.get("/api/sessions")).json()["sessions"][0]["id"]

    # first connection: receive replay, then drop immediately
    live_events = []
    latest = 0
    async with websockets.connect(_ws_url(live, session_id), additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "subscribe", "after": 0}))
        while True:
            data = json.loads(await ws.recv())
            if data["type"] == "replay_done":
                latest = data["last_cursor"]
                break
            if data["type"] == "events":
                live_events.extend(data["events"])

    # connection lost: events arrive while client is offline
    missed = [make_source_event(index=70 + i) for i in range(3)]
    await _ingest_direct(live, missed)

    # reconnect with after=last delivered cursor; nothing already-seen is redelivered
    events2, latest2, _ = await _subscribe_and_collect(live, session_id, latest)
    missing = {e["event_id"] for e in missed} - {e["event_id"] for e in events2}
    assert missing == set(), f"missed events were lost on reconnect: {missing}"
    redundant = {e["event_id"] for e in events2} & {e["event_id"] for e in live_events}
    assert redundant == set(), f"already-delivered events were replayed: {redundant}"
    await snapshot_client.aclose()


async def test_ws_rejects_foreign_origin(live: LiveServer):
    cookies = await browser_login(live.base_url, live.app.state.dashboard_code)
    token = cookie_header(cookies)
    headers = {"Origin": "https://evil.example.com", "Cookie": f"observatory_dashboard={token}"}
    async with websockets.connect(_ws_url(live, "whatever"), additional_headers=headers) as ws:
        data = json.loads(await ws.recv())
        assert data["type"] == "error"
        assert "origin" in data["detail"]


async def test_ws_rejects_missing_cookie(live: LiveServer):
    headers = {"Origin": TEST_ORIGINS[0]}
    async with websockets.connect(_ws_url(live, "whatever"), additional_headers=headers) as ws:
        data = json.loads(await ws.recv())
        assert data["type"] == "error"
        assert "dashboard session" in data["detail"]


async def test_ws_unknown_session_reports_error(live: LiveServer):
    cookies = await browser_login(live.base_url, live.app.state.dashboard_code)
    token = cookie_header(cookies)
    headers = {**WS_HEADERS, "Cookie": f"observatory_dashboard={token}"}
    async with websockets.connect(_ws_url(live, "00bogus-session"), additional_headers=headers) as ws:
        data = json.loads(await ws.recv())
        assert data["type"] == "error"
        assert data["detail"] == "session not found"
