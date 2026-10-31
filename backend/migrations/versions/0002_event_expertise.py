"""events.expertise JSON column for ingest-time classification labels.

Revision ID: 0002_event_expertise
Revises: 0001_initial
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_event_expertise"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("expertise", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "expertise")
