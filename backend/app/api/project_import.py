"""外部监控数据导入 API —— 项目级。

挂载点：``/api/projects/{project_id}/imports``（在 ``app.main`` 注册）。

端点：
- ``POST /preview``  (multipart file) — 解析 + 校验 + 聚合，**不写库**
- ``POST /apply``    (multipart file, ?sheets=) — 解析 + 校验 + 单事务落库

鉴权与租户范围：复用 ``app.api.projects`` 的 ``_get_project`` /
``_assert_customer_access``，保证与项目其它接口完全同口径（customer_admin
访问别的客户的项目 → 403；项目不存在 → 404）。

xlsx 限制：仅 ``.xlsx`` 后缀，上限 10MB（样本 1.1MB，但 5000+ 行要留余量）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.projects import _assert_customer_access, _get_project
from app.db import get_db
from app.deps import get_current_user
from app.models.customer import AdminUser
from app.models.import_batch import ImportBatch
from app.schemas.import_data import (
    ImportBatchDetailOut,
    ImportBatchListOut,
    ImportBatchSummary,
    ImportPreviewOut,
    ImportResultOut,
)
from app.services.import_monitor_data import (
    SHEET_KEYS,
    ImportConfigError,
    apply_import,
    compute_delete_impact,
    preview_import,
    undo_import,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/imports",
    tags=["project:import"],
)

_MAX_XLSX_BYTES = 10 * 1024 * 1024


@router.post("/preview", response_model=ImportPreviewOut)
async def preview(
    project_id: int,
    file: UploadFile = File(...),
    sheets: str | None = Query(None),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """解析 + 校验 + 聚合，不写库。可安全反复调用。

    ``?sheets=`` 传勾选的 sheet —— 前端切换勾选时重新预览，页面上的
    数字才跟实际要写入的量一致。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    content = await _read_xlsx(file)
    selected = _parse_sheets(sheets)
    try:
        result = preview_import(db, project_id, content, selected)
    except ImportConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 文件里一张可识别的 sheet 都没有 —— 明确报错，别让用户以为导了 0 行
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result.file_name = file.filename or ""
    return result


@router.post("/apply", response_model=ImportResultOut)
async def apply(
    project_id: int,
    file: UploadFile = File(...),
    sheets: str | None = Query(None),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """解析 + 校验 + 落库（单事务）。``?sheets=`` 缺省 = 三张全导。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    content = await _read_xlsx(file)
    selected = _parse_sheets(sheets)
    try:
        return apply_import(
            db,
            project_id,
            content,
            selected,
            file_name=file.filename or "",
            created_by=user.username or "",
        )
    except ImportConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_sheets(raw: str | None) -> list[str] | None:
    """``?sheets=answers,citations`` -> 列表；参数缺省 -> None（全导）。

    显式给了但解析出空列表（``?sheets=,``）→ 400，不让它静默变成「全导」。
    """
    if not raw:
        return None
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [key for key in keys if key not in SHEET_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown sheet key(s): {', '.join(unknown)}",
        )
    if not keys:
        raise HTTPException(
            status_code=400,
            detail="至少选择一张 sheet",
        )
    return keys


async def _read_xlsx(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="only .xlsx files supported")
    content = await file.read()
    if len(content) > _MAX_XLSX_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 10MB)")
    return content


@router.get("/batches", response_model=ImportBatchListOut)
def list_batches(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """批次列表 —— 按最近导入时间倒序。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    rows = db.execute(
        select(ImportBatch)
        .where(ImportBatch.project_id == project_id)
        .order_by(ImportBatch.updated_at.desc(), ImportBatch.id.desc())
    ).scalars().all()
    return ImportBatchListOut(
        items=[_to_batch_summary(row) for row in rows],
        total=len(rows),
    )


@router.get("/batches/{batch_id}", response_model=ImportBatchDetailOut)
def get_batch(
    project_id: int,
    batch_id: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """批次详情 —— 含完整错误清单与撤销影响统计。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    try:
        batch = db.get(ImportBatch, batch_id)
        if batch is None or batch.project_id != project_id:
            raise ImportConfigError(f"import batch {batch_id} not found")
        impact = compute_delete_impact(db, project_id, batch_id)
    except ImportConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ImportBatchDetailOut(
        **_to_batch_summary(batch).model_dump(),
        customer_id=batch.customer_id,
        file_hash=batch.file_hash,
        file_size=batch.file_size,
        selected_sheets=list(batch.selected_sheets or []),
        errors=list(batch.errors or []),
        warnings=list(batch.warnings or []),
        delete_impact=impact,
    )


@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(
    project_id: int,
    batch_id: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """撤销一次导入 —— 硬删它写入的全部行。不可撤销。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    try:
        undo_import(db, project_id, batch_id)
    except ImportConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


def _to_batch_summary(row: ImportBatch) -> ImportBatchSummary:
    return ImportBatchSummary(
        id=row.id,
        file_name=row.file_name,
        status=row.status,
        totals=dict(row.totals or {}),
        attempts=row.attempts,
        dates=list(row.dates or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
    )
