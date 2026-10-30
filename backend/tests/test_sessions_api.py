"""Session list, snapshot, pagination, and state semantics."""

from __future__ import annotations

from backend.app.schemas.base import SESSION_STATE_BY_KIND, should_update_state
from backend.tests.conftest import SimpleClient, ingest, make_source_event


async def _seed_two_sessions(client: SimpleClient):
    await client.login()
    events_a = [
        make_source_event(
            session_id="synthetic-demo-0001", kind="session.started", source_event="SessionStart", index=0
        ),
        make_source_event(
            session_id="synthetic-demo-0001",
            kind="prompt.submitted",
            source_event="UserPromptSubmit",
            index=1,
        ),
        make_source_event(session_id="synthetic-demo-0001", kind="tool.requested", index=2),
        make_source_event(
            session_id="synthetic-demo-0001", kind="tool.completed", source_event="PostToolUse", index=3
        ),
    ]
    events_b = [
        make_source_event(
            session_id="synthetic-demo-0002", kind="session.started", source_event="SessionStart", index=10
        ),
        make_source_event(
            session_id="synthetic-demo-0002", kind="turn.completed", source_event="Stop", index=11
        ),
    ]
    await ingest(client, events_a)
    await ingest(client, events_b)


async def test_sessions_listed_with_synthetic_flag(client: SimpleClient):
    await _seed_two_sessions(client)
    listing = (await client.http.get("/api/sessions")).json()
    ids = [s["source_session_id"] for s in listing["sessions"]]
    assert set(ids) == {"synthetic-demo-0001", "synthetic-demo-0002"}
    assert all(s["is_synthetic"] for s in listing["sessions"])
    # state derived from observed kinds only
    state_a = next(s for s in listing["sessions"] if s["source_session_id"] == "synthetic-demo-0001")[
        "state"
    ]
    state_b = next(s for s in listing["sessions"] if s["source_session_id"] == "synthetic-demo-0002")[
        "state"
    ]
    assert state_a == "turn_active"
    assert state_b == "turn_finished"


async def test_snapshot_contains_session_and_events(client: SimpleClient):
    await _seed_two_sessions(client)
    listing = (await client.http.get("/api/sessions")).json()
    session_id = next(s for s in listing["sessions"] if s["source_session_id"] == "synthetic-demo-0001")[
        "id"
    ]
    snapshot = (await client.http.get(f"/api/sessions/{session_id}/snapshot")).json()
    assert snapshot["session"]["id"] == session_id
    assert len(snapshot["events"]) == 4
    cursors = [event["cursor"] for event in snapshot["events"]]
    assert cursors == sorted(cursors)
    assert snapshot["latest_cursor"] == max(cursors)
    assert snapshot["has_older_events"] is False


async def test_snapshot_unknown_session_is_404(client: SimpleClient):
    await client.login()
    response = await client.http.get("/api/sessions/nonexistent/snapshot")
    assert response.status_code == 404


async def test_events_pagination_is_bounded_and_ordered(client: SimpleClient):
    await client.login()
    events = [make_source_event(session_id="synthetic-demo-0003", index=i) for i in range(10)]
    await ingest(client, events)
    listing = (await client.http.get("/api/sessions")).json()
    session_id = listing["sessions"][0]["id"]

    page1 = (
        await client.http.get(f"/api/sessions/{session_id}/events", params={"after": 0, "limit": 4})
    ).json()
    assert len(page1["events"]) == 4
    assert page1["has_more"] is True
    page2_after = page1["next_after"]

    page2 = (
        await client.http.get(
            f"/api/sessions/{session_id}/events", params={"after": page2_after, "limit": 4}
        )
    ).json()
    cursors = [event["cursor"] for event in page1["events"]] + [
        event["cursor"] for event in page2["events"]
    ]
    assert cursors == sorted(cursors)
    assert len(set(cursors)) == 8

    tile = (await client.http.get(f"/api/sessions/{session_id}/events", params={"limit": 500})).json()
    all_ids = [event["event_id"] for event in tile["events"]]
    assert set(all_ids) == {event["event_id"] for event in events}
    assert tile["has_more"] is False


async def test_session_state_transitions_are_conservative(client: SimpleClient):
    await client.login()
    # ended stays ended even when more events arrive
    base = [
        make_source_event(
            session_id="synthetic-demo-0009", kind="session.started", source_event="SessionStart", index=0
        ),
        make_source_event(
            session_id="synthetic-demo-0009", kind="session.ended", source_event="SessionEnd", index=1
        ),
    ]
    await ingest(client, base)
    await ingest(
        client,
        [make_source_event(session_id="synthetic-demo-0009", kind="tool.requested", index=2)],
    )
    listing = (await client.http.get("/api/sessions")).json()
    assert listing["sessions"][0]["state"] == "ended"


async def test_prompt_after_finished_turn_reactivates(client: SimpleClient):
    await client.login()
    events = [
        make_source_event(
            session_id="synthetic-demo-0010", kind="turn.completed", source_event="Stop", index=0
        ),
        make_source_event(
            session_id="synthetic-demo-0010",
            kind="prompt.submitted",
            source_event="UserPromptSubmit",
            index=1,
        ),
    ]
    await ingest(client, events)
    listing = (await client.http.get("/api/sessions")).json()
    assert listing["sessions"][0]["state"] == "turn_active"


def test_state_mapping_table_is_exact():
    assert SESSION_STATE_BY_KIND["session.started"] == "unknown"
    assert SESSION_STATE_BY_KIND["turn.completed"] == "turn_finished"
    assert SESSION_STATE_BY_KIND["session.ended"] == "ended"


def test_should_update_state_rules():
    assert should_update_state("unknown", "turn_active") is True
    assert should_update_state("turn_active", "turn_active") is False
    assert should_update_state("turn_finished", "unknown") is False
    assert should_update_state("ended", "turn_active") is False
