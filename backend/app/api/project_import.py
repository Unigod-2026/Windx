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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.projects import _assert_customer_access, _get_project
from app.db import get_db
from app.deps import get_current_user
from app.models.customer import AdminUser
from app.schemas.import_data import ImportPreviewOut, ImportResultOut
from app.services.import_monitor_data import (
    SHEET_KEYS,
    ImportConfigError,
    apply_import,
    preview_import,
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
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """解析 + 校验 + 聚合，不写库。可安全反复调用。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    content = await _read_xlsx(file)
    try:
        result = preview_import(db, project_id, content)
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
        return apply_import(db, project_id, content, selected)
    except ImportConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_sheets(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [key for key in keys if key not in SHEET_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown sheet key(s): {', '.join(unknown)}",
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
