"""geo_own_articles 增加 分发渠道(channel)列。

需求:自有文章引用分析的导入「管十项」升级 ——
xlsx 从三列(URL / 标题 / 发布日期)变成四列(再加「分发渠道」),
要求四列都不为空。

- **新增列**``channel VARCHAR(64) NOT NULL DEFAULT ''``;列名取 ``channel``
  是因为全仓库此前无「分发渠道」既有命名,简洁足够。64 字符覆盖所有常见渠道名。
- **空串 + NOT NULL** —— 307 行历史数据落空串,不让 ``NULL`` 污染 schema;
  UI 渲染时把空串显示为「—」。这是「不向历史行回填假数据」的策略
  (CLAUDE.md §3 「Touch only what you must」)。
- **不加索引 / 不改约束** —— 列表页按 id 倒序,不按 channel 查询。

Revision ID: 20260928_0001
Revises: 20260924_0004
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260928_0001"
down_revision = "20260924_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_own_articles",
        sa.Column(
            "channel",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_own_articles", "channel")