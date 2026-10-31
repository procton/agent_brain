"""The dashboard must accept its own serving origin (incident regression test).

An acceptance stack was run with `uvicorn --port 8041` and no
`OBSERVATORY_PORT`; the origin allowlist then still described port 8000 and
the backend rejected the dashboard requests its own process served
(unlock POST and WS handshake). The serving port must therefore be
self-allowed, derived per request from the ASGI scope.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.app.config import secret_from_file
from backend.app.main import create_app
from backend.app.security import origin_allowed, server_port_from_scope
from backend.tests.conftest import build_settings


def test_server_port_follows_the_asgi_scope():
    assert server_port_from_scope({"server": ("127.0.0.1", 8041)}) == 8041
    assert server_port_from_scope({}) is None
    assert server_port_from_scope({"server": ("127.0.0.1", None)}) is None


def test_origin_allowlist_extends_with_the_real_port(tmp_path):
    settings = build_settings(tmp_path)
    # settings.port is 8000 here; a different serving port gains self-origins.
    with_port = origin_allowed("http://127.0.0.1:8041", settings, require_for_write=True, server_port=8041)
    without_port = origin_allowed(
        "http://127.0.0.1:8041", settings, require_for_write=True, server_port=None
    )
    foreign = origin_allowed("http://127.0.0.1:9991", settings, require_for_write=True, server_port=8041)
    default = origin_allowed("http://127.0.0.1:8000", settings, require_for_write=True, server_port=None)
    assert with_port is True
    assert without_port is False
    assert foreign is False
    assert default is True  # the configured allowlist keeps working


async def test_real_server_accepts_its_own_port_as_origin(live):
    """Unlock + session list against the REAL bound port, while
    OBSERVATORY_PORT (settings.port=8000) describes a different port —
    exactly the shape of the production incident."""
    real_port = int(live.base_url.rsplit(":", 1)[1])
    assert real_port != live.settings.port  # the divergent-port scenario holds
    code = secret_from_file(live.settings.dashboard_code_path)

    own = f"http://127.0.0.1:{real_port}"
    foreign = "http://127.0.0.1:9991"

    async with httpx.AsyncClient(base_url=live.base_url) as client:
        unlock = await client.post(
            "/api/auth/browser-session",
            json={"code": code},
            headers={"Origin": own},
        )
        assert unlock.status_code == 200, unlock.text

        sessions_ok = await client.get("/api/sessions", headers={"Origin": own})
        assert sessions_ok.status_code == 200, sessions_ok.text

    async with httpx.AsyncClient(base_url=live.base_url) as client:
        unlock = await client.post(
            "/api/auth/browser-session",
            json={"code": code},
            headers={"Origin": foreign},
        )
        assert unlock.status_code == 403
        sessions_ok = await client.get("/api/sessions", headers={"Origin": foreign})
        assert sessions_ok.status_code == 403


def test_startup_prints_the_dashboard_access_code(tmp_path, capsys):
    settings = build_settings(tmp_path)
    app = create_app(settings)
    expected = secret_from_file(settings.dashboard_code_path)

    with TestClient(app):
        pass

    out = capsys.readouterr().out
    assert "dashboard access code:" in out
    assert expected in out


@pytest.fixture
async def live(tmp_path: Path):
    """Real uvicorn server on a random port with OBSERVATORY_PORT misdescribed
    as 8000 — the divergent-port production shape."""
    settings = build_settings(tmp_path)  # port=8000 deliberately ≠ serving port
    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, loop="asyncio", http="h11", log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.02)
    else:  # pragma: no cover
        raise RuntimeError("uvicorn did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    live = SimpleNamespace(base_url=f"http://127.0.0.1:{port}", settings=settings, app=app)
    yield live
    server.should_exit = True
    thread.join(timeout=10)
