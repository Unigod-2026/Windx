"""Fold pending-project workflow into ``geo_projects`` and drop the
``geo_pending_projects`` shadow table.

Revision ID: 20260908_0002
Revises: 20260908_0001
Create Date: 2026-09-08

背景
----
之前的「待审核」流程用单独的 ``geo_pending_projects`` 表 + 一组
``/api/pending-projects`` 路由,审批通过后才 ``INSERT`` 到 ``geo_projects``。
两表双份存储的痛点:

- 字段集 (``WizardPayload`` vs ``ProjectDetailOut``) 不一致,前端两边
  都要写一份 form state。
- 「已通过」后老 row 留在 pending 表里变成审计垃圾;删 pending row
  后又拿不回原 wizard payload。
- 改 UI 时 schema 改动要双份迁移。

从这次开始,所有项目都直接 ``INSERT`` 到 ``geo_projects``,通过 ``status``
区分审批生命周期。流程变成:

- customer_admin 提交 → ``POST /api/projects`` 写一行 ``status=pending``
- pending 期间一切字段保存在 ``geo_projects``;通过 ``PUT /api/projects/{id}/draft``
  覆盖 wizard payload(等价于之前的 PUT ``/api/pending-projects/{id}``)。
- super_admin ``POST /api/projects/{id}/approve`` → ``status`` 转 ``active``,
  ``approved_at`` / ``approved_by`` 落元信息。
- super_admin ``POST /api/projects/{id}/reject`` → ``status`` 转 ``rejected``,
  ``review_note`` 留底。
- customer_admin ``POST /api/projects/{id}/withdraw`` → 硬删除该行(只允许
  pending → 删;approved/rejected 保留作审计)。

变更
----
- ``geo_projects.status`` ENUM 新增 ``pending`` / ``rejected``(``active`` /
  ``disabled`` 含义不变)。
- ``geo_projects`` 新增 review 元信息列(全部 nullable):
    - ``review_note``: Text。驳回原因 / 备注。
    - ``submitted_by``: Integer。提交人 ``admin_users.id``。
    - ``submitted_at``: DateTime。提交时间。
    - ``reviewed_by``: Integer。审核人 ``admin_users.id``。
    - ``reviewed_at``: DateTime。审核时间(通过/驳回均落)。
    - ``approved_by`` / ``approved_at``: 同上,只有通过时落。
    - ``wizard_payload_json``: Text。customer_admin 提交的 wizard payload 原文
      (JSON 字符串),供审核时直接展示 + 审批保存时覆盖。
- ``geo_pending_projects`` 表 DROP(数据丢弃,无迁移脚本 —— 老 pending 行
  已经无业务价值,rejected 的 audit 信息之前也没怎么用)。

注意
----
本 migration 不强制把存量 ``active/disabled`` 项目填上 review 元信息;
``submitted_by`` / ``submitted_at`` 等允许 NULL,UI 在「无元信息」时直接
隐藏对应区块即可。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260908_0002"
down_revision = "20260908_0001"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    # 1. ``geo_projects.status`` ENUM 扩值。
    # MySQL 不允许 ``ALTER ENUM`` 直接加新值,需要 ``MODIFY COLUMN`` 整列
    # 重写一次。Sa ``mysql.ENUM`` 配合 ``existing_type`` 是规范做法。
    with op.batch_alter_table("geo_projects") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.Enum(
                "active", "disabled", name="project_status"
            ),
            type_=sa.Enum(
                "pending",
                "active",
                "rejected",
                "disabled",
                name="project_status",
            ),
            existing_nullable=False,
            nullable=False,
        )

    # 2. review 元信息列。
    with op.batch_alter_table("geo_projects", schema=None) as batch:
        batch.add_column(sa.Column("review_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("submitted_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("approved_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("wizard_payload_json", sa.Text(), nullable=True)
        )

    # 3. status 列加索引 —— 列表 / 待审核页会按 status 过滤。
    op.create_index(
        "ix_projects_status", "geo_projects", ["status"], unique=False
    )

    # 4. DROP 老表。注意 SQLite 测试库没有外键,直接 DROP 即可;生产 MySQL
    # 也无 FK 关联,稳妥。
    op.drop_table("geo_pending_projects")


def downgrade() -> None:
    # 1. 恢复老表(空 schema,数据已经丢了)。
    op.create_table(
        "geo_pending_projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=True),
        sa.Column("platform_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("approved_project_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        **MYSQL_OPTS,
    )

    # 2. 删索引 + 列。
    op.drop_index("ix_projects_status", table_name="geo_projects")
    with op.batch_alter_table("geo_projects") as batch:
        batch.drop_column("wizard_payload_json")
        batch.drop_column("approved_at")
        batch.drop_column("approved_by")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by")
        batch.drop_column("submitted_at")
        batch.drop_column("submitted_by")
        batch.drop_column("review_note")

    # 3. ENUM 收窄回原值。
    with op.batch_alter_table("geo_projects") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.Enum(
                "pending",
                "active",
                "rejected",
                "disabled",
                name="project_status",
            ),
            type_=sa.Enum("active", "disabled", name="project_status"),
            existing_nullable=False,
            nullable=False,
        )
