"""geo_project_platforms.mobile_code holds the resolved API platform string for
mobile-device rows (e.g. ``baiduai`` → ``baidu_mobile``). The mapping is NOT a
uniform ``+_mobile`` suffix, so the resolved code can't be derived on the
fly from ``platform`` and must be persisted alongside it.

Revision ID: 20260903_0001
Revises: 20260902_0001
Create Date: 2026-09-03

Adds:
- ``mobile_code`` (VARCHAR(32), nullable) on ``geo_project_platforms``. NULL on
  rows where the user picked the web (pc) surface; non-NULL only when
  ``delivery_mode = mobile``.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260903_0001"
down_revision = "20260902_0001"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.add_column(
            sa.Column("mobile_code", sa.String(32), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.drop_column("mobile_code")