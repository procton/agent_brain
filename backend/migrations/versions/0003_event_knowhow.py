"""events.knowhow JSON column for ingest-time technology tags (knowhow axis).

Revision ID: 0003_event_knowhow
Revises: 0002_event_expertise
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_event_knowhow"
down_revision = "0002_event_expertise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("knowhow", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "knowhow")
