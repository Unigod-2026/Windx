"""Switch ``geo_projects`` schedule model from 1-2 daily time slots to weekly
freq/days. Time-of-day is no longer per-project — it lives in env vars
(``MONITOR_DEFAULT_HOUR`` / ``MONITOR_DEFAULT_MINUTE``) so ops can shift
the run window in one place.

Revision ID: 20260903_0003
Revises: 20260903_0002
Create Date: 2026-09-03

Drops: ``slot1_hour``, ``slot1_minute``, ``slot2_hour``, ``slot2_minute``.
Adds: ``monitor_freq VARCHAR(8) NULL`` (w1/w2/wn) and ``monitor_days JSON
NULL`` (list of weekday keys "1".."7").
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260903_0003"
down_revision = "20260903_0002"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    with op.batch_alter_table("geo_projects") as batch:
        batch.add_column(
            sa.Column("monitor_freq", sa.String(8), nullable=True)
        )
        batch.add_column(
            sa.Column("monitor_days", sa.JSON(), nullable=True)
        )
        batch.drop_column("slot2_minute")
        batch.drop_column("slot2_hour")
        batch.drop_column("slot1_minute")
        batch.drop_column("slot1_hour")


def downgrade() -> None:
    with op.batch_alter_table("geo_projects") as batch:
        batch.add_column(
            sa.Column("slot1_hour", sa.SmallInteger(), nullable=True)
        )
        batch.add_column(
            sa.Column("slot1_minute", sa.SmallInteger(), nullable=True)
        )
        batch.add_column(
            sa.Column("slot2_hour", sa.SmallInteger(), nullable=True)
        )
        batch.add_column(
            sa.Column("slot2_minute", sa.SmallInteger(), nullable=True)
        )
        batch.drop_column("monitor_days")
        batch.drop_column("monitor_freq")