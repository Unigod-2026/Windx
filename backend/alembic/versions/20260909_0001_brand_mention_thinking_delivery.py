"""geo_brand_mentions: add thinking_mode + delivery_mode for toolbar filters.

Revision ID: 20260909_0001
Revises: 20260908_0002
Create Date: 2026-09-09

背景
----
全局工具栏的「模式 / 终端」控件要把 KPI 收窄到特定子集:

- 模式:「快速 / 思考」分桶
    - fast  = Subtask.mode IN ('standard', 'search')
    - think = Subtask.mode IN ('reasoning', 'reasoning_search')
  历史遗留的 ``mode='web'`` 值(2026 年 8 月前的 1900 行数据)在枚举
  拆分前就是默认「非思考」桶,语义上属于 fast,因此归到 ``thinking_mode=False``。
- 终端:「PC / 移动端」分桶
    - web    = Subtask.platform NOT LIKE '%\\_mobile'
    - mobile = Subtask.platform LIKE '%\\_mobile'

把分桶结果落到 ``geo_brand_mentions`` 行上,让 ``project_overview``
能在不 JOIN Subtask 的前提下按桶过滤(已有的 ``BrandMention.platform``
也走的同款逻辑)。

Schema 设计
-----------
两列都保持 nullable —— 历史行的「未回填」和「新行未跑抽取」看起来一样,
都可以让上层按 NULL 显式过滤(暂时没用到,因为回填会覆盖全部存量)。
新增行走 :func:`app.services.extraction._load_context` 在写入时同步落
``thinking_mode`` / ``delivery_mode``,所以稳态下没有 NULL。

Backfill
--------
``geo_brand_mentions.subtask_id`` 与 ``geo_subtasks.subtask_id`` 一一对应,
直接 ``UPDATE ... JOIN`` 一次性回填全部存量。JOIN 用 ``INNER JOIN``:
若某行 BrandMention 找不到对应 Subtask(理论上不应发生 —— 抽取流程
总是先 upsert Subtask 再写 BrandMention),保留 NULL,后续 sync 自然补齐。

Downgrade
---------
两列直接 DROP。回填数据不需要回滚(Subtask 才是真源)。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260909_0001"
down_revision = "20260908_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns nullable — legacy rows without backfill will show as
    # NULL but won't break existing readers.
    with op.batch_alter_table("geo_brand_mentions") as batch:
        batch.add_column(
            sa.Column("thinking_mode", sa.Boolean(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "delivery_mode",
                sa.String(length=16),
                nullable=True,
            )
        )

    # Backfill from Subtask. mode 'web' is treated as fast (thinking_mode=0).
    # JOIN 用显式 ``COLLATE utf8mb4_0900_ai_ci`` —— ``geo_brand_mentions``
    # 走 ``utf8mb4_unicode_ci``(初始 schema 起的表),``geo_subtasks`` 在
    # ``20260810_0002`` 改名后落到 ``utf8mb4_0900_ai_ci``(MySQL 8 默认),
    # 不强制 COLLATE 的话 JOIN 会因 collation 不一致报 1267。
    op.execute(
        """
        UPDATE geo_brand_mentions bm
        INNER JOIN geo_subtasks st
            ON st.subtask_id = bm.subtask_id COLLATE utf8mb4_0900_ai_ci
        SET bm.thinking_mode = CASE
                WHEN st.mode IN ('reasoning', 'reasoning_search') THEN 1
                ELSE 0
            END,
            bm.delivery_mode = CASE
                WHEN st.platform LIKE '%\\_mobile' THEN 'mobile'
                ELSE 'web'
            END
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("geo_brand_mentions") as batch:
        batch.drop_column("delivery_mode")
        batch.drop_column("thinking_mode")
