"""geo_media_dictionary: 全局官方媒体字典。

需求:对接参考页 docs/风球GEO监控平台UI/index.html 「导入官方媒体字典」
按钮 —— super_admin 上传 媒体名称映射表.xlsx,一次配置权威媒体白名单。
后续分类器接入后会优先命中本表(粒度比通用 _CITATION_DOMAIN_RULES 更
细,有 11 类细分行业分类),fallback 才是通用 substring 规则。

数据来源: ``docs/媒体名称映射表.xlsx`` sheet1 「URL→媒体名映射表」——
三列 (域名, 媒体名称, 媒体分类),~2451 行,11 类细分分类
(官方网站 / 医院媒体 / 医疗健康平台 / 医药学术文献 / 医药专业媒体 /
新闻门户 / 政府·行业协会 / 企业官网 / 社交内容 / 电商购物 / 其他)。

设计要点:
- **全局表,无 customer_id**:字典是「白名单」语义,所有项目共用一份。
  后续分类器接入时按 host UNIQUE 直接命中,不参与多租户隔离。
- **host UNIQUE**:导入是 upsert —— 已存在的 host 更新 media_name /
  category,新 host 插入。同一 host 在 xlsx 内出现多次时,preview 阶段
  报 duplicate_in_file 让用户知道。
- **不做 enum 限制 category**:字典可能演进,新增分类不需要 schema
  变更。category 走普通 VARCHAR(64),加二级索引加速后续按分类过滤。

Revision ID: 20260914_0001
Revises: 20260911_0002
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260914_0001"
down_revision = "20260911_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_media_dictionary",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("host", sa.String(255), nullable=False, unique=True),
        sa.Column("media_name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_geo_media_dictionary_category",
        "geo_media_dictionary",
        ["category"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_media_dictionary_category",
        table_name="geo_media_dictionary",
    )
    op.drop_table("geo_media_dictionary")
