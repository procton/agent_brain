"""Async engine/session management for SQLite.

Blocking database work stays out of the async event loop by using aiosqlite.
Migrations run synchronously once at startup, before the loop serves traffic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.app.config import Settings
from backend.app.database.models import Base

if TYPE_CHECKING:  # pragma: no cover
    from typing import Any


def build_async_engine(settings: Settings) -> AsyncEngine:
    """Async engine with WAL mode and permissive-looking but safe pragmas."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{settings.database_path}",
        connect_args={"timeout": 30},
    )

    def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


class SessionFactory:
    """Small wrapper so request handlers get short-lived sessions."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False
        )

    def __call__(self) -> AsyncSession:
        return self._maker()


__all__ = ["Base", "SessionFactory", "build_async_engine"]
