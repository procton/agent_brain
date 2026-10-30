"""initial tables: machines, sessions, events

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("first_seen_at", sa.String(length=40), nullable=False),
        sa.Column("last_seen_at", sa.String(length=40), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_session_id", sa.String(length=128), nullable=False),
        sa.Column("machine_id", sa.String(length=128), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("project_label", sa.String(length=200), nullable=True),
        sa.Column("display_title", sa.String(length=300), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("first_event_at", sa.String(length=40), nullable=True),
        sa.Column("last_activity_at", sa.String(length=40), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("latest_cursor", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "source", "machine_id", "source_session_id", name="uq_session_source"
        ),
    )
    op.create_index("ix_sessions_last_activity", "sessions", ["last_activity_at"])
    op.create_table(
        "events",
        sa.Column("cursor", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("machine_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.String(length=40), nullable=True),
        sa.Column("received_at", sa.String(length=40), nullable=False),
        sa.Column("correlation", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
    )
    op.create_index("ix_events_session_cursor", "events", ["session_id", "cursor"])
    op.create_index("ix_events_event_id", "events", ["event_id"], unique=True)
    op.create_table(
        "__schema_metadata__",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("__schema_metadata__")
    op.drop_index("ix_events_event_id", "events")
    op.drop_index("ix_events_session_cursor", "events")
    op.drop_table("events")
    op.drop_index("ix_sessions_last_activity", "sessions")
    op.drop_table("sessions")
    op.drop_table("machines")
