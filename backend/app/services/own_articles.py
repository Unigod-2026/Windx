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
import re
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

import openpyxl
from sqlalchemy import func, select, text
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
from app.services.source_preferences import _compound_platform, _expand_platform_keys


class RawRow(NamedTuple):
    row: int
    url: str
    title: str
    publish_date: date | None
    # 发布日期原始字符串 —— 用于区分「单元格空」与「单元格填了但解析失败」,
    # 让必填校验能给出准确的行级报错(后者属格式错而非缺值)。
    publish_raw: str
    channel: str


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
    """读 sheet1,跳过表头,取前 4 列 (URL, 标题, 发布日期, 分发渠道)。

    至少需要 4 列,不足直接 ``ValueError("文件格式不正确")`` —— 这是「必
    须有四列」的关卡,行级必填校验在 :func:`preview_import` 里。

    全空白行(4 列都为空)静默跳过;日期列可以是 ``date`` / ``datetime`` /
    ``YYYY-MM-DD`` 字符串,解析失败时 ``publish_date=None`` + ``publish_raw``
    保留原文本,留给必填校验区分「缺值」与「格式错」。
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    if ws.max_column < 4:
        raise ValueError("文件格式不正确:导入文件必须包含 4 列(URL、标题、发布日期、分发渠道)")
    rows: list[RawRow] = []
    try:
        for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if idx == 1:
                continue  # skip header
            url = _cell(row, 0)
            title = _cell(row, 1)
            pub_raw = _cell(row, 2)
            pub = _parse_date(pub_raw)
            channel = _cell(row, 3)
            if not url and not title and not pub_raw and not channel:
                continue  # 全空白行
            rows.append(RawRow(
                row=idx, url=url, title=title,
                publish_date=pub, publish_raw=pub_raw, channel=channel,
            ))
    finally:
        wb.close()
    return rows


def _cell(row, idx: int) -> str:
    if idx >= len(row):
        return ""
    v = row[idx]
    return (str(v).strip() if v is not None else "")


def _parse_date(s: str) -> date | None:
    """把 xlsx 单元格里的发布日期字符串解析成 ``date``。

    接受的短格式 ``YYYY[-/.]M[-/.]D`` —— ``-``/``/``/``.`` 三种分隔符 + 月日
    不强制零填充(办公场景常见 ``2026/9/1`` / ``2026.9.1``)。``date(y, m, d)``
    构造会自己检验月日范围,越界返回 ``None``。
    """
    if not s:
        return None
    s = s.strip()
    # 短日期 YYYY[-/.]M[-/.]D —— regex 兼顾分隔符与是否零填充;
    # Python 3.11 的 date.fromisoformat 不吃 `/` 和 `.`,所以不能直接复用。
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # 完整 datetime 字符串(``YYYY-MM-DD HH:MM:SS`` 或 ISO ``T`` 分隔)
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


# 必填列 → 中文显示名。Fatal 校验按这个表报「第 N 行<名称>为空」等。
_REQUIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("url", "URL"),
    ("title", "标题"),
    ("publish_date", "发布日期"),
    ("channel", "分发渠道"),
)


def _missing_required(raw: RawRow) -> list[str]:
    """返回该行缺失(或解析失败)的中文列名列表;空 = 通过。"""
    missing: list[str] = []
    if not raw.url.strip():
        missing.append("URL")
    if not raw.title.strip():
        missing.append("标题")
    # publish_date 用原始字符串 + 解析结果双判断:空 = 缺值;非空但解析失败
    # 也视为无效(单元格没日期不应形成合法行)。
    if raw.publish_date is None:
        missing.append("发布日期")
    if not raw.channel.strip():
        missing.append("分发渠道")
    return missing


def validate_row(raw: RawRow) -> OwnArticleInvalidRow | None:
    """返回 None 表示行合法,否则返回 invalid 行。

    只处理「跳过类」校验:URL 有值但没 host(整份不阻断,这一行从 entries
    排除);缺值校验由 :func:`_missing_required` 在 preview_import 一并
    收口成致命错误,不在这里处理。
    """
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

    - **致命校验**(整份不导入):任一行 URL / 标题 / 发布日期 / 分发渠道
      四列任一为空 → 抛 ``ValueError``,错误信息列出所有出错行号 + 列名。
      这是用户选的「逐行必填,缺值即整份失败」语义。
    - **跳过类校验**:`invalid_url`(有值但没 host)、``duplicate_in_file``
      跟之前一样,这些行不进 entries,其余正常入预览。
    - 数据库已存在(同 project_id + 规范化 URL):落 ``update_urls``。
    - 全新:落 ``new_urls``。
    """
    raws = parse_xlsx(content)
    # 致命关卡 —— 先于任何写库/跳过逻辑,确保任意一行的四列都非空。
    fatal_lines: list[str] = []
    for raw in raws:
        missing = _missing_required(raw)
        if missing:
            fatal_lines.append(f"第 {raw.row} 行「{'/'.join(missing)}」为空或无效")
    if fatal_lines:
        raise ValueError("导入失败,以下行四列(URL/标题/发布日期/分发渠道)缺一不可:\n" + "\n".join(fatal_lines))

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
        entries.append(OwnArticleIn(
            url=raw.url, title=raw.title,
            publish_date=raw.publish_date, channel=raw.channel,
        ))

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

    - 命中已有行:更新 ``title`` / ``publish_date`` / ``channel``,
      ``remind`` 保留用户原有选择(不被 xlsx 覆盖)。
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
            row.channel = entry.channel
            updated += 1
        else:
            db.add(OwnArticle(
                project_id=project_id,
                url=entry.url,
                title=entry.title,
                publish_date=entry.publish_date,
                channel=entry.channel,
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
    的就是同一列 ``reference_list_json``,全信源池口径一致),模型 / 问题
    两个 toolbar 筛选也照抄那套:``selected_platforms`` 是 compound key
    (``<code>__<delivery>__<thinking>``),先拆回 platform_code 进 SQL
    ``IN``,再按 compound key post-filter —— 同一 platform 的 fast / think
    是两个 key,只靠 ``platform IN`` 收不干净。
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

    # toolbar 「问题」筛选:Subtask 只存 prompt 文本,无 prompt_id 外键。
    # ``selected_prompt_texts`` 显式传空列表(全部 id 解析不到)= 不命中任何行。
    prompt_filter = (
        selected_prompt_texts if selected_prompt_texts is not None else None
    )
    # toolbar 「模型」筛选:先按 platform_code 收窄,再 post-filter。
    platform_codes: set[str] | None = None
    if selected_platforms is not None:
        platform_codes = _expand_platform_keys(selected_platforms)
    selected_compound_keys = set(selected_platforms) if selected_platforms else None

    # 派发:MySQL 走 JSON_TABLE 把 reference_list_json 数组展平 + 抽 url
    # 字段,只把 url 字符串传过来(其他字段从不用).SQLite / 通用路径继续
    # Python 端反序列化 JSON,行为完全等价。
    if db.bind is not None and db.bind.dialect.name == "mysql":
        rows = _cite_stats_rows_mysql(
            db,
            project_id=project_id,
            win_start_dt=win_start_dt,
            win_end_dt=win_end_dt,
            platform_codes=platform_codes,
            prompt_filter=prompt_filter,
        )
    else:
        rows = _cite_stats_rows_python(
            db,
            project_id=project_id,
            win_start_dt=win_start_dt,
            win_end_dt=win_end_dt,
            platform_codes=platform_codes,
            prompt_filter=prompt_filter,
        )

    # compound key post-filter(每个 subtask 一行,mode 跟 platform 同源)
    if selected_compound_keys is not None:
        rows = [
            (url, platform, mode, created_at)
            for url, platform, mode, created_at in rows
            if _compound_platform(platform, mode) in selected_compound_keys
        ]

    stats: dict[str, dict] = {}
    for url, platform, _mode, created_at in rows:
        if not url:
            continue
        norm = normalize_url(url.strip())
        if not norm:
            continue
        bucket = stats.setdefault(norm, {"count": 0, "models": set(), "last_cited": None})
        bucket["count"] += 1
        if platform:
            bucket["models"].add(platform)
        if created_at and (bucket["last_cited"] is None or created_at > bucket["last_cited"]):
            bucket["last_cited"] = created_at
    return stats


def _cite_stats_rows_mysql(
    db: Session, *,
    project_id: int,
    win_start_dt: datetime,
    win_end_dt: datetime,
    platform_codes: set[str] | None,
    prompt_filter: list[str] | None,
) -> list[tuple[str, str | None, str | None, datetime | None]]:
    """MySQL 路径:JSON_TABLE 展平 reference_list_json + COALESCE 抽 url。

    返回 ``(url, platform, mode, created_at)`` —— 每条 URL entry 一行,不再
    是 subtask 级。platform / mode 在 subtask 级是固定的,展开后自然每行
    继承。function 的 compound key post-filter 仍按 ``(platform, mode)``
    在 Python 里做(同一 platform 的 fast / think 是不同 key,纯 SQL 收不
    干净,见 :func:`source_preferences._compound_platform`)。
    """
    params: dict = {"pid": project_id, "ws": win_start_dt, "we": win_end_dt}
    where_extra = ""
    if platform_codes:
        where_extra += " AND s.platform IN :plats"
        params["plats"] = tuple(platform_codes)
    if prompt_filter is not None:
        where_extra += " AND s.prompt IN :prompts"
        params["prompts"] = tuple(prompt_filter)

    sql = text(
        """
        SELECT /*+ NO_MERGE(jt) */
          JSON_UNQUOTE(
            COALESCE(
              JSON_EXTRACT(jt.value, '$.url'),
              JSON_EXTRACT(jt.value, '$.link'),
              CASE WHEN JSON_TYPE(jt.value) = 'STRING' THEN jt.value ELSE NULL END
            )
          ) AS url,
          s.platform AS platform,
          s.mode AS mode,
          t.created_local_at AS created_at
        FROM geo_subtasks s
        JOIN geo_tasks t ON t.task_id = s.task_id
        CROSS JOIN JSON_TABLE(
          s.reference_list_json, '$[*]'
          COLUMNS (value JSON PATH '$')
        ) AS jt
        WHERE t.project_id = :pid
          AND t.created_local_at >= :ws
          AND t.created_local_at <= :we
          """ + where_extra + """
          AND (
            JSON_EXTRACT(jt.value, '$.url') IS NOT NULL
            OR JSON_EXTRACT(jt.value, '$.link') IS NOT NULL
            OR JSON_TYPE(jt.value) = 'STRING'
          )
        """
    )
    rows = db.execute(sql, params).all()
    return [(url, platform, mode, created_at) for url, platform, mode, created_at in rows]


def _cite_stats_rows_python(
    db: Session, *,
    project_id: int,
    win_start_dt: datetime,
    win_end_dt: datetime,
    platform_codes: set[str] | None,
    prompt_filter: list[str] | None,
) -> list[tuple[str, str | None, str | None, datetime | None]]:
    """SQLite / 通用路径:Python 端反序列化 reference_list_json。

    与 MySQL 路径结果完全等价,只是慢一些(主要是 JSON 反序列化 + 整 blob
    传输)。生产 MySQL 走 ``_cite_stats_rows_mysql``,测试 SQLite 走这里。
    """
    stmt = (
        select(
            Subtask.reference_list_json,
            Subtask.platform,
            Subtask.mode,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    if prompt_filter is not None:
        stmt = stmt.where(Subtask.prompt.in_(prompt_filter))
    if platform_codes:
        stmt = stmt.where(Subtask.platform.in_(platform_codes))

    out: list[tuple[str, str | None, str | None, datetime | None]] = []
    for refs, platform, mode, created_at in db.execute(stmt).all():
        if not isinstance(refs, list):
            continue
        for item in refs:
            if isinstance(item, dict):
                url = item.get("url") or item.get("link")
                if not isinstance(url, str):
                    continue
            elif isinstance(item, str):
                url = item
            else:
                continue
            out.append((url.strip(), platform, mode, created_at))
    return out
