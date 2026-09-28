"""geo_reports.scope_text: 报告生成时的筛选范围人话文字。

替代原本想要存的原始 JSON(platform_codes / prompts / period 三件套),
存成「近 7 天 · 5 档模型 · 8 个问题」这种文案。

设计要点:
- **NOT NULL + server_default=""** —— 旧报告行(0 行,本期迁移时尚未
  生成报告)无历史数据可 backfill,直接用空串兜底,UI 展示为「未指定」
  而不是 NULL 字符串。
- **VARCHAR(255)** —— 长度上限按 spec §2.5 的最坏情况(
  「自定义 YYYY-MM-DD ~ YYYY-MM-DD · NNN 档模型 · NNNN 个问题」
  ≈ 60 字节)给 4 倍余量。
- 不重建索引 —— 列表 endpoint 按 generated_at 排序,本列只在 SELECT
  列表里读,不上索引。

Revision ID: 20260924_0002
Revises: 20260924_0001
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0002"
down_revision = "20260924_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_reports",
        sa.Column(
            "scope_text",
            sa.String(255),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_reports", "scope_text")
