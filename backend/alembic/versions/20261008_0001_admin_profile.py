"""geo_admin_users 加 email / phone / notification_prefs,支持「设置」页面真实落库。

背景:SettingsPane (frontend/src/pages/Projects/settings/SettingsPane.tsx) 之前
无后端 endpoint,只能 message.warning 提示用户「请联系超级管理员」。本迁移把
账号三件套存到 ``geo_admin_users``,让 PATCH /api/auth/me + POST /api/auth/change-password
两个新 endpoint 真的能写入。

三列都允许 NULL:历史账号没填,NULL = 「未设置」,UX 不会因为旧数据报错。
notification_prefs 用 String(2048) 存 JSON 文本(避免 MySQL 5.7 原生 JSON
类型兼容问题),application 层 parse。

Revision ID: 20261008_0001
Revises: 20260928_0003
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261008_0001"
down_revision = "20260928_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_admin_users",
        sa.Column("email", sa.String(128), nullable=True),
    )
    op.add_column(
        "geo_admin_users",
        sa.Column("phone", sa.String(32), nullable=True),
    )
    op.add_column(
        "geo_admin_users",
        sa.Column("notification_prefs", sa.String(2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_admin_users", "notification_prefs")
    op.drop_column("geo_admin_users", "phone")
    op.drop_column("geo_admin_users", "email")
