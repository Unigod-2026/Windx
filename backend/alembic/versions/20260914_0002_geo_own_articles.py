"""geo_own_articles: 项目自有文章声明表,供「自有文章引用分析」页面使用。

需求:参考页 docs/风球GEO监控平台UI/index.html:1293-1326
+ js/app.js:3026-3055 + js/data.js:702-709 —— 自有文章引用分析是独立
一级页面,7 列(文章/发布日期/是否被引用/引用次数/引用模型/最近引用/
引用提醒)。本表承载用户通过「导入 URL 列表」xlsx 声明的「自有 URL」,
后端再 join ``geo_subtasks.citation_list_json`` 计算每条引用次数 / 涉及
模型 / 最近一次引用时间。``remind`` boolean 是行级 toggle,不触发实际
通知(对照 index.html 提示文案「已开启引用提醒(页面内通知)」)。

数据来源:
- 输入:用户上传的 .xlsx(sheet1 三列 URL / 标题 / 发布日期)。
- 计算:``app.services.own_articles.compute_cite_stats`` 在 toolbar
  时间窗 + 模型过滤范围内统计。

设计要点:
- **(project_id, url) UNIQUE** —— 同一项目内同一 URL 不重复入库;不同
  项目可独立声明相同 URL。导入时已存在的 host 行更新 title /
  publish_date(remind 不重置)。
- **url 长度 512** —— MySQL InnoDB unique index 3072 byte 上限 = 4 字节/字符
  (utf8mb4)× 768 字符,扣掉 project_id (4 byte) 留余地,512 安全。
  Normalize 在 service 层做。
- **二级索引 ix_own_articles_project_id** —— 加速 list endpoint。
- **不做外键** —— 跨表关联列是普通 integer,删 Project 不 cascade 删
  own_articles 行(CLAUDE.md 约定)。

Revision ID: 20260914_0002
Revises: 20260914_0001
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260914_0002"
down_revision = "20260914_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_own_articles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer, nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("publish_date", sa.Date, nullable=True),
        sa.Column("remind", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("project_id", "url", name="uq_own_articles_project_url"),
    )
    op.create_index(
        "ix_own_articles_project_id",
        "geo_own_articles",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_own_articles_project_id", table_name="geo_own_articles")
    op.drop_table("geo_own_articles")
