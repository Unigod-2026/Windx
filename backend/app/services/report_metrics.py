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

from datetime import date, timedelta
from typing import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.enums import ExtractStatus
from app.models.project import BrandMention, OwnArticle, ProjectPrompt


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
            ProjectPrompt.project_id == project_id
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
            ProjectPrompt.project_id == project_id
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
    """独立标题数 = 周窗口内 ``geo_own_articles.publish_date`` 命中的行数。

    不去重 title:每条录入代表一次发布动作(可能同名内容不同渠道),
    运营看到的是「这周发了多少篇」。0 行 → 0(不是 None),便于前端
    KPI 始终显示数字。

    Spec:report-template-full.md §9 把「内容运营数据接入」原定为不做项;
    本期仅接「本周发布独立标题」这一个 KPI,4.x 章节其余字段仍为 None。
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
