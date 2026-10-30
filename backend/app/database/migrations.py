"""Programmatic Alembic bootstrap.

The backend runs Alembic migrations synchronously at startup, before serving.
`alembic upgrade head` can also be run from the CLI: alembic -c backend/alembic.ini upgrade head.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def run_migrations(database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
