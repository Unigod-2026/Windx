"""geo_reports 加 manual_overrides + is_published 列,支持运营编辑 + 发布。

设计要点:
- manual_overrides JSON NOT NULL server_default='{}' —— 旧报告行无需
  backfill,UI 展示为「未填」。
- is_published BOOL NOT NULL server_default=false —— 现有未发布的报告
  默认 false;发布后变 true;运营点「取消发布」回 false。
- 不重建索引 —— 两列都不参与 WHERE。

Revision ID: 20260924_0004
Revises: 20260924_0003
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0004"
down_revision = "20260924_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_reports",
        sa.Column(
            "manual_overrides",
            sa.JSON,
            nullable=False,
            # MySQL 8 forbids literal defaults on JSON columns; use the
            # ``(JSON_OBJECT())`` expression default (8.0.13+). The
            # bracketed form is the documented MySQL syntax for
            # expression defaults on BLOB/TEXT/JSON/GEOMETRY.
            server_default=sa.text("(JSON_OBJECT())"),
        ),
    )
    op.add_column(
        "geo_reports",
        sa.Column(
            "is_published",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_reports", "is_published")
    op.drop_column("geo_reports", "manual_overrides")