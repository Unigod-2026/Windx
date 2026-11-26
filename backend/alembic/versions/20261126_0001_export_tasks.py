"""geo_export_tasks:后台导出任务表。

背景:监控数据导出(xlsx)在后台生成,耗时可达分钟级,HTTP 请求不能同步等。
这张表记录每次导出的状态与产物位置,前端「下载历史」tab 靠它展示任务列表
与下载入口。

- **不加外键** —— 删 Project 行不 cascade 删本表(CLAUDE.md 约定)。
- **JSON 列**用 MySQL 8 的表达式默认值(JSON_OBJECT())—— MySQL 8 不允许
  JSON 列带字面量默认值(与 20260924_0004 / 20261104_0001 同法)。
- 索引:列表按 (project_id, created_at) 查;worker 按 status 扫 pending。

Revision ID: 20261126_0001
Revises: 20261104_0002
Create Date: 2026-11-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261126_0001"
down_revision = "20261104_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_export_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "params_json", sa.JSON(), nullable=False,
            server_default=sa.text("(JSON_OBJECT())"),
        ),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_export_tasks_project_created",
        "geo_export_tasks",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_export_tasks_status",
        "geo_export_tasks",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_export_tasks_status", table_name="geo_export_tasks")
    op.drop_index(
        "ix_export_tasks_project_created", table_name="geo_export_tasks"
    )
    op.drop_table("geo_export_tasks")
