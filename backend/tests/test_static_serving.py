"""Production static serving: the built frontend is served from FastAPI.

Regression tests for a real acceptance-run bug: the dist directory used the
wrong parent index, so `settings.frontend_dist_dir.exists()` was always False
and production mode silently served 404s instead of the SPA.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.app.config import Settings
from backend.app.main import _mount_frontend, create_app
from backend.tests.conftest import build_settings, dispose_app


def test_frontend_dist_dir_resolves_into_this_repo(tmp_path):
    """The property must compute the repo root, not a directory above it."""
    settings = build_settings(tmp_path)
    repo_root = Path(__file__).resolve().parents[2]
    assert settings.frontend_dist_dir == repo_root / "frontend" / "dist"


def _fake_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html lang='en'>spa</html>")
    (dist / "assets" / "app.js").write_text("console.log('static serving works');")
    return dist


async def test_mounted_frontend_serves_index_assets_and_fallback(tmp_path):
    app = FastAPI()
    _mount_frontend(app, _fake_dist(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
        assert (await http.get("/")).text.endswith("spa</html>")
        asset = await http.get("/assets/app.js")
        assert asset.status_code == 200 and "static serving works" in asset.text
        # SPA fallback: client-side routes get the shell, not a 404.
        assert (await http.get("/sessions")).status_code == 200
        assert (await http.get("/sessions")).text.endswith("spa</html>")
        # API namespace is never hijacked by the SPA handler.
        assert (await http.get("/api/definitely-missing")).status_code == 404


async def test_production_build_mounts_the_frontend(tmp_path, monkeypatch):
    dist = _fake_dist(tmp_path)
    monkeypatch.setattr(Settings, "frontend_dist_dir", property(lambda self: dist))
    settings = build_settings(tmp_path, env="production")
    app = create_app(settings)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
            assert (await http.get("/")).text.endswith("spa</html>")
            assert (await http.get("/assets/app.js")).status_code == 200
    finally:
        await dispose_app(app)


async def test_development_build_does_not_mount_static(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "frontend_dist_dir", property(lambda self: _fake_dist(tmp_path)))
    settings = build_settings(tmp_path, env="development")
    app = create_app(settings)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
            assert (await http.get("/")).status_code == 404
    finally:
        await dispose_app(app)
