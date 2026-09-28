"""geo_reports: 周报/报告生成历史表,周报 tab「历史报告一览」真源。

需求:周报 tab 由「实时指标看板」改为「历史报告一览」,报告生成
后会写入一行元数据,前端列表读这张表。HTML 文件本体存
``backend/data/reports/{project_id}/{report_id}.html``(约定路径,
无 env 配置),``file_path`` 记相对 backend/ 的相对路径。

数据流:
- 用户点「生成周报」→ ``POST /api/reports`` → 后端按 template_id 调
  ``services.report_templates`` 跑出 metrics dict → ``report_render``
  渲染 HTML 写到 ``backend/data/reports/{project_id}/{report_id}.html``
  → 写本表。
- 用户点列表项 → ``GET /api/reports/{report_id}/html``(受保护) →
  读 file_path + 鉴权(scope 到 project_id) → 返回 ``text/html``。

设计要点:
- **UNIQUE(file_path)** —— 同路径不能被两个 report 占用,防止后端
  并发生成时撞车(实际路径含 report_id 自带唯一性,但加约束是
  双保险 + DB 层信号)。
- **template_id** 用 String(64) —— 模板由 ``report_templates.TEMPLATES``
  字典注册,新模板加一行 key 即可,不用 alembic 改这张表。
- **period_start / period_end** 是 Date —— 周报口径按日,与「日级
  mention rate」的 DATE(Task.created_local_at) 对齐(Asia/Shanghai)。
- **baseline_date / baseline_rate** 拍快照存进元数据 —— setting.json
  里的 baseline 后续被改了,旧报告仍能展示「较基线」,不复用
  setting.json 的当前值。
- **generated_by** 是 AdminUser.id 字符串 + display_name(后者冗余是
  列表页不想 join 一次 user 表)—— User 行删了列表仍能展示生成人。
- **不上外键** —— 删 Project / User 行不 cascade 删本表(CLAUDE.md
  约定)。
- **ix_reports_project_generated** —— 列表 endpoint 按 project_id
  ORDER BY generated_at DESC LIMIT N 的覆盖索引。

Revision ID: 20260924_0001
Revises: 20260914_0002
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260924_0001"
down_revision = "20260914_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer, nullable=False),
        sa.Column("customer_id", sa.Integer, nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("baseline_date", sa.Date, nullable=True),
        sa.Column("baseline_rate", sa.Float, nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("generated_by_id", sa.Integer, nullable=False),
        sa.Column("generated_by_name", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("file_path", name="uq_reports_file_path"),
    )
    op.create_index(
        "ix_reports_project_generated",
        "geo_reports",
        ["project_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_reports_project_generated", table_name="geo_reports")
    op.drop_table("geo_reports")
