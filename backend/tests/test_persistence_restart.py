"""Persistence across restart: a new app process sees the same data."""

from __future__ import annotations

from backend.app.main import create_app
from backend.tests.conftest import build_settings, dispose_app, make_source_events


async def test_events_survive_backend_restart(tmp_path):
    import httpx

    settings = build_settings(tmp_path)

    # "first process"
    app_one = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_one), base_url="http://127.0.0.1"
    ) as client:
        login = await client.post(
            "/api/auth/browser-session",
            json={"code": app_one.state.dashboard_code},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        assert login.status_code == 200
        events = make_source_events(6, session_id="synthetic-demo-0001")
        response = await client.post(
            "/api/events/batch",
            json={"schema_version": 1, "events": events},
            headers={"Authorization": f"Bearer {app_one.state.ingest_token}"},
        )
        assert response.status_code == 200
        sessions_before = (await client.get("/api/sessions")).json()["sessions"]
    await dispose_app(app_one)

    # "second process": same data dir, fresh app (migrations are idempotent)
    app_two = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_two), base_url="http://127.0.0.1"
    ) as client:
        await client.post(
            "/api/auth/browser-session",
            json={"code": app_two.state.dashboard_code},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        sessions_after = (await client.get("/api/sessions")).json()["sessions"]
        assert sessions_after, "session lost after restart"
        assert sessions_after[0]["event_count"] == sessions_before[0]["event_count"]
        snapshot = (await client.get(f"/api/sessions/{sessions_after[0]['id']}/snapshot")).json()
        assert len(snapshot["events"]) == 6
        assert snapshot["latest_cursor"] == max(event["cursor"] for event in snapshot["events"])
    await dispose_app(app_two)


async def test_duplicate_ingestion_after_restart_does_not_duplicate(tmp_path):
    import httpx

    settings = build_settings(tmp_path)
    app_one = create_app(settings)
    events = make_source_events(2, session_id="synthetic-demo-0002")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_one), base_url="http://127.0.0.1"
    ) as client:
        await client.post(
            "/api/auth/browser-session",
            json={"code": app_one.state.dashboard_code},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        await client.post(
            "/api/events/batch",
            json={"schema_version": 1, "events": events},
            headers={"Authorization": f"Bearer {app_one.state.ingest_token}"},
        )
    await dispose_app(app_one)

    app_two = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_two), base_url="http://127.0.0.1"
    ) as client:
        await client.post(
            "/api/auth/browser-session",
            json={"code": app_two.state.dashboard_code},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        replay = await client.post(
            "/api/events/batch",
            json={"schema_version": 1, "events": events},
            headers={"Authorization": f"Bearer {app_two.state.ingest_token}"},
        )
        assert replay.status_code == 200
        assert replay.json()["duplicates"] == [event["event_id"] for event in events]
        listing = (await client.get("/api/sessions")).json()["sessions"]
        assert listing[0]["event_count"] == 2
    await dispose_app(app_two)
