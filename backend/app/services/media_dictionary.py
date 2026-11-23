"""官方媒体字典 xlsx 解析、preview、apply 服务。

设计要点:
- **按表头名定位列,不按位置**。官方文件的列序是
  (媒体名称, 媒体分类, 注册域名),自家映射表是 (域名, 媒体名称, 媒体分类)
  —— 列序不同但表头名稳定。前端 UI 承诺「顺序不限」,这里兑现。
  按位置取列会把「媒体名称」当成域名,整份 1.8 万行文件全部 invalid_host。
- 遍历所有 sheet,取第一个能认出三列的;表头认不出 → 抛 ``ValueError``
  (API 层转 400 拒绝),不再按位置瞎猜。
- 全空白行(3 列都为空)静默跳过 —— openpyxl 在末尾会给出 None 行。
- 同 host 在 xlsx 内重复:第 1 条入 entries,第 2 条起记 invalid_rows
  ``duplicate_in_file``,**不抛错** —— 用户能在预览界面看到。
- host 全部 lowercased 写入数据库 —— 「Zhihu.com」与「zhihu.com」同义。
- 校验失败的行不进 entries,apply 时也不会插入(invalid_rows 仅作
  提示,不入库)。

不支持:``.xls``(老 binary 格式)、``openpyxl 不读 CSV``。
xlsx 上限 5MB(在 endpoint 层 enforce)。
"""

from __future__ import annotations

import io
import re
from typing import NamedTuple

import openpyxl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.media_dictionary import MediaDictionary
from app.schemas.media_dictionary import (
    MediaDictionaryEntry,
    MediaDictionaryImportPreview,
    MediaDictionaryImportResult,
    MediaDictionaryInvalidRow,
)


class RawRow(NamedTuple):
    row: int
    host: str
    media_name: str
    category: str


#: 表头别名 —— 角色 → 可接受的表头写法(归一化后比较)。
#: 「注册域名」是官方文件的写法,「域名」是自家映射表的写法,两个都要认。
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "host": ("域名", "注册域名", "网址", "链接", "url", "host", "domain"),
    "media_name": ("媒体名称", "媒体名", "名称", "media_name"),
    "category": ("媒体分类", "分类", "类别", "category"),
}


