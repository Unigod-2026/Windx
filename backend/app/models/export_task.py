"""导出任务 —— 后台生成的 xlsx 交付物留痕。

一个任务 = 「一次导出请求」×「一个项目」。提交时只落一行 ``pending``,
真正的 xlsx 生成由独立的 worker 进程(``app/services/export_worker.py``)
异步完成,所以这张表同时承担两个职责:

1. **任务状态机** —— ``pending`` → ``running`` → ``success`` / ``failed``。
   worker 用一条 UPDATE 原子抢占 pending 任务,多进程下也不会重复跑。
2. **交付物索引** —— ``file_path`` / ``file_name`` / ``file_size`` 指向
   ``backend/data/exports/{project_id}/`` 下落盘的文件。

跨表关联列(``project_id`` / ``customer_id`` / ``created_by``)都是普通列,
不用 ForeignKey —— 删 Project 行不 cascade 删本表(CLAUDE.md「外键约定」)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import created_at_column, updated_at_column


class ExportTask(Base):
    __tablename__ = "geo_export_tasks"
    __table_args__ = (
        # 列表 endpoint:WHERE project_id = ? ORDER BY created_at DESC
        Index("ix_export_tasks_project_created", "project_id", "created_at"),
        # worker 扫 pending 任务:WHERE status = 'pending' ORDER BY id
        Index("ix_export_tasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 冗余一份,列表按租户过滤时不必 join geo_projects。
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # pending / running / success / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    #: 提交时的筛选快照 —— {"date_range": {...}, "platforms": [...] | null,
    #: "prompt_ids": [...] | null}。快照而不是引用,是为了「重试」能拿到
    #: 当时那次的筛选条件,而不是用户现在工具栏上的选择。
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: 相对 backend/data/ 的路径;文件过了保留期被清理后置 NULL。
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 用户可读的失败原因(不含 traceback / 不含连接串)。
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    def __repr__(self) -> str:
        return (
            f"<ExportTask id={self.id!r} project_id={self.project_id!r} "
            f"status={self.status!r}>"
        )
