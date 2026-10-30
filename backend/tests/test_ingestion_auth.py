"""Authentication: ingestion token and dashboard browser session."""

from __future__ import annotations

from backend.tests.conftest import SimpleClient, ingest, make_source_event


async def test_ingest_requires_bearer_token(client: SimpleClient):
    response = await client.http.post(
        "/api/events/batch", json={"schema_version": 1, "events": [make_source_event()]}
    )
    assert response.status_code == 401


async def test_ingest_rejects_wrong_token(client: SimpleClient):
    response = await ingest(client, [make_source_event()], token="totally-wrong")
    assert response.status_code == 403


async def test_ingest_valid_token_accepts(client: SimpleClient):
    response = await ingest(client, [make_source_event()])
    assert response.status_code == 200


# -- dashboard browser session ------------------------------------------------


async def test_api_requires_cookie(client: SimpleClient):
    response = await client.http.get("/api/sessions")
    assert response.status_code == 401


async def test_login_with_wrong_code_rejected(client: SimpleClient):
    response = await client.login(code="definitely-not-the-code")
    assert response.status_code == 403
    response = await client.http.get("/api/sessions")
    assert response.status_code == 401


async def test_login_without_origin_rejected(client: SimpleClient):
    """State-changing request: browsers always send Origin; absence is rejected."""
    response = await client.http.post(
        "/api/auth/browser-session",
        json={"code": client.harness.dashboard_code},
    )
    assert response.status_code == 403


async def test_login_foreign_origin_rejected(client: SimpleClient):
    response = await client.login(origin="https://evil.example.com")
    assert response.status_code == 403


async def test_login_dev_origin_allowed(client: SimpleClient):
    response = await client.login(origin="http://localhost:5173")
    assert response.status_code == 200, response.text
    listing = await client.http.get("/api/sessions", headers={"Origin": "http://localhost:5173"})
    assert listing.status_code == 200


async def test_login_sets_httponly_cookie(client: SimpleClient):
    response = await client.login()
    cookie_lines = [h for h in response.headers.get_list("set-cookie")]
    assert any("observatory_dashboard=" in line for line in cookie_lines)
    assert any("httponly" in line.lower() for line in cookie_lines)
    assert any("samesite=strict" in line.replace("SameSite", "samesite").lower() for line in cookie_lines)
    # never a document-exposed cookie
    assert not any("document" in line for line in cookie_lines)


async def test_auth_status_reports_state(client: SimpleClient):
    assert (await client.http.get("/api/auth/status")).status_code == 401
    await client.login()
    assert (await client.http.get("/api/auth/status")).status_code == 200


async def test_ingest_with_ingest_origin_header_is_allowed(client: SimpleClient):
    """The collector is not a browser; a matching loopback origin is fine."""
    response = await client.http.post(
        "/api/events/batch",
        json={"schema_version": 1, "events": [make_source_event()]},
        headers={
            "Authorization": f"Bearer {client.harness.ingest_token}",
            "Origin": "http://127.0.0.1:8000",
        },
    )
    assert response.status_code == 200


async def test_ingest_foreign_origin_with_token_rejected(client: SimpleClient):
    response = await client.http.post(
        "/api/events/batch",
        json={"schema_version": 1, "events": [make_source_event()]},
        headers={
            "Authorization": f"Bearer {client.harness.ingest_token}",
            "Origin": "https://evil.example.com",
        },
    )
    assert response.status_code == 403
