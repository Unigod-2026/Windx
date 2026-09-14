"""「自有文章引用分析」独立一级页面服务。

对应前端 ``/admin/projects/:id?tab=self-articles`` —— 7 列表格(文章 /
发布日期 / 是否被引用 / 引用次数 / 引用模型 / 最近引用 / 引用提醒)。

数据流:
1. 用户通过 xlsx 导入(URL / 标题 / 发布日期 三列)声明「自有文章」,
   写入 :class:`app.models.project.OwnArticle`。
2. ``compute_cite_stats`` 在 toolbar 时间窗 + 模型 + 问题过滤范围
   内,逐条读 :data:`Subtask.reference_list_json`(全信源池 —— AI 搜索
   返回的所有 references,不仅是回答正文里 cite 过的子集)、
   跟自有文章 normalize 后的 URL 做精确 join,产出 ``{cited, count,
   models, last_cited}``。

设计要点:
- **URL normalize** —— scheme + host 小写 + 去掉 path 尾斜杠。避免
  ``HTTP://Example.com/Path`` 与 ``http://example.com/path`` 被当成两条。
- **reference schema 平台异构** —— yuanbao 是 dict,其它是字符串,
  兼容方式照抄 :func:`app.api.projects.citation_analysis` (L3371-3397)。
- **remind 是单行 toggle,不级联** —— 不删 own_article 行即保留 reminder
  历史。
- **import 整事务** —— 跟 :mod:`app.services.media_dictionary` 同款,
  失败整体回滚。

不做:
- Fuzzy match(去掉 query string / path 后缀模糊匹配) —— 等用户反馈
  false negative 后再加。
- 真实通知(邮件 / 站内信) —— 跟 index.html 文案对齐,本期只存 boolean。
"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

import openpyxl
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from urllib.parse import urlparse

from app.models.common import now_local
from app.models.project import OwnArticle
from app.models.task import Subtask, Task
from app.schemas.project import (
    OwnArticleImportPreview,
    OwnArticleImportResult,
    OwnArticleIn,
    OwnArticleInvalidRow,
)


class RawRow(NamedTuple):
    row: int
    url: str
    title: str
    publish_date: date | None


def normalize_url(url: str) -> str:
    """URL → 用于 join 的 canonical key。

    规则(从严到宽,任一条都影响匹配结果):
    - scheme / host 小写
    - ``http://`` / ``https://`` 视为等价(站点常做 http→https 重定向,
      AI 抓到的版本可能跟用户上传的 scheme 不一致 —— 这是最常见的
      false negative)
    - 去 path 尾斜杠
    - 保留 query string(utm / ref 等营销参数仍会影响匹配,留作后续
      优化)
    - 无 scheme 时(``x.com/path``)按 http 兜底补齐
    - 真的是纯 path(没有 host 也没有 dot)则原样 lowercase 返回
    """
    s = (url or "").strip()
    if not s:
        return ""
    try:
        p = urlparse(s)
    except ValueError:
        return s.lower()
    if not p.netloc:
        if "://" not in s and "/" in s:
            try:
                p = urlparse("http://" + s)
            except ValueError:
                return s.lower()
        if not p.netloc:
            return s.lower()
    scheme = (p.scheme or "http").lower()
    if scheme in ("http", "https"):
        scheme = "https"
    host = p.netloc.lower()
    path = (p.path or "").rstrip("/")
    query = ("?" + p.query) if p.query else ""
    return f"{scheme}://{host}{path}{query}"


def parse_xlsx(content: bytes) -> list[RawRow]:
    """读 sheet1,跳过表头,只取前 3 列 (URL, 标题, 发布日期)。

    全空白行(3 列都为空)静默跳过。日期列可以是 ``date`` / ``datetime``
    实例,也可以是 ``YYYY-MM-DD`` 字符串;解析失败时落 ``None``。
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows: list[RawRow] = []
    try:
        for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if idx == 1:
                continue  # skip header
            url = _cell(row, 0)
            title = _cell(row, 1)
            pub = _parse_date(_cell(row, 2))
            if not url and not title and not pub:
                continue  # 全空白行
            rows.append(RawRow(row=idx, url=url, title=title, publish_date=pub))
    finally:
        wb.close()
    return rows


def _cell(row, idx: int) -> str:
    if idx >= len(row):
        return ""
    v = row[idx]
    return (str(v).strip() if v is not None else "")


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    # ISO 短格式 YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    # ISO 完整 datetime
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def validate_row(raw: RawRow) -> OwnArticleInvalidRow | None:
    """返回 None 表示行合法,否则返回 invalid 行。

    - 空 URL → ``empty_url``
    - URL 含空白 / 没 host → ``invalid_url``
    """
    if not raw.url:
        return OwnArticleInvalidRow(row=raw.row, raw_url="", reason="empty_url")
    if any(c.isspace() for c in raw.url):
        return OwnArticleInvalidRow(row=raw.row, raw_url=raw.url, reason="invalid_url")
    try:
        p = urlparse(raw.url.strip())
    except ValueError:
        return OwnArticleInvalidRow(row=raw.row, raw_url=raw.url, reason="invalid_url")
    if not p.netloc:
        return OwnArticleInvalidRow(row=raw.row, raw_url=raw.url, reason="invalid_url")
    return None


