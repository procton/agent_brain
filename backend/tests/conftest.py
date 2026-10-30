"""Shared backend test fixtures.

Uses temporary data directories exclusively — the developer's real Claude Code
settings and app data are never touched.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app

TEST_ORIGINS = ("http://127.0.0.1:8000", "http://localhost:5173")


@dataclass
class TestHarness:
    settings: Settings
    app: object = field(default=None)

    @property
    def ingest_token(self) -> str:
        from backend.app.config import secret_from_file

        return secret_from_file(self.settings.credential_path)

    @property
    def dashboard_code(self) -> str:
        from backend.app.config import secret_from_file

        return secret_from_file(self.settings.dashboard_code_path)


def build_settings(tmp_path: Path, *, env: str = "development", port: int = 8000) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        env=env,
        port=port,
    )


@pytest.fixture
def harness(tmp_path) -> TestHarness:
    settings = build_settings(tmp_path)
    from backend.app.main import create_app

    app = create_app(settings)
    return TestHarness(settings=settings, app=app)


@pytest.fixture
async def client(harness: TestHarness):
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http:
        yield SimpleClient(http=http, harness=harness)


class SimpleClient:
    """HTTP client that knows the harness code/token for convenience helpers."""

    def __init__(self, http: httpx.AsyncClient, harness: TestHarness):
        self.http = http
        self.harness = harness

    def auth_headers_origin(self, origin: str = TEST_ORIGINS[0]) -> dict:
        return {"Origin": origin}

    async def login(self, *, origin: str = TEST_ORIGINS[0], code: str | None = None) -> httpx.Response:
        return await self.http.post(
            "/api/auth/browser-session",
            json={"code": code if code is not None else self.harness.dashboard_code},
            headers={"Origin": origin},
        )


def make_source_event(
    *,
    event_id: str | None = None,
    session_id: str = "synthetic-demo-0001",
    kind: str = "tool.requested",
    source_event: str = "PreToolUse",
    machine_id: str = "test-machine",
    occurred_at: str | None = None,
    tool: str = "Read",
    target: str = "README.md",
    index: int = 0,
    correlation: dict | None = None,
) -> dict:
    base = datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=index)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "machine_id": machine_id,
        "session_id": session_id,
        "source": "synthetic",
        "source_event": source_event,
        "kind": kind,
        "occurred_at": occurred_at if occurred_at is not None else base.isoformat(timespec="milliseconds"),
        "recorded_at": base.isoformat(timespec="milliseconds"),
        "correlation": correlation or {"tool_call_id": f"call-{index:04d}"},
        "summary": {"tool": tool, "target": target, "project": "demo"},
    }


async def ingest(client: SimpleClient, events: list[dict], *, token: str | None = None) -> httpx.Response:
    return await client.http.post(
        "/api/events/batch",
        json={"schema_version": 1, "events": events},
        headers={"Authorization": f"Bearer {token or client.harness.ingest_token}"},
    )


# ---------------------------------------------------------------------------
# Live uvicorn server (for WebSocket integration tests)
# ---------------------------------------------------------------------------


class LiveServer:
    def __init__(self, settings: Settings, base_url: str):
        self.settings = settings
        self.base_url = base_url
        self.app = None


@pytest.fixture
async def live(tmp_path) -> LiveServer:
    import asyncio
    import uvicorn

    settings = build_settings(tmp_path)
    app = create_app(settings)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, loop="asyncio", http="h11", log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.02)
    else:  # pragma: no cover
        raise RuntimeError("uvicorn did not start")
    host, port = None, None
    for sock in server.servers[0].sockets:
        host, port = sock.getsockname()[:2]
        break
    live = LiveServer(settings=settings, base_url=f"http://127.0.0.1:{port}")
    live.app = app
    yield live
    server.should_exit = True
    thread.join(timeout=10)


async def browser_login(base_url: str, code: str, *, origin: str = TEST_ORIGINS[0]) -> httpx.Cookies:
    """Perform the dashboard login handshake with a real HTTP client."""
    async with httpx.AsyncClient(base_url=base_url) as client:
        response = await client.post(
            "/api/auth/browser-session", json={"code": code}, headers={"Origin": origin}
        )
        assert response.status_code == 200, response.text
        return client.cookies


def cookie_header(cookies: httpx.Cookies) -> str | None:
    return cookies.get("observatory_dashboard") or None


def make_source_events(
    count: int,
    session_id: str = "synthetic-demo-0001",
    *,
    machine_id: str = "test-machine",
) -> list[dict]:
    """`count` unique events for one session, ready to ingest."""
    return [
        make_source_event(session_id=session_id, index=index, machine_id=machine_id)
        for index in range(count)
    ]


async def dispose_app(app) -> None:
    """Close the async engine created by create_app (no lifespan in ASGI tests)."""
    engine = getattr(app.state, "engine", None)
    if engine is not None:
        await engine.dispose()
