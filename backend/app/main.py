"""FastAPI application factory for the observatory backend.

Startup sequence (synchronous, before the event loop serves):
1. Create the data directory and ensure the local ingest credential and the
   dashboard access code exist (0600 files).
2. Run Alembic migrations against SQLite.
3. Build the async engine, ingestion service, and broadcast hub.

In production mode (`OBSERVATORY_ENV=production`) the built frontend is served
from the same origin. In development the Vite dev server is proxied by its own
config; permissive CORS is never enabled.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from backend.app import config as app_config
from backend.app.api import events as events_api
from backend.app.api import expertise as expertise_api
from backend.app.api import health as health_api
from backend.app.api import sessions as sessions_api
from backend.app.api import ws as ws_api
from backend.app.config import (
    Settings,
    create_credential_file,
    create_dashboard_code_file,
)
from backend.app.config import (
    settings as default_settings,
)
from backend.app.database.engine import SessionFactory, build_async_engine
from backend.app.database.migrations import run_migrations
from backend.app.security import BrowserSessions
from backend.app.services.hub import BroadcastHub
from backend.app.services.ingest import IngestionService

logger = logging.getLogger("observatory.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or default_settings

    prepare_data_directory(settings)

    run_migrations(f"sqlite:///{settings.database_path}")

    engine = build_async_engine(settings)
    session_factory = SessionFactory(engine)
    hub = BroadcastHub()
    ingestion = IngestionService(settings, session_factory, hub)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await engine.dispose()
        hub.close_all()

    app = FastAPI(title="Agent Brain Observatory", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = session_factory
    app.state.hub = hub
    app.state.ingestion = ingestion
    app.state.ingest_token = app_config.secret_from_file(settings.credential_path)
    app.state.dashboard_code = app_config.secret_from_file(settings.dashboard_code_path)
    app.state.browser_sessions = BrowserSessions(settings)

    app.include_router(health_api.router, prefix="/api")
    app.include_router(events_api.router, prefix="/api")
    app.include_router(sessions_api.router, prefix="/api")
    app.include_router(expertise_api.router, prefix="/api")
    app.include_router(ws_api.router, prefix="/api")

    if settings.production and settings.frontend_dist_dir.exists():
        _mount_frontend(app, settings.frontend_dist_dir)

    return app


def prepare_data_directory(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    create_credential_file(settings.credential_path)
    create_dashboard_code_file(settings.dashboard_code_path)
    logger.info("observatory data directory: %s", settings.data_dir)


def _mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    assets = dist_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index_file = dist_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):  # noqa: ANN202
        candidate = dist_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        if full_path.startswith("api"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(index_file)


app = create_app()
