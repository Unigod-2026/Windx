"""导出取数与口径层 —— 把「哪些问题在哪些平台被提及」算成可直接写表的数据。

本模块只负责取数与口径,不碰 xlsx(那是 ``export_generator`` 的事),
也不碰任务状态(那是 ``export_worker`` 的事)。这样口径可以脱离文件格式单测。

日期口径
--------
全篇用 ``geo_tasks.created_local_at`` 的上海日期作为「监控日期」——
那是监控发生的时刻。``BrandMention.created_at`` 在导入路径上写的是监控日
(``import_monitor_data`` 用 ``_day_start(row.date)``),在抽取流水线上写的是
抽取时刻,两者不一致,拿它分日期会让同一次监控落进两个日子。

单元格三态
----------
- 「已提及」—— 该 (问题, 平台组) 下有任一**已结算**的抽取结论为提及;
- 「未提及」—— 有已结算结论但都不是提及;
- 「-」—— 没有已结算结论(没回答 / 抽取还在跑 / 抽取失败),
  **不计入统计分母**。

「已结算」= ``extract_status != PENDING``。``FAILED`` 算已结算(抽取跑完了,
结论是「没提到」),与 ``report_metrics.py`` 的 ``total`` 口径一致。

平台归并
--------
按平台名归并:``doubao`` 与 ``doubao_mobile`` 合成一个「豆包」组
(``platform_labels.platform_label_for_code``)。归并后统计计数按
**(问题, 平台组, 日期) 三元组去重** —— 同平台三档(web / mobile / 思考)
各答一次只算一个「对」。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.common import now_local
from app.models.enums import ExtractStatus
from app.models.project import (
    BrandMention,
    Project,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.task import Subtask, Task
from app.services.platform_labels import platform_label_for_code

#: 一格最多能塞多少字符 —— Excel 单元格硬上限 32767。
CELL_MAX_CHARS = 32767


class ExportParamError(ValueError):
    """导出参数不合法 —— API 层转 400。"""


@dataclass(frozen=True)
class ExportParams:
    """一次导出的筛选条件(已归一)。"""

    start: date
    end: date
    #: compound key 列表(``doubao__web__fast``);None = 不筛。
    platforms: tuple[str, ...] | None
    #: ``geo_project_prompts.id`` 列表;None = 不筛。
    prompt_ids: tuple[int, ...] | None


@dataclass(frozen=True)
class PlatformGroup:
    """一个平台组 —— 按平台名归并后的一个「豆包」。"""

    label: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class PromptRow:
    id: int
    text: str
    sort: int


@dataclass(frozen=True)
class DetailRow:
    """明细 sheet 的一行 —— 一次回答。"""

    prompt_text: str
    day: date
    platform_code: str
    answer_content: str
    share_url: str
    #: 本品牌在这次回答里的**真实排名** —— 来自
    #: ``BrandMention.rank_position``。没被提及时是 None。
    rank: int | None
    #: 问题核心词。
    keyword: str


@dataclass(frozen=True)
class MentionCell:
    """总表(「提及率」sheet)里的一格。

    ``state``:
    - ``mentioned``     —— 提及了,``rank`` 带最佳排名(数值越小越靠前);
    - ``not_mentioned`` —— 有回答但品牌没被提及;
    - ``unknown``       —— 没有已结算的抽取结论(没回答 / 抽取还在跑)。
    """

    state: str
    rank: int | None = None


@dataclass(frozen=True)
class StatBlock:
    """某一天的统计块。"""

    day: date
    mentioned: dict[str, int]
    not_mentioned: dict[str, int]


@dataclass(frozen=True)
class ExportData:
    """写一个 xlsx 所需的全部数据。"""

    project_name: str
    brand: str
    keywords: tuple[str, ...]
    platforms: tuple[PlatformGroup, ...]
    prompts: tuple[PromptRow, ...]
    #: (prompt_id, 平台 label) → 该格的提及结论(带最佳排名)
    cells: dict[tuple[int, str], MentionCell]
    stat_blocks: tuple[StatBlock, ...]
    #: 平台 label → 明细行
    details: dict[str, tuple[DetailRow, ...]]


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------


def _as_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise ExportParamError(f"{field} 不是合法日期") from exc
    raise ExportParamError(f"{field} 不是合法日期")


def parse_export_params(raw: dict) -> ExportParams:
    """把请求体归一成 :class:`ExportParams`,不合法就抛 :class:`ExportParamError`。

    ``date_range`` 二选一:``{"start","end"}`` 或 ``{"days"}``(最近 N 天,
    1–90)。窗口起闭都是闭区间。
    """
    raw = raw or {}
    rng = raw.get("date_range") or {}
    if not isinstance(rng, dict):
        raise ExportParamError("date_range 必须是对象")
    if rng.get("start") is not None or rng.get("end") is not None:
        if rng.get("start") is None or rng.get("end") is None:
            raise ExportParamError("start 和 end 必须同时提供")
        start = _as_date(rng.get("start"), "start")
        end = _as_date(rng.get("end"), "end")
        if end < start:
            raise ExportParamError("end 不能早于 start")
    else:
        raw_days = rng.get("days")
        # 注意不能写 ``rng.get("days") or 15`` —— 那样 days=0 会被当成
        # 「没传」而悄悄变成 15,越界校验就形同虚设。
        try:
            days = 15 if raw_days is None else int(raw_days)
        except (TypeError, ValueError) as exc:
            raise ExportParamError("days 必须是整数") from exc
        if days < 1 or days > 90:
            raise ExportParamError("days 必须在 1~90 之间")
        end = now_local().date()
        start = end - timedelta(days=days - 1)

    platforms = raw.get("platforms")
    if platforms is not None:
        if not isinstance(platforms, (list, tuple)):
            raise ExportParamError("platforms 必须是数组")
        platforms = tuple(str(p) for p in platforms)

    prompt_ids = raw.get("prompt_ids")
    if prompt_ids is not None:
        if not isinstance(prompt_ids, (list, tuple)):
            raise ExportParamError("prompt_ids 必须是数组")
        try:
            prompt_ids = tuple(int(p) for p in prompt_ids)
        except (TypeError, ValueError) as exc:
            raise ExportParamError("prompt_ids 必须是整数数组") from exc

    return ExportParams(
        start=start, end=end, platforms=platforms, prompt_ids=prompt_ids
    )


# --------------------------------------------------------------------------
# compound key 展开
# --------------------------------------------------------------------------


def expand_selected(selected: Sequence[str] | None) -> set[tuple[str, bool]] | None:
    """compound key 列表 → ``{(platform_code, is_thinking)}``;None = 不筛。

    兼容前端 ``rowKeyOfPlatform``(用 ``platform_code`` 直拼,mobile 行产
    ``doubao_mobile__mobile__fast``)与后端 ``_compound_platform``(base 不带
    ``_mobile`` 后缀,产 ``doubao__mobile__fast``)两种写法:先把 code 的
    ``_mobile`` 后缀剥掉,再按 delivery 决定加不加回去。

    非法格式静默跳过(与 Overview 一致),不把整批 SQL 拉爆。
    """
    if selected is None:
        return None
    out: set[tuple[str, bool]] = set()
    for key in selected:
        parts = str(key).split("__")
        if len(parts) != 3:
            continue
        code, delivery, thinking = parts
        if not code:
            continue
        base = code.removesuffix("_mobile")
        platform_code = f"{base}_mobile" if delivery == "mobile" else base
        out.add((platform_code, thinking == "think"))
    return out


# --------------------------------------------------------------------------
# 取数
# --------------------------------------------------------------------------


def _load_platform_groups(
    db: Session, project_id: int, selected: set[tuple[str, bool]] | None
) -> tuple[PlatformGroup, ...]:
    rows = db.execute(
        select(ProjectPlatform.platform_code, ProjectPlatform.sort)
        .where(ProjectPlatform.project_id == project_id)
        .order_by(ProjectPlatform.sort, ProjectPlatform.id)
    ).all()
    allowed = None if selected is None else {code for code, _ in selected}
    groups: dict[str, list[str]] = {}
    for code, _sort in rows:
        if allowed is not None and code not in allowed:
            continue
        label = platform_label_for_code(code)
        bucket = groups.setdefault(label, [])
        if code not in bucket:
            bucket.append(code)
    return tuple(
        PlatformGroup(label=label, codes=tuple(codes))
        for label, codes in groups.items()
    )


def _load_prompts(
    db: Session, project_id: int, params: ExportParams
) -> tuple[PromptRow, ...]:
    stmt = select(ProjectPrompt.id, ProjectPrompt.prompt, ProjectPrompt.sort).where(
        ProjectPrompt.project_id == project_id
    )
    if params.prompt_ids is not None:
        stmt = stmt.where(ProjectPrompt.id.in_(params.prompt_ids))
    rows = db.execute(stmt.order_by(ProjectPrompt.sort, ProjectPrompt.id)).all()
    return tuple(PromptRow(id=r.id, text=r.prompt, sort=r.sort) for r in rows)


def _load_keywords(db: Session, project_id: int) -> tuple[str, ...]:
    rows = db.execute(
        select(ProjectKeyword.keyword)
        .where(ProjectKeyword.project_id == project_id)
        .order_by(ProjectKeyword.sort, ProjectKeyword.id)
    ).all()
    return tuple(r.keyword for r in rows)


def _pick_keyword(prompt_text: str, keywords: Sequence[str], fallback: str) -> str:
    """问题核心词 —— 项目关键词里第一个出现在问题文本中的;没有则回落品牌名。"""
    for kw in keywords:
        if kw and kw in prompt_text:
            return kw
    return fallback


def _load_mention_facts(
    db: Session,
    project_id: int,
    params: ExportParams,
    texts: Sequence[str],
    codes: Sequence[str],
    selected: set[tuple[str, bool]] | None,
) -> list[tuple[str, str, date, int, bool, int | None]]:
    """self 抽取结论 → ``(prompt_text, platform_code, day, is_mention, settled, rank)``。

    ``rank`` 是本品牌在这次回答里的真实排名(``BrandMention.rank_position``)
    —— 导入数据和流水线抽取都写这一列,不用去翻 ``raw_result_json``。
    """
    if not texts or not codes:
        return []
    win_start = datetime.combine(params.start, time.min)
    win_end = datetime.combine(params.end, time.max)
    rows = db.execute(
        select(
            BrandMention.prompt,
            BrandMention.platform,
            BrandMention.thinking_mode,
            BrandMention.is_mention,
            BrandMention.rank_position,
            BrandMention.extract_status,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == BrandMention.task_id)
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_self.is_(True),
            BrandMention.prompt.in_(list(texts)),
            BrandMention.platform.in_(list(codes)),
            Task.created_local_at >= win_start,
            Task.created_local_at <= win_end,
        )
    ).all()
    facts: list[tuple[str, str, date, int, bool, int | None]] = []
    for prompt, platform, thinking, is_mention, rank, extract_status, created in rows:
        if selected is not None:
            want = {t for code, t in selected if code == platform}
            if not want:
                continue
            # thinking_mode 缺省按 False 处理(CLAUDE.md §14)
            if bool(thinking) not in want and not (
                thinking is None and False in want
            ):
                continue
        settled = extract_status != ExtractStatus.PENDING
        facts.append(
            (prompt, platform, created.date(), is_mention, settled, rank)
        )
    return facts


def _load_detail_rows(
    db: Session,
    project_id: int,
    params: ExportParams,
    texts: Sequence[str],
    codes: Sequence[str],
    selected: set[tuple[str, bool]] | None,
    keywords: Sequence[str],
    brand: str,
) -> list[DetailRow]:
    """窗口内每一条回答 = 明细 sheet 的一行。"""
    if not texts or not codes:
        return []
    win_start = datetime.combine(params.start, time.min)
    win_end = datetime.combine(params.end, time.max)
    rows = db.execute(
        select(
            Subtask.subtask_id,
            Subtask.prompt,
            Subtask.platform,
            Subtask.mode,
            Subtask.answer_content,
            Subtask.share_url,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Subtask.prompt.in_(list(texts)),
            Subtask.platform.in_(list(codes)),
            Task.created_local_at >= win_start,
            Task.created_local_at <= win_end,
        )
    ).all()
    sub_ids = [r[0] for r in rows]

    # 本品牌在每次回答里的真实排名 —— ``BrandMention.rank_position``。
    # 导入数据没有 ``raw_result_json.allRankings``(那是远端 payload 里的),
    # 但 rank_position 两条链路都写,才是「真实排名」的可靠来源。
    rank_by_subtask: dict[str, int] = {}
    if sub_ids:
        for sid, rank in db.execute(
            select(BrandMention.subtask_id, BrandMention.rank_position).where(
                BrandMention.subtask_id.in_(sub_ids),
                BrandMention.is_self.is_(True),
                BrandMention.rank_position.isnot(None),
            )
        ).all():
            rank_by_subtask[sid] = rank

    out: list[DetailRow] = []
    for subtask_id, prompt, platform, mode, answer, share_url, created in rows:
        if selected is not None:
            want = {t for code, t in selected if code == platform}
            if not want:
                continue
            thinking = mode in ("reasoning", "reasoning_search")
            if thinking not in want and not (not thinking and False in want):
                continue
        out.append(
            DetailRow(
                prompt_text=prompt or "",
                day=created.date(),
                platform_code=platform or "",
                answer_content=answer or "",
                share_url=share_url or "",
                rank=rank_by_subtask.get(subtask_id),
                keyword=_pick_keyword(prompt or "", keywords, brand),
            )
        )
    return out


def collect_export_data(
    db: Session, project_id: int, params: ExportParams
) -> ExportData:
    """取数 + 算口径,产出可直接写表的数据。"""
    project = db.get(Project, project_id)
    if project is None:
        raise ExportParamError("项目不存在")

    selected = expand_selected(params.platforms)
    groups = _load_platform_groups(db, project_id, selected)
    prompts = _load_prompts(db, project_id, params)
    keywords = _load_keywords(db, project_id)

    # prompt 文本 → prompt id。同一项目里理论上不重名;真重名时取 sort
    # 最小的那个(子查询已按 sort 排序,第一个赢)。
    text_to_id: dict[str, int] = {}
    for p in prompts:
        text_to_id.setdefault(p.text, p.id)

    codes = tuple(code for g in groups for code in g.codes)
    code_to_label = {code: g.label for g in groups for code in g.codes}
    texts = tuple(p.text for p in prompts)

    facts = _load_mention_facts(
        db, project_id, params, texts, codes, selected
    )
    details = _load_detail_rows(
        db, project_id, params, texts, codes, selected, keywords, project.brand
    )

    # ---- 单元格 + 统计块 -------------------------------------------------
    # verdict[(prompt_id, label, day)] = (当天是否被提及, 当天的最佳排名)。
    # 「最佳」= 排名数值最小 —— 同一问题同一天被多个档位答到时取最好的那次。
    verdict: dict[tuple[int, str, date], tuple[bool, int | None]] = {}
    for prompt_text, code, day, is_mention, settled, rank in facts:
        if not settled:
            continue
        pid = text_to_id.get(prompt_text)
        if pid is None:
            continue
        key = (pid, code_to_label.get(code, code), day)
        was_mentioned, best = verdict.get(key, (False, None))
        if is_mention:
            if best is None or (rank is not None and rank < best):
                best = rank
            verdict[key] = (True, best)
        else:
            verdict[key] = (was_mentioned, best)

    mentioned_pairs: set[tuple[int, str]] = set()
    settled_pairs: set[tuple[int, str]] = set()
    #: (问题, 平台组) → 窗口内的最佳排名(数值最小 = 排名最高)。
    best_rank_by_pair: dict[tuple[int, str], int] = {}
    per_day: dict[date, dict[str, tuple[int, int]]] = {}
    for (pid, label, day), (mentioned, best) in verdict.items():
        pair = (pid, label)
        settled_pairs.add(pair)
        if mentioned:
            mentioned_pairs.add(pair)
            if best is not None:
                current = best_rank_by_pair.get(pair)
                if current is None or best < current:
                    best_rank_by_pair[pair] = best
        bucket = per_day.setdefault(day, {})
        m, n = bucket.get(label, (0, 0))
        bucket[label] = (m + (1 if mentioned else 0), n + (0 if mentioned else 1))

    cells: dict[tuple[int, str], MentionCell] = {}
    for p in prompts:
        for g in groups:
            pair = (p.id, g.label)
            if pair in mentioned_pairs:
                cells[pair] = MentionCell(
                    state="mentioned", rank=best_rank_by_pair.get(pair)
                )
            elif pair in settled_pairs:
                cells[pair] = MentionCell(state="not_mentioned")
            else:
                cells[pair] = MentionCell(state="unknown")

    stat_blocks: list[StatBlock] = []
    # 统计块的日期集合 = **窗口内有回答的监控日** ∪ 有已结算结论的日子。
    # 只按「有结论的日子」取集合的话,抽取还在跑时整块统计会整段消失 ——
    # 用户看到的是「表下面什么都没有」,而不是「这天有 48 个问题、结论还没出来」。
    block_days = {row.day for row in details} | {d for (_p, _l, d) in verdict}
    for day in sorted(block_days):
        bucket = per_day.get(day, {})
        stat_blocks.append(
            StatBlock(
                day=day,
                mentioned={
                    g.label: bucket.get(g.label, (0, 0))[0] for g in groups
                },
                not_mentioned={
                    g.label: bucket.get(g.label, (0, 0))[1] for g in groups
                },
            )
        )

    # ---- 明细按平台组归拢 + 排序 -----------------------------------------
    by_label: dict[str, list[DetailRow]] = {g.label: [] for g in groups}
    for row in details:
        label = code_to_label.get(row.platform_code)
        if label is None:
            continue
        by_label.setdefault(label, []).append(row)
    sort_by_text = {p.text: p.sort for p in prompts}
    detail_map: dict[str, tuple[DetailRow, ...]] = {}
    for label, rows_ in by_label.items():
        rows_.sort(
            key=lambda r: (
                sort_by_text.get(r.prompt_text, 0),
                r.day,
                r.platform_code,
            )
        )
        detail_map[label] = tuple(rows_)

    return ExportData(
        project_name=project.name,
        brand=project.brand,
        keywords=keywords,
        platforms=groups,
        prompts=prompts,
        cells=cells,
        stat_blocks=tuple(stat_blocks),
        details=detail_map,
    )
