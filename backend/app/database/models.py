"""SQLite persistence for machines, sessions, and normalized events."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now_iso() -> str:
    """Current time as a UTC ISO-8601 string with second precision."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Base(DeclarativeBase):
    pass


class Machine(Base):
    """A local machine that produced events (metadata-only identity)."""

    __tablename__ = "machines"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    first_seen_at: Mapped[str] = mapped_column(String(40))
    last_seen_at: Mapped[str] = mapped_column(String(40))


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("source", "machine_id", "source_session_id", name="uq_session_source"),
        Index("ix_sessions_last_activity", "last_activity_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # backend uuid
    source: Mapped[str] = mapped_column(String(64))
    source_session_id: Mapped[str] = mapped_column(String(128))
    machine_id: Mapped[str] = mapped_column(String(128))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    project_label: Mapped[str | None] = mapped_column(String(200))
    display_title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)

    created_at: Mapped[str] = mapped_column(String(40))
    first_event_at: Mapped[str | None] = mapped_column(String(40))
    last_activity_at: Mapped[str | None] = mapped_column(String(40), index=False)
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latest_cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Event(Base):
    """A normalized event. `cursor` is the global replay-order sequence."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_session_cursor", "session_id", "cursor"),
        Index("ix_events_event_id", "event_id", unique=True),
    )

    cursor: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128))
    session_id: Mapped[str] = mapped_column(String(36))
    machine_id: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(64))
    source_event: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40))

    occurred_at: Mapped[str | None] = mapped_column(String(40))
    received_at: Mapped[str] = mapped_column(String(40))
    correlation: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    # Deterministic expertise labels computed at ingest time:
    # [{label, basis, rule_id, confidence, evidence_event_id}] (see classification/).
    expertise: Mapped[list | None] = mapped_column(JSON, nullable=True)


SCHEMA_VERSION_TABLE = "__schema_metadata__"


class SchemaMetadata(Base):
    """Rows tracking persisted schema versions, for future migrations."""

    __tablename__ = SCHEMA_VERSION_TABLE

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(64))
