"""导入批次 —— 外部监控数据每次导入的留痕与数据归属。

一个批次 = 「一份文件内容」×「一个项目」：
  id = sha256(f"{project_id}:{file_hash}")[:16]

同一份文件重复导入命中同一批次（upsert 同一批行），不产生重复数据；
批次行的 errors / warnings / totals 反映**最近一次**导入。

跨表关联列（geo_tasks.import_batch_id）都是普通列，不用 ForeignKey ——
删 Project 行不 cascade 删本表（CLAUDE.md「外键约定」）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import created_at_column, updated_at_column


class ImportBatch(Base):
    __tablename__ = "geo_import_batches"
    __table_args__ = (
        # 列表 endpoint: WHERE project_id = ? ORDER BY updated_at DESC
        Index("ix_import_batches_project_updated", "project_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 冗余一份，列表按租户过滤时不必 join projects
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 文件**内容**的 sha256 —— 同一份数据换个文件名重传仍是同一批次
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: success / partial / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="failed")
    selected_sheets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 本批次覆盖的监控日期（YYYY-MM-DD 列表）；0 行写入时也有值
    dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 同一批次被导入过几次
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
