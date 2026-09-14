"""官方媒体字典 ORM model.

全局权威媒体白名单 —— 一个 host 在表里只能占一行(UNIQUE on host)。
由 super_admin 通过 xlsx 导入一次性配置;后续分类器接入后会优先
命中此表(粒度比 ``_CITATION_DOMAIN_RULES`` 更细,有 11 类细分行业分类)。

不在 customer / project 维度隔离:所有项目共用同一份字典。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import created_at_column, updated_at_column


class MediaDictionary(Base):
    __tablename__ = "geo_media_dictionary"
    __table_args__ = (
        Index("ix_geo_media_dictionary_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # host 已 lowercased 写入;UNIQUE 是 upsert key。
    host: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    media_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # xlsx 第 3 列原值,如「官方网站 / 医院媒体 / 医药学术文献」等。
    # 不做 enum —— 字典可能演进,新增分类不需要 schema 变更。
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
