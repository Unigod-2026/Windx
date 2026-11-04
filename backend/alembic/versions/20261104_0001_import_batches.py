"""geo_import_batches：外部监控数据的导入批次表 + geo_tasks.import_batch_id。

背景：「数据导入」上线后暴露一个缺口 —— 导入出错了没法回看，写进去的
行也撤不回来。本迁移加一张批次表记录每次导入的结果，并让导入产生的
task 带上批次归属，从而支持精确撤销。

- **批次 = 一份文件内容 × 一个项目** —— id = sha256(project_id:file_hash)[:16]，
  同一份文件重复导入命中同一批次（upsert 同一批行），不产生重复数据。
- **JSON 列**用 MySQL 8 的表达式默认值（JSON_ARRAY() / JSON_OBJECT()）——
  MySQL 8 不允许 JSON 列带字面量默认值（与 20260924_0004 的 manual_overrides 同法）。
- **不加外键** —— 删 Project 行不 cascade 删本表（CLAUDE.md 约定）。

Revision ID: 20261104_0001
Revises: 20261008_0001
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261104_0001"
down_revision = "20261008_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_import_batches",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="failed"),
        sa.Column(
            "selected_sheets", sa.JSON(), nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
        ),
        sa.Column(
            "totals", sa.JSON(), nullable=False,
            server_default=sa.text("(JSON_OBJECT())"),
        ),
        sa.Column(
            "errors", sa.JSON(), nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
        ),
        sa.Column(
            "warnings", sa.JSON(), nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
        ),
        sa.Column(
            "dates", sa.JSON(), nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_import_batches_project_updated",
        "geo_import_batches",
        ["project_id", "updated_at"],
    )
    op.add_column(
        "geo_tasks",
        sa.Column("import_batch_id", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_tasks", "import_batch_id")
    op.drop_index("ix_import_batches_project_updated", table_name="geo_import_batches")
    op.drop_table("geo_import_batches")
