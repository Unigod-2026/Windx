"""导出任务 API —— 项目级 + 任务级。

挂载点:
- ``POST   /api/projects/{project_id}/exports``  —— 提交导出任务(202)
- ``GET    /api/projects/{project_id}/exports``  —— 任务列表
- ``GET    /api/exports/{task_id}``              —— 任务详情
- ``GET    /api/exports/{task_id}/download``     —— 下载 xlsx
- ``DELETE /api/exports/{task_id}``              —— 删任务 + 删文件

这里只做「建任务 / 查任务 / 发文件」,真正的 xlsx 生成跑在独立 worker 进程
(``app/services/export_worker.py``)里 —— 生成耗时可达分钟级,不能占着
HTTP 请求不放。

鉴权与租户范围:复用 ``app.api.projects`` 的 ``_get_project`` /
``_assert_customer_access``(customer_admin 访问别的客户的项目 → 403)。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.projects import _assert_customer_access, _get_project
from app.db import get_db
from app.deps import get_current_user
from app.models.customer import AdminUser
from app.models.export_task import ExportTask
from app.schemas.export import (
    ExportParamsIn,
    ExportTaskDetailOut,
    ExportTaskListOut,
    ExportTaskOut,
)
from app.services.export_query import ExportParamError, parse_export_params

logger = logging.getLogger("app.export")

router = APIRouter(prefix="/api", tags=["exports"])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _task_out(task: ExportTask) -> ExportTaskOut:
    return ExportTaskOut(
        id=task.id,
        project_id=task.project_id,
        status=task.status,
        file_name=task.file_name,
        file_size=task.file_size,
        error=task.error,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        file_expired=task.status == "success" and not task.file_path,
    )


def _get_task(db: Session, task_id: int) -> ExportTask:
    task = db.get(ExportTask, task_id)
    if task is None:
        raise HTTPException(404, "export task not found")
    return task


@router.post(
    "/projects/{project_id}/exports",
    response_model=ExportTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_export(
    project_id: int,
    body: ExportParamsIn,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """提交一个导出任务。生成在后台跑,这里立刻返回。

    同一项目同时只允许一个进行中的任务 —— 连点导出不会产生一堆重复文件。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    # 提交时就校验窗口 —— 不能等 worker 跑起来才失败,那样用户看到的是
    # 一个「生成失败」的任务,而不是当场告诉他日期范围写错了。
    try:
        parse_export_params(body.model_dump())
    except ExportParamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    running = db.execute(
        select(ExportTask).where(
            ExportTask.project_id == project_id,
            ExportTask.status.in_(("pending", "running")),
        )
    ).scalars().first()
    if running is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该项目已有导出任务在生成中,完成后可再次导出",
        )

    params = body.model_dump()
    task = ExportTask(
        project_id=project_id,
        customer_id=project.customer_id,
        status="pending",
        params_json=params,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(
        "source=export:submit task_id=%s project_id=%s user_id=%s",
        task.id, project_id, user.id,
    )
    return _task_out(task)


@router.get("/projects/{project_id}/exports", response_model=ExportTaskListOut)
def list_exports(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """任务列表 —— 按提交时间倒序。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    rows = db.execute(
        select(ExportTask)
        .where(ExportTask.project_id == project_id)
        .order_by(ExportTask.created_at.desc(), ExportTask.id.desc())
    ).scalars().all()
    return ExportTaskListOut(
        items=[_task_out(t) for t in rows], total=len(rows)
    )


@router.get("/exports/{task_id}", response_model=ExportTaskDetailOut)
def get_export(
    task_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    task = _get_task(db, task_id)
    project = _get_project(db, task.project_id)
    _assert_customer_access(user, project)
    detail = ExportTaskDetailOut(
        **_task_out(task).model_dump(), params=task.params_json or {}
    )
    return detail


@router.get("/exports/{task_id}/download")
def download_export(
    task_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """下载 xlsx。任务没成功 / 文件已过期 → 404。"""
    task = _get_task(db, task_id)
    project = _get_project(db, task.project_id)
    _assert_customer_access(user, project)
    if task.status != "success" or not task.file_path:
        raise HTTPException(404, "文件不可用")
    path = Path(task.file_path)
    if not path.exists():
        raise HTTPException(404, "文件不可用")
    return FileResponse(
        path,
        media_type=XLSX_MIME,
        filename=task.file_name or path.name,
    )


@router.delete("/exports/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_export(
    task_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """删任务 + 删文件。进行中的任务不给删(避免跟 worker 抢同一份文件)。"""
    task = _get_task(db, task_id)
    project = _get_project(db, task.project_id)
    _assert_customer_access(user, project)
    if task.status in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务正在生成中,无法删除",
        )
    if task.file_path:
        Path(task.file_path).unlink(missing_ok=True)
    db.delete(task)
    db.commit()
    logger.info(
        "source=export:delete task_id=%s user_id=%s", task_id, user.id
    )
