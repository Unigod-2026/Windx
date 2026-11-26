"""导出任务 API 的请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExportParamsIn(BaseModel):
    """提交导出任务时的筛选条件。

    ``date_range`` 二选一:``{"start","end"}`` 或 ``{"days"}``。
    ``platforms`` / ``prompt_ids`` 传 null 表示「不筛」。
    """

    date_range: dict = Field(default_factory=dict)
    platforms: list[str] | None = None
    prompt_ids: list[int] | None = None


class ExportTaskOut(BaseModel):
    """任务摘要 —— 列表和创建接口都返回它。"""

    id: int
    project_id: int
    status: str
    file_name: str | None = None
    file_size: int | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: 文件过了保留期被清理后为 true —— 前端显示「文件已过期」而不是「下载」。
    file_expired: bool = False


class ExportTaskListOut(BaseModel):
    items: list[ExportTaskOut]
    total: int


class ExportTaskDetailOut(ExportTaskOut):
    """任务详情 —— 额外带回提交时的筛选快照(「重试」要用)。"""

    params: dict = Field(default_factory=dict)
