"""Ingestion behavior: validation, dedup, sizes, timestamps."""

from __future__ import annotations

from backend.tests.conftest import SimpleClient, ingest, make_source_event


async def test_happy_batch_is_persisted(client: SimpleClient):
    events = [
        make_source_event(kind="session.started", source_event="SessionStart", index=0),
        make_source_event(kind="tool.requested", index=1),
    ]
    response = await ingest(client, events)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["accepted"] == [event["event_id"] for event in events]
    assert report["duplicates"] == []

    await client.login()
    listing = await client.http.get("/api/sessions")
    assert listing.status_code == 200
    sessions = listing.json()["sessions"]
    assert len(sessions) == 1
    session = sessions[0]
    assert session["event_count"] == 2
    assert session["source"] == "synthetic"
    assert session["is_synthetic"] is True
    assert session["state"] == "turn_active"  # last kind was tool.requested


async def test_duplicate_event_id_is_ignored_not_reprocessed(client: SimpleClient):
    first = [make_source_event()]
    response = await ingest(client, first)
    assert response.status_code == 200
    response = await ingest(client, first)
    assert response.status_code == 200
    report = response.json()
    assert report["accepted"] == []
    assert report["duplicates"] == [first[0]["event_id"]]

    await client.login()
    listing = (await client.http.get("/api/sessions")).json()["sessions"]
    assert listing[0]["event_count"] == 1


async def test_late_out_of_order_event_is_accepted(client: SimpleClient):
    """arrival cursors grow; occurred_at from the source is preserved."""
    earlier = make_source_event(kind="tool.completed", occurred_at="2026-10-29T09:00:00.000+00:00", index=0)
    await ingest(client, [make_source_event(index=1)])
    await ingest(client, [earlier])  # late, out-of-order arrival
    await client.login()
    listing = (await client.http.get("/api/sessions")).json()["sessions"]
    assert len(listing) == 1
    snapshot = (await client.http.get(f"/api/sessions/{listing[0]['id']}/snapshot")).json()
    kinds = [event["kind"] for event in snapshot["events"]]
    # late event stored after, but keeps its source occurred_at
    assert kinds[-1] == "tool.completed"
    assert snapshot["events"][-1]["occurred_at"] == "2026-10-29T09:00:00.000+00:00"


async def test_invalid_kind_is_rejected(client: SimpleClient):
    event = make_source_event()
    event["kind"] = "brainwave.detected"
    response = await ingest(client, [event])
    assert response.status_code == 422


async def test_unknown_source_fields_are_ignored(client: SimpleClient):
    event = make_source_event()
    event["raw_prompt"] = "should not persist"
    event["future_field"] = 42
    response = await ingest(client, [event])
    assert response.status_code == 200
    report = response.json()
    assert report["accepted"] == [event["event_id"]]


async def test_malformed_json_is_rejected(client: SimpleClient):
    response = await client.http.post(
        "/api/events/batch",
        content=b"this is not json",
        headers={
            "Authorization": f"Bearer {client.harness.ingest_token}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 422
    assert "no events persisted" in response.text


async def test_batch_too_many_events_rejected(client: SimpleClient):
    events = [make_source_event(index=i) for i in range(101)]
    response = await ingest(client, events)
    assert response.status_code == 422


async def test_body_size_limit_enforced(client: SimpleClient):
    payload = make_source_event()
    payload["summary"] = {"tool": "Read", "target": "x" * (512 * 1024)}
    response = await ingest(client, [payload])
    assert response.status_code == 413


async def test_occurred_at_optional_falls_back_to_received(client: SimpleClient):
    event = make_source_event()
    event["occurred_at"] = None
    response = await ingest(client, [event])
    assert response.status_code == 200
    await client.login()
    listing = (await client.http.get("/api/sessions")).json()["sessions"]
    snapshot = (await client.http.get(f"/api/sessions/{listing[0]['id']}/snapshot")).json()
    stored = snapshot["events"][0]
    assert stored["occurred_at"] is None
    assert stored["received_at"]


async def test_missing_session_fields_rejected(client: SimpleClient):
    event = make_source_event()
    event["session_id"] = ""
    response = await ingest(client, [event])
    assert response.status_code == 422


async def test_correlation_ids_only_stored_when_source_provides(client: SimpleClient):
    event = make_source_event(correlation={"tool_call_id": None})
    response = await ingest(client, [event])
    assert response.status_code == 200
    await client.login()
    listing = (await client.http.get("/api/sessions")).json()["sessions"]
    snapshot = (await client.http.get(f"/api/sessions/{listing[0]['id']}/snapshot")).json()
    assert snapshot["events"][0]["correlation"] == {
        "tool_call_id": None,
        "agent_id": None,
        "parent_agent_id": None,
    }