def parse_xlsx(content: bytes) -> list[RawRow]:
    """按表头名定位列后解析 —— 列序任意,表头认不出则抛 ``ValueError``。

    遍历所有 sheet,取第一个能认出「域名 / 媒体名称 / 媒体分类」三列的
    (不依赖 Excel 存的「当前激活 sheet」);数据行从表头下一行开始,
    ``RawRow.row`` 仍是 xlsx 的实际行号(表头占第 1 行)。

    全空白行(三列都为空字符串)静默跳过。其他无效行返回时保留,
    由 ``validate_row`` 决定是否入 entries。
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue
            index = _match_header(header)
            if index is None:
                continue
            out: list[RawRow] = []
            for row_no, row in enumerate(rows, start=2):
                host = _cell(row, index["host"])
                name = _cell(row, index["media_name"])
                cat = _cell(row, index["category"])
                if not host and not name and not cat:
                    continue  # 全空白行
                out.append(RawRow(row=row_no, host=host, media_name=name, category=cat))
            return out
        raise ValueError(
            "文件格式不正确:未识别到表头。请确认第 1 行含「域名」「媒体名称」"
            "「媒体分类」三列(列序任意;「域名」也可写作「注册域名」)。"
        )
    finally:
        wb.close()


def _norm_header(value: str) -> str:
    """归一化表头 —— 小写 + 去空格与常见标点,让「媒体/名称」「媒体 名称」等价。"""
    return re.sub(r"[\s()（）\[\]【】:：,，、/_\-]+", "", value).lower()


def _match_header(header: tuple) -> dict[str, int] | None:
    """按表头名定位 3 列,返回 ``{角色: 列号}``;认不出返回 ``None``。

    匹配口径:归一化后先精确匹配、再子串匹配(吃「网站注册域名」「URL/链接」
    这类写法)。三列必须落在**不同**列号上,否则视为没认出来。
    """
    cells = [(i, _norm_header(_cell(header, i))) for i in range(len(header))]
    index: dict[str, int] = {}
    for role, aliases in _HEADER_ALIASES.items():
        hit = next((i for i, name in cells if name in aliases), None)
        if hit is None:
            hit = next(
                (i for i, name in cells if any(a in name for a in aliases)), None
            )
        if hit is None or hit in index.values():
            return None
        index[role] = hit
    return index


def _cell(row, idx: int) -> str:
    if idx >= len(row):
        return ""
    v = row[idx]
    return (str(v).strip() if v is not None else "")


def validate_row(raw: RawRow) -> MediaDictionaryInvalidRow | None:
    """返回 None 表示行合法,否则返回 invalid 行(行号 + raw_host + reason)。"""
    if not raw.host:
        return MediaDictionaryInvalidRow(row=raw.row, raw_host="", reason="empty_host")
    # host 必须含 . 且不能含空白 —— 「知乎」「baidu」一类不是合法 host
    # (但作为 keyword 也可能存在,所以拒绝掉;用户应填「zhihu.com」)。
    if "." not in raw.host or any(c.isspace() for c in raw.host):
        return MediaDictionaryInvalidRow(row=raw.row, raw_host=raw.host, reason="invalid_host")
    if not raw.media_name:
        return MediaDictionaryInvalidRow(row=raw.row, raw_host=raw.host, reason="empty_name")
    if not raw.category:
        return MediaDictionaryInvalidRow(row=raw.row, raw_host=raw.host, reason="empty_category")
    return None


def preview_import(db: Session, content: bytes) -> MediaDictionaryImportPreview:
    """解析 + 校验 + 与数据库 diff,不写库。

    返回 entries(全部合法行)+ new_hosts/update_hosts(在 DB 视角的
    分桶)+ invalid_rows(校验失败的行,用户预览时看)。
    """
    raws = parse_xlsx(content)
    entries: list[MediaDictionaryEntry] = []
    invalids: list[MediaDictionaryInvalidRow] = []
    seen: set[str] = set()
    for raw in raws:
        err = validate_row(raw)
        if err is not None:
            invalids.append(err)
            continue
        host = raw.host.lower()
        if host in seen:
            invalids.append(
                MediaDictionaryInvalidRow(
                    row=raw.row, raw_host=raw.host, reason="duplicate_in_file"
                )
            )
            continue
        if len(host) > 255 or len(raw.media_name) > 128 or len(raw.category) > 64:
            invalids.append(
                MediaDictionaryInvalidRow(row=raw.row, raw_host=raw.host, reason="invalid_host")
            )
            continue
        seen.add(host)
        entries.append(
            MediaDictionaryEntry(host=host, media_name=raw.media_name, category=raw.category)
        )

    existing = {
        h for (h,) in db.execute(select(MediaDictionary.host)).all()
    }
    new_hosts = [e.host for e in entries if e.host not in existing]
    update_hosts = [e.host for e in entries if e.host in existing]
    return MediaDictionaryImportPreview(
        entries=entries,
        new_hosts=new_hosts,
        update_hosts=update_hosts,
        invalid_rows=invalids,
        total_parsed=len(raws),
    )


def apply_import(db: Session, content: bytes) -> MediaDictionaryImportResult:
    """调 preview_import,逐行 upsert by host,最后 commit。

    单事务内完成;失败自动 rollback —— 不会出现「插了一半」的中间态。
    2k 行量级 SQLite/MySQL 都秒级返回。
    """
    prev = preview_import(db, content)
    inserted = 0
    updated = 0
    existing = {
        r.host: r
        for r in db.execute(select(MediaDictionary).where(
            MediaDictionary.host.in_([e.host for e in prev.entries])
        )).scalars()
    }
    for entry in prev.entries:
        row = existing.get(entry.host)
        if row is not None:
            row.media_name = entry.media_name
            row.category = entry.category
            updated += 1
        else:
            db.add(
                MediaDictionary(
                    host=entry.host,
                    media_name=entry.media_name,
                    category=entry.category,
                )
            )
            inserted += 1
    db.commit()
    total = db.scalar(select(func.count()).select_from(MediaDictionary)) or 0
    return MediaDictionaryImportResult(
        inserted=inserted,
        updated=updated,
        skipped=0,
        total_in_dictionary=total,
    )
