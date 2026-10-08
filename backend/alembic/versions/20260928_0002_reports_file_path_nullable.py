"""geo_reports.file_path 改为可空 —— 草稿用 NULL 表示「尚无渲染产物」。

背景:``file_path`` 上有 UNIQUE ``uq_reports_file_path``,而新建草稿时写
入的哨兵值是空串 ``''``。MySQL/SQLite 的 UNIQUE 都允许多个 NULL、但只
允许一个 ``''`` —— 于是只要库里存在一份从未发布的草稿,再建第二份就撞
``Duplicate entry '' for key 'geo_reports.uq_reports_file_path'``,生成
接口 500。

改为 NULL 之后:语义上「还没有文件」= NULL(而不是「名为空串的文件」),
多份草稿互不冲突,而约束对真正渲染出来的路径依旧生效(防止两份报告指向
同一个文件)。

升级时一并把已落库的空串转成 NULL —— 否则那个唯一的空串槽位仍被占着,
问题只是从「撞空串」变成「撞同一行」。

Revision ID: 20260928_0002
Revises: 20260928_0001
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260928_0002"
down_revision = "20260928_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "geo_reports",
        "file_path",
        existing_type=sa.String(512),
        nullable=True,
    )
    op.execute("UPDATE geo_reports SET file_path = NULL WHERE file_path = ''")


def downgrade() -> None:
    # 回退到 NOT NULL:NULL 只能落回空串。注意这一步假设库里最多只有
    # 一份未发布草稿 —— 旧 schema 无法表达「多份都没有文件」,多于一份时
    # 这里会因为 UNIQUE 冲突而失败,属于预期内的有损回退。
    op.execute("UPDATE geo_reports SET file_path = '' WHERE file_path IS NULL")
    op.alter_column(
        "geo_reports",
        "file_path",
        existing_type=sa.String(512),
        nullable=False,
    )
