"""Pydantic schemas for the 官方媒体字典 admin API.

三组响应类型:
- ``MediaDictionaryEntry`` — 列表 / 导出共用,3 列 (host, media_name, category)。
- ``MediaDictionaryImportPreview`` — POST /preview 返回,带 new vs update 分桶 + 无效行列表。
- ``MediaDictionaryImportResult`` — POST /import 返回,带 inserted / updated / 总数。
- ``MediaDictionaryListOut`` — GET / 列表的 wrapper(items + total)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MediaDictionaryEntry(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    media_name: str = Field(..., min_length=1, max_length=128)
    category: str = Field(..., min_length=1, max_length=64)


InvalidRowReason = Literal[
    "empty_host",
    "invalid_host",
    "empty_name",
    "empty_category",
    "duplicate_in_file",
]


class MediaDictionaryInvalidRow(BaseModel):
    """解析失败或重复的行 —— xlsx 1-based 行号(包含表头,数据行从 2 起)。"""

    row: int
    raw_host: str
    reason: InvalidRowReason


class MediaDictionaryImportPreview(BaseModel):
    entries: list[MediaDictionaryEntry]
    new_hosts: list[str]
    update_hosts: list[str]
    invalid_rows: list[MediaDictionaryInvalidRow]


class MediaDictionaryImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    total_in_dictionary: int


class MediaDictionaryListOut(BaseModel):
    items: list[MediaDictionaryEntry]
    total: int
