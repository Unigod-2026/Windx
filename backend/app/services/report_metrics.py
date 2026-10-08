"""Aggregation queries for the weekly report surface.

All mention-rate stats come from ``geo_brand_mentions`` only — no JOIN
to ``Subtask`` / ``Task`` / ``Project``. BrandMention carries its own
``project_id`` / ``platform`` / ``prompt`` / ``created_at`` copies, so
the metrics layer doesn't need parent-table lookups for the common
project-self queries (``is_self = 1``).

Definitions (2026-09 product decision):
- ``mentioned`` = ``BrandMention.is_mention == 1`` for the project's
  self brand (filter: ``is_self = 1``).
- ``total`` = ``BrandMention`` rows where ``is_self = 1`` AND
  ``extract_status != PENDING``. PENDING rows are mid-pipeline and
  shouldn't influence the rate; SUCCESS / FAILED / SKIPPED all
  represent "extraction finished, here's the verdict".
- ``rate`` = ``mentioned / total``.

Why drop the SUCCESS-only filter:
- The original SUCCESS-only metric counted "LLM successfully
  processed" — not "brand was mentioned". That's a *pipeline* metric,
  not a *mention* metric. Operators looking at "本周提及率" want the
  latter. ``is_mention`` is the regex verdict: 1 if the brand needle
  matched the answer, 0 if not. That's the mention signal.
- This also simplifies the data dependency: every operator-relevant
  report metric now reads a single table.

Grouping & timezone:
- We bucket by ``DATE(BrandMention.created_at)`` — i.e. the Shanghai
  wall-clock day the row was written. ``created_at`` is a naive
  ``DateTime`` filled by ``now_local()`` (Asia/Shanghai), so
  ``DATE()`` lands on the operator's Shanghai day — see
  ``models/common.py`` and CLAUDE.md §6.

Filter plumbing:
- ``platform_codes`` is a list of raw ``BrandMention.platform``
  strings (``doubao`` / ``doubao_mobile`` etc.).
- ``prompts`` is a list of prompt *strings* (not ids). BrandMention
  stores the literal prompt text — same shape as Subtask used to.
- ``None`` for either means "no filter" (all rows).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Sequence, cast

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.models.enums import ExtractStatus
from app.models.project import BrandMention, OwnArticle, ProjectPrompt
from app.models.task import Subtask, Task
from app.services.own_articles import normalize_url
from app.services.platform_labels import platform_label_for_code


def _apply_filters(
    stmt,
    *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
):
    """AND-in the project / window / platform / prompt filters on a
    BrandMention-only query. ``prompts`` is a list of prompt *strings*
    (BrandMention.prompt stores the literal prompt text).
    """
    stmt = stmt.where(BrandMention.project_id == project_id)
    stmt = stmt.where(BrandMention.created_at >= window_start)
    stmt = stmt.where(BrandMention.created_at < window_end_exclusive)
    if platform_codes:
        stmt = stmt.where(BrandMention.platform.in_(platform_codes))
    if prompts:
        stmt = stmt.where(BrandMention.prompt.in_(prompts))
    return stmt


def daily_mention_rate(
    db: Session,
    *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> list[dict]:
    """Per-day mention rate for the requested window.

    Returns a list of ``{date, total, mentioned, rate}`` dicts sorted by
    date ascending.  Days with zero rows are **omitted** — the UI fills
    gaps from the requested window so we don't accidentally report
    "missing data" as "0% mentioned".

    Single-table read on ``geo_brand_mentions`` (see module docstring):
    - ``total`` = rows where ``is_self=1 AND extract_status != PENDING``
    - ``mentioned`` = rows where additionally ``is_mention=1``
    - ``rate = mentioned / total``
    """
    day_col = func.date(BrandMention.created_at).label("day")
    mentioned_count = func.sum(
        case((BrandMention.is_mention == 1, 1), else_=0)
    ).label("mentioned")
    total_count = func.count(BrandMention.id).label("total")

    base = select(day_col, total_count, mentioned_count).where(
        BrandMention.is_self == True,
        BrandMention.extract_status != ExtractStatus.PENDING,
    )
    base = _apply_filters(
        base,
        project_id=project_id,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        platform_codes=platform_codes,
        prompts=prompts,
    )
    base = base.group_by(day_col).order_by(day_col.asc())

    rows = db.execute(base).all()
    out: list[dict] = []
    for day, total, mentioned in rows:
        total = int(total or 0)
        mentioned = int(mentioned or 0)
        out.append(
            {
                "date": day,
                "total": total,
                "mentioned": mentioned,
                "rate": (mentioned / total) if total else 0.0,
            }
        )
    return out


def platform_breakdown(
    db: Session,
    *,
    project_id: int,
    current_start: date,
    current_end_exclusive: date,
    previous_start: date,
    previous_end_exclusive: date,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> list[dict]:
    """Per-平台 × 终端 × 模式 的当前 vs 上周期 提及率。

    3.1 章节每个组合一行(例:千问-网页-快速 / 千问-移动-思考),
    列:AI平台 / 当前周期 / 上周期 / 周环比。

    Returns one row per (platform, delivery_mode, thinking_mode)
    combination. Each row carries:
    - all-mode aggregate (current_total/mentioned/rate 等) 用于汇总
    - per-mode 各项(虽然现在每行就是一种 mode,字段保留向后兼容)

    Both windows must be the same length; the caller (``reports``
    router) computes ``previous_*`` by subtracting ``(current_end -
    current_start)`` days from ``current_start``.
    """
    def _agg() -> dict:
        return {"total": 0, "mentioned": 0, "rate": 0.0}

    def _key(platform, delivery, thinking):
        # 老数据 delivery/thinking 是 NULL —— 落到 web/fast,UI 标 "网页"/"快速"
        d = (delivery or "web").lower()
        t = "think" if thinking else "fast"
        return (platform or "", d, t)

    def _query(start: date, end: date):
        platform_col = BrandMention.platform.label("platform")
        delivery_col = BrandMention.delivery_mode.label("delivery_mode")
        thinking_col = BrandMention.thinking_mode.label("thinking_mode")
        mentioned_count = func.sum(
            case((BrandMention.is_mention == 1, 1), else_=0)
        ).label("mentioned")
        total_count = func.count(BrandMention.id).label("total")
        base = (
            select(
                platform_col,
                delivery_col,
                thinking_col,
                total_count,
                mentioned_count,
            ).where(
                BrandMention.is_self == True,
                BrandMention.extract_status != ExtractStatus.PENDING,
            )
        )
        base = _apply_filters(
            base,
            project_id=project_id,
            window_start=start,
            window_end_exclusive=end,
            platform_codes=platform_codes,
            prompts=prompts,
        )
        base = base.group_by(platform_col, delivery_col, thinking_col)
        return base

    def _pack(rows) -> dict:
        out: dict[tuple, dict] = {}
        for platform, delivery, thinking, total, mentioned in rows:
            key = _key(platform, delivery, thinking)
            total = int(total or 0)
            mentioned = int(mentioned or 0)
            out[key] = {
                "total": total,
                "mentioned": mentioned,
                "rate": (mentioned / total) if total else 0.0,
            }
        return out

    cur = _pack(db.execute(_query(current_start, current_end_exclusive)).all())
    prev = _pack(db.execute(_query(previous_start, previous_end_exclusive)).all())

    all_keys = list(dict.fromkeys(list(cur.keys()) + list(prev.keys())))
    out: list[dict] = []
    for k in all_keys:
        platform, delivery, thinking = k
        c = cur.get(k, _agg())
        pv = prev.get(k, _agg())
        # 同时保留旧的 fast/think 字段(向后兼容,3.1 现不用)
        c_fast = c if thinking == "fast" else _agg()
        c_think = c if thinking == "think" else _agg()
        p_fast = pv if thinking == "fast" else _agg()
        p_think = pv if thinking == "think" else _agg()
        out.append(
            {
                "platform_code": platform,
                "delivery_mode": delivery,
                "thinking_mode": thinking,
                # 当前周期
                "current_total": c["total"],
                "current_mentioned": c["mentioned"],
                "current_rate": c["rate"],
                # 上周期
                "previous_total": pv["total"],
                "previous_mentioned": pv["mentioned"],
                "previous_rate": pv["rate"],
                # 周环比(用当前 rate - 上期 rate,本身就是 pp)
                "delta_pp": c["rate"] - pv["rate"],
                # 向后兼容:每行的 fast/think 字段就是当前 mode 的值
                "current_fast_mentioned": c_fast["mentioned"],
                "current_fast_total": c_fast["total"],
                "current_fast_rate": c_fast["rate"],
                "current_think_mentioned": c_think["mentioned"],
                "current_think_total": c_think["total"],
                "current_think_rate": c_think["rate"],
                "previous_fast_mentioned": p_fast["mentioned"],
                "previous_fast_total": p_fast["total"],
                "previous_fast_rate": p_fast["rate"],
                "previous_think_mentioned": p_think["mentioned"],
                "previous_think_total": p_think["total"],
                "previous_think_rate": p_think["rate"],
                "delta_fast": c_fast["rate"] - p_fast["rate"],
                "delta_think": c_think["rate"] - p_think["rate"],
            }
        )
    return out


def fill_window_gaps(
    daily: list[dict], start: date, end_exclusive: date
) -> list[dict]:
    """Insert zero-rate placeholders for days with no rows.

    The DB query only returns days that have at least one row; the
    chart wants a continuous series.  We pad gaps with total=0 so the
    line doesn't break and the operator sees the real on/off rhythm.
    """
    by_day = {row["date"]: row for row in daily}
    out: list[dict] = []
    cursor = start
    while cursor < end_exclusive:
        row = by_day.get(cursor)
        if row is None:
            out.append(
                {"date": cursor, "total": 0, "mentioned": 0, "rate": 0.0}
            )
        else:
            out.append(row)
        cursor = cursor + timedelta(days=1)
    return out


def weekly_changes(
    db: Session, *,
    project_id: int,
    current_start: date, current_end_exclusive: date,
    previous_start: date, previous_end_exclusive: date,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> dict:
    """Four-quadrant classification of prompt mention coverage change.

    For each prompt in the project's configured set, count distinct
    platforms that mentioned the project's brand in each window,
    then bucket:

    - new_mentions: 0 platforms in previous, >=1 in current (newly broken).
    - increased: count went up by >=1 AND previous was >=1.
    - decreased: count went down by >=1 AND current is >=1.
    - lost_mentions: >=1 platforms in previous, 0 in current (fully lost).

    Every entry carries ``from`` / ``to`` (the per-window platform
    counts) so the 5.2 表格 can render "0→1 平台" / "2→0 平台"
    uniformly across all four buckets.

    A prompt in neither bucket is "stable" and not surfaced here —
    the consumer infers "stable" from "not in any list".
    """
    proj_prompts = db.execute(
        select(ProjectPrompt.id, ProjectPrompt.prompt).where(
            ProjectPrompt.project_id == project_id,
            # 同 prompt_platform_matrix:只对运营 toolbar 里选中的 prompt 做
            # 5.2 四象限分类(参见 report_templates.py 矩阵段的注释)。
            *([ProjectPrompt.prompt.in_(prompts)] if prompts else []),
        ).order_by(ProjectPrompt.sort)
    ).all()
    if not proj_prompts:
        return {"new_mentions": [], "increased": [], "decreased": [], "lost_mentions": []}
    prompt_id_by_text = {p.prompt: p.id for p in proj_prompts}

    def _count_platforms(start: date, end: date) -> dict[int, set[str]]:
        stmt = (
            select(BrandMention.prompt, BrandMention.platform)
            .where(
                BrandMention.project_id == project_id,
                BrandMention.is_self == True,
                BrandMention.is_mention == 1,
                BrandMention.extract_status != ExtractStatus.PENDING,
                BrandMention.created_at >= start,
                BrandMention.created_at < end,
                BrandMention.prompt.in_(prompt_id_by_text.keys()),
                *([BrandMention.platform.in_(platform_codes)] if platform_codes else []),
                *([BrandMention.prompt.in_(prompts)] if prompts else []),
            )
        )
        out: dict[int, set[str]] = {pid: set() for pid in prompt_id_by_text.values()}
        for prompt_text, platform in db.execute(stmt).all():
            pid = prompt_id_by_text.get(prompt_text)
            if pid is not None:
                out[pid].add(platform)
        return out

    prev = _count_platforms(previous_start, previous_end_exclusive)
    cur = _count_platforms(current_start, current_end_exclusive)

    new_mentions: list[dict] = []
    increased: list[dict] = []
    decreased: list[dict] = []
    lost_mentions: list[dict] = []

    for pid, _text in [(p.id, p.prompt) for p in proj_prompts]:
        p_count = len(prev.get(pid, set()))
        c_count = len(cur.get(pid, set()))
        text = prompt_id_by_text and {v: k for k, v in prompt_id_by_text.items()}.get(pid) or ""
        if p_count == 0 and c_count >= 1:
            new_mentions.append({
                "prompt_id": pid, "prompt_text": text,
                "from": 0, "to": c_count,
            })
        elif p_count >= 1 and c_count == 0:
            lost_mentions.append({
                "prompt_id": pid, "prompt_text": text,
                "from": p_count, "to": 0,
            })
        elif c_count > p_count and p_count >= 1:
            increased.append({
                "prompt_id": pid, "prompt_text": text,
                "from": p_count, "to": c_count,
            })
        elif c_count < p_count and c_count >= 1:
            decreased.append({
                "prompt_id": pid, "prompt_text": text,
                "from": p_count, "to": c_count,
            })

    return {
        "new_mentions": new_mentions,
        "increased": increased,
        "decreased": decreased,
        "lost_mentions": lost_mentions,
    }


def zero_mention_prompts(
    db: Session, *, project_id: int, since_date: date,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> list[dict]:
    """Prompts with no successful brand mention across the window.

    Lists the configured prompts that produced zero rows in
    ``geo_brand_mentions`` for the project's brand between
    ``since_date`` and today. Sorted by ``ProjectPrompt.sort`` so the
    output is stable across runs.

    Edge case: a prompt that wasn't run at all (no BrandMention row
    either — pipeline didn't get to it) is included by virtue of
    "no row in the result set" — "didn't run" and "ran but wasn't
    mentioned" are both "no mention in the window", which is the
    operator's question.
    """
    proj_prompts = db.execute(
        select(ProjectPrompt.id, ProjectPrompt.prompt).where(
            ProjectPrompt.project_id == project_id,
            # 同 prompt_platform_matrix / weekly_changes:5.1「零提及」只
            # 列出 toolbar 选中的 prompt 里未被提及的那些。
            *([ProjectPrompt.prompt.in_(prompts)] if prompts else []),
        ).order_by(ProjectPrompt.sort)
    ).all()
    if not proj_prompts:
        return []
    prompt_texts = [p.prompt for p in proj_prompts]
    prompt_id_by_text = {p.prompt: p.id for p in proj_prompts}

    stmt = (
        select(BrandMention.prompt)
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_self == True,
            BrandMention.is_mention == 1,
            BrandMention.extract_status != ExtractStatus.PENDING,
            BrandMention.created_at >= since_date,
            BrandMention.prompt.in_(prompt_texts),
            *([BrandMention.platform.in_(platform_codes)] if platform_codes else []),
            *([BrandMention.prompt.in_(prompts)] if prompts else []),
        )
        .group_by(BrandMention.prompt)
    )
    mentioned_texts = set(db.execute(stmt).scalars())
    return [
        {"prompt_id": prompt_id_by_text[t], "prompt_text": t}
        for t in prompt_texts
        if t not in mentioned_texts
    ]


def weekly_post_count(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
) -> int:
    """独立标题数 = 周窗口内 ``geo_own_articles.title`` 的 distinct 非空值数。

    同一篇文章标题可能分发到多个渠道(URL 不同)→ 多行 OwnArticle → 按
    ``title`` 去重才是「这周发了多少篇文章」。行数走
    :func:`weekly_distribution_count`(两个 KPI 各自有独立含义)。

    空字符串是 schema 默认值(导入时未填标题),不算独立标题。
    0 行 → 0(不是 None),便于前端 KPI 始终显示数字。
    """
    stmt = (
        select(func.count(func.distinct(OwnArticle.title)))
        .where(
            OwnArticle.project_id == project_id,
            OwnArticle.publish_date >= window_start,
            OwnArticle.publish_date < window_end_exclusive,
            OwnArticle.title != "",
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def weekly_distribution_count(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
) -> int:
    """分发次数 = 周窗口内 ``geo_own_articles`` 行数(每行 = 一次分发动作)。

    不去重:同一文章标题走多渠道 = 多次。这是 KPI 卡片 2 「20次分发」的
    数字来源,与 :func:`weekly_post_count`(独立标题)对应「7 篇」。
    """
    stmt = (
        select(func.count(OwnArticle.id))
        .where(
            OwnArticle.project_id == project_id,
            OwnArticle.publish_date >= window_start,
            OwnArticle.publish_date < window_end_exclusive,
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def weekly_channel_count(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
) -> int:
    """4.x KPI 「分发渠道数」= 窗口内 ``geo_own_articles.channel`` 的 distinct 非空值数。

    空串(``""``)是迁移 ``20260928_0001`` 的 server_default,代表「导入时未填渠道」
    的历史行,不算一个独立渠道。0 行 → 0(不是 None),便于前端 KPI 始终显示数字。
    """
    stmt = (
        select(func.count(func.distinct(OwnArticle.channel)))
        .where(
            OwnArticle.project_id == project_id,
            OwnArticle.publish_date >= window_start,
            OwnArticle.publish_date < window_end_exclusive,
            OwnArticle.channel != "",
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def weekly_self_article_citation_count(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    platform_codes: Sequence[str] | None = None,
    prompts: Sequence[str] | None = None,
) -> int:
    """4.x KPI 「自有文章被 AI 引用次数」= 窗口内命中自有文章 URL 的 reference 条数。

    数据源: ``geo_subtasks.reference_list_json``(全信源池口径,与「自有文章引用
    分析」页 :func:`compute_cite_stats` 同款)与 ``geo_own_articles.url`` normalize
    后精确 join。Toolbar 平台 / 问题筛选语义与 :func:`daily_mention_rate` 一致
    (``platform_codes`` = 原始 ``Subtask.platform``,``prompts`` = 文本)。

    Edge cases:
    - 窗口内无自有文章 → 0
    - 自有文章存在但窗口内无 subtask → 0
    - ``reference_list_json`` 是 None / [] / 异质 dict / 非 str 非 dict 元素 → 静默忽略
    """
    own_urls = {
        normalize_url(a.url)
        for a in db.execute(
            select(OwnArticle).where(
                OwnArticle.project_id == project_id,
                OwnArticle.publish_date >= window_start,
                OwnArticle.publish_date < window_end_exclusive,
            )
        ).scalars()
    }
    if not own_urls:
        return 0

    win_start_dt = datetime.combine(window_start, time.min)
    win_end_dt = datetime.combine(window_end_exclusive - timedelta(days=1), time.max)

    stmt = (
        select(Subtask.reference_list_json)
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    if prompts is not None:
        stmt = stmt.where(Subtask.prompt.in_(prompts))
    if platform_codes is not None:
        stmt = stmt.where(Subtask.platform.in_(platform_codes))

    rows = db.execute(stmt).all()
    count = 0
    for (refs,) in rows:
        if not refs or not isinstance(refs, list):
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
            if normalize_url(url) in own_urls:
                count += 1
    return count


def _scan_own_citations(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> tuple[set[str], list[tuple[str, str]], dict[str, str]]:
    """共享给 4.2 ① / 4.2 ② / 引用计数的扫描骨架。

    返回 ``(own_urls, hits, url_to_title)``:
    - ``own_urls``: 窗口内自有文章的 normalized URL 集合。
    - ``hits``: ``(normalized_url, raw_platform)`` 列表 —— 每次 reference_list_json
      命中自有文章 URL 追加一条。调用方自行 group / sort / slice。
    - ``url_to_title``: ``normalized_url -> title``,给 4.2 ② 显示用。

    复用 :func:`weekly_self_article_citation_count` 的扫描主干,但额外保留
    platform 维度,供 by_platform / top_articles 二次聚合。``url_to_title``
    顺带返回,避免 4.2 ② 单独再读一次 OwnArticle(避免重复 IO)。
    """
    own_rows = db.execute(
        select(OwnArticle).where(
            OwnArticle.project_id == project_id,
            OwnArticle.publish_date >= window_start,
            OwnArticle.publish_date < window_end_exclusive,
        )
    ).scalars().all()
    own_urls = {normalize_url(a.url) for a in own_rows}
    url_to_title = {normalize_url(a.url): a.title for a in own_rows}
    if not own_urls:
        return own_urls, [], url_to_title

    win_start_dt = datetime.combine(window_start, time.min)
    win_end_dt = datetime.combine(window_end_exclusive - timedelta(days=1), time.max)

    # 派发:MySQL 走 JSON_TABLE 在 SQL 层把 reference_list_json 数组展开 + 抽出 url,
    # 只传 URL 字符串过来 —— 实测 ~17x 速度提升、传输字节降到 13.8%(228 个 subtask
    # 的 JSON 数组从 3.9 MB → 537 KB,且免去 Python 端逐行 json.loads 的 CPU)。
    # 其他 dialect(SQLite 测试用)继续走 Python 端解析,功能等价。
    if db.bind is not None and db.bind.dialect.name == "mysql":
        raw_hits = _scan_citation_urls_mysql(
            db,
            project_id=project_id,
            win_start_dt=win_start_dt,
            win_end_dt=win_end_dt,
            platform_codes=platform_codes,
            prompts=prompts,
        )
    else:
        raw_hits = _scan_citation_urls_python(
            db,
            project_id=project_id,
            win_start_dt=win_start_dt,
            win_end_dt=win_end_dt,
            platform_codes=platform_codes,
            prompts=prompts,
        )
    # 仅保留 normalize_url 命中自有文章集合的 —— 这层过滤无论 SQL / Python
    # 路径都共用,保持结果一致。
    hits = [(url, platform) for url, platform in raw_hits if url in own_urls]
    return own_urls, hits, url_to_title


def _scan_citation_urls_mysql(
    db: Session, *,
    project_id: int,
    win_start_dt: datetime,
    win_end_dt: datetime,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> list[tuple[str, str]]:
    """MySQL 路径:JSON_TABLE 展平 + COALESCE 三种 URL 抽法(url / link / 裸字符串),
    只把 url 字符串 + platform 拉过 Python 层。

    三种 entry schema 兼容:
    - ``{"url": "..."}`` → ``$.url`` 命中
    - ``{"link": "..."}``(yuanbao) → ``$.link`` 命中
    - ``"https://..."``(纯字符串)→ COALESCE 落到 ``CASE WHEN JSON_TYPE=STRING``

    返回 ``(url, platform)`` 元组 —— url 是 JSON_UNQUOTE 后的纯文本,调用方
    负责 normalize_url。None / 空字符串被 WHERE 滤掉,不再传过来。
    """
    params: dict = {"pid": project_id, "ws": win_start_dt, "we": win_end_dt}
    where_extra = ""
    if platform_codes is not None:
        # 用 bindparam 名字避免和 JSON_TABLE 别名冲突
        where_extra += " AND s.platform IN :plats"
        params["plats"] = tuple(platform_codes)
    if prompts is not None:
        where_extra += " AND s.prompt IN :prompts"
        params["prompts"] = tuple(prompts)

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
          s.platform AS platform
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
    # IN 子句在 expand 时若为空会触发 SQL 语法错,但调用方传 None 才会触发,
    # 上层已经守好"None = 不过滤"语义。
    rows = db.execute(sql, params).all()
    # MySQL 路径已经替我们做过 schema 兼容抽 url,Python 端再 normalize
    # 一下,与 SQLite 路径行为完全一致。
    return [(normalize_url(url), platform or "") for url, platform in rows]


def _scan_citation_urls_python(
    db: Session, *,
    project_id: int,
    win_start_dt: datetime,
    win_end_dt: datetime,
    platform_codes: Sequence[str] | None,
    prompts: Sequence[str] | None,
) -> list[tuple[str, str]]:
    """SQLite / 通用路径:Python 端 json.loads + dict.get('url'|'link')。

    与 MySQL 路径结果完全等价,只是慢一些(主要是 JSON 反序列化 + 整 blob
    传输)。生产 MySQL 走 ``_scan_citation_urls_mysql``,测试 SQLite 走这里。
    """
    stmt = (
        select(Subtask.reference_list_json, Subtask.platform)
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    if prompts is not None:
        stmt = stmt.where(Subtask.prompt.in_(prompts))
    if platform_codes is not None:
        stmt = stmt.where(Subtask.platform.in_(platform_codes))

    out: list[tuple[str, str]] = []
    for refs, platform in db.execute(stmt).all():
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
            out.append((normalize_url(url), platform or ""))
    return out


def compute_citation_metrics(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    platform_codes: Sequence[str] | None = None,
    prompts: Sequence[str] | None = None,
    top_n: int = 10,
) -> dict:
    """一次 Subtask 扫描同时产出三个引用 KPI,避免
    :func:`weekly_self_article_citation_count` / :func:`weekly_citation_by_platform`
    / :func:`weekly_citation_top_articles` 各自重复扫一次全表 + 重复 Python 遍历
    ``reference_list_json``。

    实测:每个扫描 + JSON 解析 ~5s/次(228 行 subtasks,JSON 列)。原来模板调
    3 个函数 = 15s;走本函数 = 5s。weekly_summary 是当前唯一调用方。

    返回 ``{"citation_count", "citation_by_platform", "citation_top_articles"}``,
    三个字段语义分别与上面三个独立函数一致。
    """
    own_urls, hits, url_to_title = _scan_own_citations(
        db,
        project_id=project_id,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        platform_codes=platform_codes,
        prompts=prompts,
    )
    if not own_urls or not hits:
        return {
            "citation_count": 0,
            "citation_by_platform": [],
            "citation_top_articles": [],
        }

    # by_platform —— 按平台累加
    by_platform_counts: dict[str, int] = {}
    for _url, platform in hits:
        by_platform_counts[platform] = by_platform_counts.get(platform, 0) + 1
    total = sum(by_platform_counts.values())
    citation_by_platform = sorted(
        [
            {
                "platform_code": code,
                "platform_label": platform_label_for_code(code),
                "count": count,
                "share": (count / total) if total > 0 else 0.0,
            }
            for code, count in by_platform_counts.items()
        ],
        key=lambda r: -r["count"],
    )

    # top_articles —— 按 URL 累加 + 平台去重
    by_url: dict[str, dict[str, object]] = {}
    for url, platform in hits:
        bucket = by_url.setdefault(
            url, {"count": 0, "models": set(), "title": url_to_title.get(url, url)}
        )
        bucket["count"] = int(bucket["count"]) + 1
        if platform:
            cast(set, bucket["models"]).add(platform)
    citation_top_articles = sorted(
        [
            {
                "title": str(b["title"]),
                "count": int(b["count"]),
                "models": sorted(cast(set, b["models"])),
            }
            for b in by_url.values()
        ],
        key=lambda r: -r["count"],
    )[:top_n]

    return {
        "citation_count": len(hits),
        "citation_by_platform": citation_by_platform,
        "citation_top_articles": citation_top_articles,
    }


def weekly_publish_detail(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
) -> list[dict]:
    """4.1 表 —— 窗口内 ``geo_own_articles`` 按 ``title`` roll-up,每行 = 一个独立标题。

    同一标题多渠道(URL 不同)=多行 DB 行 → roll-up 成一行展示:
    ``distribution_count`` = 组内行数,``channels`` / ``dates`` = 组内去重列表。

    返回按 ``distribution_count`` 降序,前端 4.1 表直接渲染无需再 sort。

    空标题的行不参与 roll-up(同 :func:`weekly_post_count` 语义),但仍计入
    :func:`weekly_distribution_count`。

    Edge cases:
    - 0 行 → ``[]``
    - 所有行都是空标题 → ``[]``(4.1 表整体不渲染,只显示 KPI 卡片)
    - ``publish_date`` / ``channel`` 空 → 该字段在 list 里缺失,前端显示「—」
    """
    rows = db.execute(
        select(OwnArticle).where(
            OwnArticle.project_id == project_id,
            OwnArticle.publish_date >= window_start,
            OwnArticle.publish_date < window_end_exclusive,
            OwnArticle.title != "",
        ).order_by(OwnArticle.publish_date, OwnArticle.id)
    ).scalars().all()

    by_title: dict[str, dict] = {}
    for a in rows:
        bucket = by_title.setdefault(a.title, {
            "title": a.title,
            "distribution_count": 0,
            "channels": [],
            "dates": [],
        })
        bucket["distribution_count"] += 1
        if a.channel and a.channel not in bucket["channels"]:
            bucket["channels"].append(a.channel)
        if a.publish_date:
            iso = a.publish_date.isoformat()
            if iso not in bucket["dates"]:
                bucket["dates"].append(iso)
    rows_out = list(by_title.values())
    rows_out.sort(key=lambda r: -r["distribution_count"])
    return rows_out


def weekly_citation_by_platform(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    platform_codes: Sequence[str] | None = None,
    prompts: Sequence[str] | None = None,
) -> list[dict]:
    """4.2 ① —— 自有文章被引用次数按 AI 平台分布。

    返回 ``[{"platform_code", "platform_label", "count", "share"}, ...]``,
    按 count 降序。``share`` 是该平台 count 占本项目本窗口内总引用次数的比例
    (0-1),供前端「占比」+「可视化」两条柱子宽度同步用。
    """
    _own_urls, hits, _url_to_title = _scan_own_citations(
        db,
        project_id=project_id,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        platform_codes=platform_codes,
        prompts=prompts,
    )
    if not hits:
        return []
    by_platform: dict[str, int] = {}
    for _url, platform in hits:
        by_platform[platform] = by_platform.get(platform, 0) + 1
    total = sum(by_platform.values())
    rows = [
        {
            "platform_code": code,
            "platform_label": platform_label_for_code(code),
            "count": count,
            "share": (count / total) if total > 0 else 0.0,
        }
        for code, count in by_platform.items()
    ]
    rows.sort(key=lambda r: -r["count"])
    return rows


def weekly_citation_top_articles(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    top_n: int = 10,
    platform_codes: Sequence[str] | None = None,
    prompts: Sequence[str] | None = None,
) -> list[dict]:
    """4.2 ② —— 自有文章被引用次数 TOP ``top_n`` 文章。

    返回 ``[{"title", "count", "models": [...]}, ...]``,按 count 降序。
    ``count`` 是该文章在窗口内的引用次数(全信源池口径,同 4.2 ①);
    ``models`` 是去重后的 AI 平台列表,供「引用 AI」列拼接成「元宝、文心一言」用。
    """
    own_urls, hits, url_to_title = _scan_own_citations(
        db,
        project_id=project_id,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        platform_codes=platform_codes,
        prompts=prompts,
    )
    if not hits:
        return []
    # url_to_title 由 _scan_own_citations 一并返回(避免重复 IO)。

    # 同一 (url, platform) 多次出现算一次(避免异构数据多次算);count 用
    # 命中总次数更直观,与 by_platform 口径对齐。
    by_url: dict[str, dict[str, object]] = {}
    for url, platform in hits:
        bucket = by_url.setdefault(
            url, {"count": 0, "models": set(), "title": url_to_title.get(url, url)}
        )
        bucket["count"] = int(bucket["count"]) + 1
        if platform:
            cast(set, bucket["models"]).add(platform)
    rows = [
        {
            "title": str(b["title"]),
            "count": int(b["count"]),
            "models": sorted(cast(set, b["models"])),
        }
        for b in by_url.values()
    ]
    rows.sort(key=lambda r: -r["count"])
    return rows[:top_n]


def top_stable_prompts(
    db: Session, *,
    project_id: int,
    window_start: date,
    window_end_exclusive: date,
    top_n: int = 5,
    platform_codes: Sequence[str] | None = None,
    prompts: Sequence[str] | None = None,
) -> dict:
    """3.3 稳定提及的前 N 个问题 — 按问题在窗口内被提及的「监测日数」降序排。

    数据源: ``geo_brand_mentions`` 直接读。指标 = 该 prompt 在窗口内被提及的
    distinct 天数(任一平台 / 终端 / 模式 + is_mention=1 都算一天)。

    ``total_monitor_days`` = 窗口内实际有抽取数据的 distinct 天数(``is_self=1
    AND extract_status != PENDING`` 的行),不是日历跨度——日历跨度可能在
    周末或缺测日根本没有数据,不该作为分母。前端展示 "覆盖 X/Y 天"。

    Edge cases:
    - 窗口内 0 行抽取 → ``stable_prompts=[]`` + ``total_monitor_days=0``
    - 多个 prompt 同分 → 按 ``ProjectPrompt.sort`` 升序稳定排序
    """
    monitor_days_stmt = select(
        func.count(func.distinct(func.date(BrandMention.created_at)))
    ).where(
        BrandMention.project_id == project_id,
        BrandMention.is_self == True,
        BrandMention.extract_status != ExtractStatus.PENDING,
        BrandMention.created_at >= window_start,
        BrandMention.created_at < window_end_exclusive,
        *([BrandMention.platform.in_(platform_codes)] if platform_codes else []),
    )
    total_monitor_days = int(db.execute(monitor_days_stmt).scalar() or 0)

    base = (
        select(
            BrandMention.prompt,
            func.count(func.distinct(func.date(BrandMention.created_at))).label(
                "mention_days"
            ),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_self == True,
            BrandMention.is_mention == 1,
            BrandMention.extract_status != ExtractStatus.PENDING,
            BrandMention.created_at >= window_start,
            BrandMention.created_at < window_end_exclusive,
            BrandMention.prompt.is_not(None),
            *([BrandMention.platform.in_(platform_codes)] if platform_codes else []),
            *([BrandMention.prompt.in_(prompts)] if prompts else []),
        )
        .group_by(BrandMention.prompt)
    )

    ranked = db.execute(
        base.order_by(
            func.count(func.distinct(func.date(BrandMention.created_at))).desc(),
        )
    ).all()

    proj_prompts_rows = db.execute(
        select(ProjectPrompt.id, ProjectPrompt.prompt).where(
            ProjectPrompt.project_id == project_id
        ).order_by(ProjectPrompt.sort)
    ).all()
    sort_rank = {p.prompt: (i, p.id) for i, p in enumerate(proj_prompts_rows)}

    out: list[dict] = []
    for prompt_text, mention_days in ranked[:top_n]:
        if not prompt_text:
            continue
        sort_idx, prompt_id = sort_rank.get(prompt_text, (10**9, None))
        out.append({
            "prompt_id": prompt_id,
            "prompt_text": prompt_text,
            "mention_days": int(mention_days),
            "sort_rank": sort_idx,
        })
    out.sort(key=lambda r: (-r["mention_days"], r["sort_rank"]))
    return {"stable_prompts": out, "total_monitor_days": total_monitor_days}