def preview_import(
    db: Session, project_id: int, content: bytes,
) -> OwnArticleImportPreview:
    """解析 + 校验 + 与 DB diff —— 不写库。

    - 文件内重复 URL(规范化后):后者覆盖前者,但 preview 时第二条报
      ``duplicate_in_file``,让用户能看到。
    - 数据库已存在(同 project_id + 规范化 URL):落 ``update_urls``。
    - 全新:落 ``new_urls``。
    """
    raws = parse_xlsx(content)
    entries: list[OwnArticleIn] = []
    invalids: list[OwnArticleInvalidRow] = []
    seen: set[str] = set()
    for raw in raws:
        err = validate_row(raw)
        if err is not None:
            invalids.append(err)
            continue
        norm = normalize_url(raw.url)
        if norm in seen:
            invalids.append(
                OwnArticleInvalidRow(row=raw.row, raw_url=raw.url, reason="duplicate_in_file")
            )
            continue
        seen.add(norm)
        entries.append(OwnArticleIn(url=raw.url, title=raw.title, publish_date=raw.publish_date))

    existing_norms = {
        normalize_url(a.url)
        for a in db.execute(select(OwnArticle).where(OwnArticle.project_id == project_id)).scalars()
    }
    new_urls = [e.url for e in entries if normalize_url(e.url) not in existing_norms]
    update_urls = [e.url for e in entries if normalize_url(e.url) in existing_norms]
    return OwnArticleImportPreview(
        entries=entries, new_urls=new_urls, update_urls=update_urls, invalid_rows=invalids,
    )


def apply_import(
    db: Session, project_id: int, content: bytes,
) -> OwnArticleImportResult:
    """调 preview_import,逐行 upsert by (project_id, normalize_url),最后 commit。

    - 命中已有行:更新 ``title`` / ``publish_date``,``remind`` 保留
      用户原有选择(不被 xlsx 覆盖)。
    - 新行:insert。
    - 单事务,失败整体回滚。
    """
    prev = preview_import(db, project_id, content)
    existing = {
        normalize_url(a.url): a
        for a in db.execute(select(OwnArticle).where(OwnArticle.project_id == project_id)).scalars()
    }
    inserted = 0
    updated = 0
    for entry in prev.entries:
        norm = normalize_url(entry.url)
        row = existing.get(norm)
        if row is not None:
            row.title = entry.title
            row.publish_date = entry.publish_date
            updated += 1
        else:
            db.add(OwnArticle(
                project_id=project_id,
                url=entry.url,
                title=entry.title,
                publish_date=entry.publish_date,
                remind=False,
            ))
            inserted += 1
    db.commit()
    total = db.scalar(
        select(func.count()).select_from(OwnArticle).where(OwnArticle.project_id == project_id)
    ) or 0
    return OwnArticleImportResult(
        inserted=inserted, updated=updated, skipped=0, total_in_project=int(total),
    )


def compute_cite_stats(
    db: Session, project_id: int, *,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    selected_platforms: list[str] | None = None,
    selected_prompt_texts: list[str] | None = None,
) -> dict[str, dict]:
    """逐条读 citation_list_json,按 URL normalize 后 group,返回
    ``{normalized_url: {count, models: set[str], last_cited: datetime}}``。

    注意:这函数**不直接返回** last_cited 字符串,last_cited_str 由调用方
    按需格式化(避免时区 / 格式漂移)。

    SQL 主干与 :func:`source_preferences._fetch_source_rows` 同款 join(读
    的就是同一列 ``reference_list_json``,全信源池口径一致)。
    """
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("start and end must be provided together")
        if end < start:
            raise ValueError("end must not be earlier than start")
        win_start, win_end = start, end
    else:
        if days < 1 or days > 90:
            raise ValueError("days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=days - 1)
        win_end = today

    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    stmt = (
        select(
            Subtask.reference_list_json,
            Subtask.platform,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    rows = db.execute(stmt).all()

    stats: dict[str, dict] = {}
    for refs, platform, created_at in rows:
        items = refs if isinstance(refs, list) else []
        if not items:
            continue
        for item in items:
            # Heterogeneous reference schema (跟 citation_analysis endpoint 同款):
            # - yuanbao returns dict: {url, site, title, ...}
            # - others return plain URL string
            if isinstance(item, dict):
                url = item.get("url") or item.get("link")
                if not isinstance(url, str):
                    continue
            elif isinstance(item, str):
                url = item
            else:
                continue
            url = url.strip()
            if not url:
                continue
            norm = normalize_url(url)
            bucket = stats.setdefault(norm, {"count": 0, "models": set(), "last_cited": None})
            bucket["count"] += 1
            if platform:
                bucket["models"].add(platform)
            if created_at and (bucket["last_cited"] is None or created_at > bucket["last_cited"]):
                bucket["last_cited"] = created_at
    return stats
