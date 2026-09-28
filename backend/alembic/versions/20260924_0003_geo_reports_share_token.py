"""geo_reports.share_token: 公开分享 URL 的不可枚举 token。

需求:周报预览页允许通过 ``/public/reports/{token}`` 直接访问,不需
要登录,链接可以发到微信给任何人(spec §3.4 + 后续分享决策)。

设计要点:
- **256-bit URL-safe random**(secrets.token_urlsafe(32))生成。
  32 字节 ≈ 43 字符 base64,枚举空间 2^256,实际不可枚举。
- **UNIQUE + NOT NULL** —— token 是公开 URL 的唯一凭证,不能重复,
  也不能缺失。
- **server_default="" 兼容旧行** —— 旧报告(目前 0 行,但迁移时仍要
  兼容)先落空串,后台脚本或下次 generate 时补;列表/分享逻辑读到
  空串视为"未分享"。
- 不上额外索引 —— token 已是 UNIQUE,B+树自动建索引;查询路径是
  ``WHERE share_token = ?``,命中唯一索引。

Revision ID: 20260924_0003
Revises: 20260924_0002
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0003"
down_revision = "20260924_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_reports",
        sa.Column(
            "share_token",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )
    op.create_unique_constraint(
        "uq_reports_share_token",
        "geo_reports",
        ["share_token"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_reports_share_token", "geo_reports", type_="unique")
    op.drop_column("geo_reports", "share_token")
