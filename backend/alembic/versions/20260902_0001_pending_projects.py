"""geo_pending_projects —— 多步新建项目向导的待审核提交表

Revision ID: 20260902_0001
Revises: 20260818_0002
Create Date: 2026-09-02

新建 ``geo_pending_projects`` 表,存 wizard 各步骤产物(JSON),供
super_admin 审核后落地为真实的 ``geo_projects`` + 关联配置行。

详见 ``app/models/pending.py``。该表刻意与 ``geo_projects`` 解耦:
- 审核前 payload 不一定能 1:1 翻译进现有 schema(比如每周 N 次 + 日期
  这类意图,需要 super_admin 在项目详情页配置 schedule);
- 审核流程需要审计字段(submitted_by / reviewed_by / review_note),
  不应污染主项目表。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260902_0001"
down_revision = "20260818_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_pending_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("brand_name", sa.String(255), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("platform_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="pending_project_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "submitted_by",
            sa.Integer(),
            sa.ForeignKey("geo_admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("geo_admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("approved_project_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_pending_projects_customer_id",
        "geo_pending_projects",
        ["customer_id"],
    )
    op.create_index(
        "ix_pending_projects_status",
        "geo_pending_projects",
        ["status"],
    )
    op.create_index(
        "ix_pending_projects_submitted_by",
        "geo_pending_projects",
        ["submitted_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_projects_submitted_by", table_name="geo_pending_projects"
    )
    op.drop_index("ix_pending_projects_status", table_name="geo_pending_projects")
    op.drop_index(
        "ix_pending_projects_customer_id", table_name="geo_pending_projects"
    )
    op.drop_table("geo_pending_projects")
