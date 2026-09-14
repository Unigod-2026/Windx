"""官方媒体字典 admin API —— 仅 super_admin 可访问。

挂载点:``/api/admin/media-dictionary``(在 ``app.main`` 注册)。

端点:
- ``GET  /``                          — 列表(全表返回,带 total)
- ``POST /preview``  (multipart file) — 解析 + 校验 + diff 现有 DB,不写库
- ``POST /import``   (multipart file) — 解析 + upsert,单事务完成

xlsx 限制:仅接受后缀 ``.xlsx``,文件大小不超过 5MB。openpyxl 的
read_only 模式一次性 IO,在内存中处理即可,不流式。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_super_admin
from app.models import AdminUser, MediaDictionary
from app.schemas.media_dictionary import (
    MediaDictionaryEntry,
    MediaDictionaryImportPreview,
    MediaDictionaryImportResult,
    MediaDictionaryListOut,
)
from app.services.media_dictionary import apply_import, preview_import

router = APIRouter(
    prefix="/api/admin/media-dictionary",
    tags=["admin:media-dictionary"],
)

_MAX_XLSX_BYTES = 5 * 1024 * 1024


@router.get("", response_model=MediaDictionaryListOut)
def list_dict(
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """列出全部字典条目。按 (category, host) 排序,方便按分类浏览。"""
    rows = (
        db.execute(
            select(MediaDictionary).order_by(MediaDictionary.category, MediaDictionary.host)
        )
        .scalars()
        .all()
    )
    return MediaDictionaryListOut(
        items=[
            MediaDictionaryEntry(host=r.host, media_name=r.media_name, category=r.category)
            for r in rows
        ],
        total=len(rows),
    )


@router.post("/preview", response_model=MediaDictionaryImportPreview)
async def preview_dict(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """解析 xlsx → 返回预览(合法行 + new/update 分桶 + 无效行)。

    不写库,只读,可在导入前安全反复调用。
    """
    content = await _read_and_validate(file)
    return preview_import(db, content)


@router.post("/import", response_model=MediaDictionaryImportResult)
async def import_dict(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """解析 + upsert(单事务),返回 inserted / updated / 总数。"""
    content = await _read_and_validate(file)
    return apply_import(db, content)


async def _read_and_validate(file: UploadFile) -> bytes:
    """公共入口校验:后缀必须 .xlsx,字节数不超过 5MB。"""
    name = (file.filename or "").lower()
    if not name.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="only .xlsx files supported")
    content = await file.read()
    if len(content) > _MAX_XLSX_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 5MB)")
    return content
