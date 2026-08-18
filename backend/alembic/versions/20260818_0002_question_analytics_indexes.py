"""question analytics 索引

Revision ID: 20260818_0002
Revises: 20260818_0001
Create Date: 2026-08-18

为问题提及分析按需加载加速(question analytics lazy loading):

- ``ix_subtasks_prompt_updated (prompt(191), updated_at)`` —
  ``GET /projects/{id}/question-analytics`` 按 prompt 取最新摘录时
  用 ``prompt`` 过滤 + ``ORDER BY updated_at DESC``;191 是 utf8mb4
  下 InnoDB 单列索引前缀上限,刚好把整列装进去。

- ``ix_brand_mentions_proj_self_prompt_created
  (project_id, is_self, prompt(191), created_at)`` —
  KPI 聚合按 ``project_id`` + ``is_self`` + ``prompt`` 收口窗口
  (``created_at >= ?``),前缀长度同上。
"""

from __future__ import annotations

from alembic import op


revision = "20260818_0002"
down_revision = "20260818_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    mysql_length = {"prompt": 191} if bind.dialect.name == "mysql" else None

    op.create_index(
        "ix_subtasks_prompt_updated",
        "geo_subtasks",
        ["prompt", "updated_at"],
        unique=False,
        mysql_length=mysql_length,
    )
    op.create_index(
        "ix_brand_mentions_proj_self_prompt_created",
        "geo_brand_mentions",
        ["project_id", "is_self", "prompt", "created_at"],
        unique=False,
        mysql_length=mysql_length,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brand_mentions_proj_self_prompt_created",
        table_name="geo_brand_mentions",
    )
    op.drop_index("ix_subtasks_prompt_updated", table_name="geo_subtasks")