"""Scratch stub: add the `sensors` table for the sensor-card vertical slice.

Deliberately placed in migrations/ (NOT versions/): the real alembic chain
0001_initial -> 0003_event_knowhow in versions/ is untouched, so alembic
never sees this stub. Follows the same style as the real revisions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_add_sensors"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensors",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("sensor_id", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=8), nullable=False, server_default="C"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.UniqueConstraint("sensor_id", name="uq_sensors_sensor_id"),
    )


def downgrade() -> None:
    op.drop_table("sensors")
