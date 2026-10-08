"""竞品分析 (data tab → 竞品分析) 计算服务。

本文件按页面分开,把所有竞品分析相关的 SQL/聚合/序列化集中在这里,
``api/projects.py`` 只剩薄壳 endpoint 调 :func:`compute_competitor_analysis`。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select, tuple_

from app.models.common import now_local
from app.models.project import BrandMention, ProjectCompetitor, ProjectPlatform
from app.schemas.project import (
    CompetitorAnalysisOut,
    CompetitorKpi,
    CompetitorTrendBlock,
    CompetitorTrendSeries,
    DiffBrandCard,
    DiffBrandOut,
    DiffBrandRow,
)


def compound_key(
    platform_code: str,
    delivery_mode: str,
    thinking_mode: bool | None,
) -> str:
    """``${platform_code}__${delivery_mode}__${thinking}`` —— ``thinking_mode``
    缺省按 False 处理,避免与旧 fixture ``None`` 行拼出 ``__None__`` 这种坏
    key。本地副本,避免与 ``app.api.projects`` 的 circular import。"""
    thinking = "think" if thinking_mode else "fast"
    return f"{platform_code}__{delivery_mode}__{thinking}"


_COMPETITOR_LINE_COLORS = [
    "#1a55e8",  # self — brand blue
    "#ff6b1a",  # 元宝
    "#13c2c2",  # DeepSeek
    "#52c41a",  # 通义
    "#722ed1",  # Kimi
    "#eb2f96",  # 文心
]


def _resolve_competitor_window(
    days: int, start: date | None, end: date | None
) -> tuple[date, date]:
    """Same shape as :func:`_overview_window` but accepts a wider range
    because the 竞品分析 tab doesn't need to compare against a baseline —
    the chart just shows the window directly."""
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        if (end - start).days + 1 > 90:
            raise HTTPException(400, "range must not exceed 90 days")
        return start, end
    if days < 1 or days > 90:
        raise HTTPException(400, "days must be between 1 and 90")
    today = now_local().date()
    return today - timedelta(days=days - 1), today


def _build_brand_filter(
    selected_triples: set[tuple[str, str, bool]] | None,
    selected_prompt_texts: list[str] | None,
) -> list:
    """构造 ``BrandMention`` 表的额外 WHERE 条件。

    - ``selected_triples=None`` 表示「不筛」(全选);非 None 表示按
      ``(platform, delivery_mode, thinking_mode)`` 三元组精确过滤,
      与 Overview / 问题提及分析 tab 同口径;
    - ``selected_prompt_texts=None`` 表示「不筛」(全选);``[]`` 表示
      「全部未选」(走 0 行,避免静默回退到全选);非空 list 是 IN-list
      过滤(按 prompt 文本匹配,因为 BrandMention.prompt 是文本)。

    返回 SQLAlchemy 条件 list;调用方用 ``*existing, *filter`` 拼到
    ``.where()`` 里。
    """
    out: list = []
    if selected_triples is not None:
        if not selected_triples:
            # 「全部未选」走 0 行,SQL 永远 false,避免空集合 IN () 语法错。
            out.append(func.coalesce(BrandMention.id, None).is_(None))
        else:
            out.append(
                tuple_(
                    BrandMention.platform,
                    BrandMention.delivery_mode,
                    BrandMention.thinking_mode,
                ).in_(selected_triples)
            )
    if selected_prompt_texts is not None:
        if not selected_prompt_texts:
            out.append(func.coalesce(BrandMention.id, None).is_(None))
        else:
            out.append(BrandMention.prompt.in_(selected_prompt_texts))
    return out


# ——— 差异化分析(逐品牌罗列) ——————————————————————————————————————
#
# 设计目标:把"自身 vs 竞品均值"展开为「3 指标 × N 品牌 = 最多 15 张卡」,
# 每张卡是单个品牌在单个指标下的完整明细(头部 KPI + N 行 × 6 列模型表)。
# 见 docs/风球GEO监控平台UI-261005 v3.2 changelog。
#
# 关键口径:
# - 数据源只用 geo_brand_mentions 一张表(不引入新表)。
# - 分母按 (platform_code, delivery_mode) 共享,自身/竞品在同一行内可横向
#   比较;platform_code 通过剥离 _mobile 后缀得到。
# - 卡片总数 = (1 + |competitors|) × 3;每张卡 N 行 = toolbar 当前选中的
#   model 集合(toolbar 全选时回退到项目配置的 platform 集合)。

DIFF_BRAND_COLORS: dict[str, str] = {
    "自身":   "#344e8d",
    "薇诺娜": "#344e8d",  # 自有品牌 fallback
    "珂润":   "#935939",
    "玉泽":   "#2f745d",
    "雅漾":   "#5f3b91",
    "理肤泉": "#317d7d",
}
DEFAULT_SELF_COLOR = "#344e8d"
DEFAULT_COMP_COLOR = "#6b7280"

_DIFF_METRIC_META = [
    {"id": "mention", "name": "整体提及率", "desc": "该品牌被提及的答案占比", "unit": "%"},
    {"id": "top1",    "name": "Top1 提及率", "desc": "该品牌排在答案第 1 位的占比", "unit": "%"},
    {"id": "top3",    "name": "Top3 提及率", "desc": "该品牌进入答案前三的占比", "unit": "%"},
]
_DIFF_METRIC_KEYS = ("mention", "top1", "top3")


def _compute_diff_brand(
    db,
    project_id: int,
    win_start_dt,
    win_end_dt,
    self_kpi: CompetitorKpi | None,
    competitor_kpis: list[CompetitorKpi],
    selected_triples: set[tuple[str, str, bool]] | None,
    selected_prompt_texts: list[str] | None,
) -> DiffBrandOut:
    """差异化分析(逐品牌罗列) — 3 指标 × N 品牌 = 最多 15 张卡。

    每张卡 = (metric, brand) → DiffBrandCard;rows 数 = |selected_codes|,顺序
    后端按字母序排稳定序,前端会用 WIZARD_MODELS 索引重排展示顺序。
    head_value 跟"全部竞品"tab 同口径:``CompetitorKpi.{mention,top1,top3}_rate``,
    品牌级单值(``matched / 项目级 total_subtasks``)。
    每张卡 rows 内的 ``overall`` 列 = (该 platform 的 web 命中数 + mobile 命中数) /
    该 platform 的 (web + mobile) subtask 数,per-platform 跨 delivery 的合并率,
    分母与 PC / 移动列的 per-(model, delivery) 细分率**不同**(分子相同,分母合并)。

    selected_triples / selected_prompt_texts 与主函数同语义:None = 不筛;
    非 None = 严格过滤(三元组 / prompt 文本 IN-list)。
    """
    if self_kpi is None:
        return DiffBrandOut(
            metrics=_DIFF_METRIC_META,
            self_brand_canonical=None,
            cards=[],
        )

    selected_codes = _resolve_selected_codes(db, project_id, selected_triples)
    sorted_codes = sorted(selected_codes)

    brand_filter = _build_brand_filter(selected_triples, selected_prompt_texts)
    common_where = [
        BrandMention.project_id == project_id,
        BrandMention.created_at >= win_start_dt,
        BrandMention.created_at <= win_end_dt,
        BrandMention.platform.is_not(None),
        *brand_filter,
    ]

    # Query A — per-(brand, platform_code, delivery_mode) 命中数
    platform_code_expr = case(
        (
            BrandMention.platform.like("%_mobile"),
            func.substr(
                BrandMention.platform,
                1,
                func.length(BrandMention.platform) - len("_mobile"),
            ),
        ),
        else_=BrandMention.platform,
    ).label("platform_code")

    brand_rows = db.execute(
        select(
            BrandMention.brand,
            BrandMention.is_self,
            platform_code_expr,
            BrandMention.delivery_mode,
            func.sum(case((BrandMention.is_mention > 0, 1), else_=0)).label("matched"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.rank_position == 1,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("top1"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.rank_position.is_not(None),
                            BrandMention.rank_position <= 3,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("top3"),
        )
        .where(*common_where)
        .group_by(
            BrandMention.brand,
            BrandMention.is_self,
            "platform_code",
            BrandMention.delivery_mode,
        )
    ).all()

    # Query B — per-(platform_code, delivery_mode) 窗口分母(self/竞品共享)
    total_rows = db.execute(
        select(
            platform_code_expr,
            BrandMention.delivery_mode,
            func.count(func.distinct(BrandMention.subtask_id)).label("total"),
        )
        .where(*common_where)
        .group_by("platform_code", BrandMention.delivery_mode)
    ).all()
    total_by_pd: dict[tuple[str, str], int] = {
        (r.platform_code, r.delivery_mode): int(r.total or 0) for r in total_rows
    }

    # 索引命中数 (brand, platform_code, delivery_mode) → {mention, top1, top3}
    by_bpd: dict[tuple[str, str, str], dict[str, int]] = {}
    for r in brand_rows:
        by_bpd[(r.brand, r.platform_code, r.delivery_mode)] = {
            "mention": int(r.matched or 0),
            "top1": int(r.top1 or 0),
            "top3": int(r.top3 or 0),
        }

    def _row_rate(brand: str, code: str, metric: str) -> tuple[float, float, float]:
        """返回 (pc_rate, mobile_rate, overall),单位 0-100。
        - pc_rate / mobile_rate:per-(platform, delivery) 细分率,分母是
          该 platform × delivery 在窗口内的 distinct subtask 数
        - overall:per-platform 跨 delivery 合并率,
          (web 命中 + mobile 命中) / 该 platform 的 (web + mobile) subtask 数
        """
        d_pc = max(1, total_by_pd.get((code, "web"), 0))
        d_mb = max(1, total_by_pd.get((code, "mobile"), 0))
        cnt_pc = by_bpd.get((brand, code, "web"), {}).get(metric, 0)
        cnt_mb = by_bpd.get((brand, code, "mobile"), {}).get(metric, 0)
        overall_denom = max(
            1, total_by_pd.get((code, "web"), 0) + total_by_pd.get((code, "mobile"), 0)
        )
        overall = (cnt_pc + cnt_mb) / overall_denom * 100
        return cnt_pc / d_pc * 100, cnt_mb / d_mb * 100, overall

    brand_list: list[CompetitorKpi] = [self_kpi, *competitor_kpis]

    cards: list[DiffBrandCard] = []
    # head_value 跟 "全部竞品" tab 同口径:`CompetitorKpi.{mention,top1,top3}_rate`
    # 是 matched / total_subtasks(品牌级单值,不分 platform / 终端),差异化
    # 卡的卡头 KPI 直接复用,不再做 pc/mobile 加权。卡内表格的 PC/移动/均值
    # 列是 per-model 的明细,跟 KPI 不同口径,各自独立。
    metric_to_attr = {
        "mention": "mention_rate",
        "top1":    "top1_rate",
        "top3":    "top3_rate",
    }
    for metric in _DIFF_METRIC_KEYS:
        attr = metric_to_attr[metric]
        for bkpi in brand_list:
            rows: list[DiffBrandRow] = [
                DiffBrandRow(
                    platform_code=code,
                    pc_rate=pc,
                    mobile_rate=mb,
                    overall=overall,
                )
                for code in sorted_codes
                for pc, mb, overall in [_row_rate(bkpi.brand, code, metric)]
            ]
            head = getattr(bkpi, attr) * 100
            cards.append(DiffBrandCard(
                metric=metric,  # type: ignore[arg-type]
                brand=bkpi.name,
                brand_canonical=bkpi.brand,
                is_self=bkpi.is_self,
                color=brand_color_for(bkpi.name, bkpi.is_self),
                head_value=round(head, 1),
                rows=rows,
            ))

    return DiffBrandOut(
        metrics=_DIFF_METRIC_META,
        self_brand_canonical=self_kpi.brand,
        cards=cards,
    )


def _strip_mobile(platform_code: str | None) -> str:
    """``doubao_mobile`` → ``doubao``。platform_code 为 None/空时原样返回。"""
    if not platform_code:
        return platform_code or ""
    return (
        platform_code[:-len("_mobile")]
        if platform_code.endswith("_mobile")
        else platform_code
    )


def brand_color_for(brand_name: str, is_self: bool) -> str:
    """差异化分析卡头左条 / KPI 数字的取色;unknown 竞品走灰色兜底。"""
    if is_self:
        return DIFF_BRAND_COLORS.get(brand_name, DEFAULT_SELF_COLOR)
    return DIFF_BRAND_COLORS.get(brand_name, DEFAULT_COMP_COLOR)


def _resolve_selected_codes(
    db,
    project_id: int,
    selected_triples: set[tuple[str, str, bool]] | None,
) -> set[str]:
    """决定差异化卡片表格的"行集合"。

    - ``selected_triples`` 非 None 且非空 → 用 toolbar 选中的 platform_code 集合
      (空集 ``set()`` 是合法的"用户显式全清"语义,返回 ``set()``,前端显示空态)
    - ``selected_triples is None`` (toolbar 全选) → fallback 到项目配置的
      ``geo_project_platforms.platform_code``(剥离 _mobile 去重)
    """
    if selected_triples is not None:
        return {code for code, _, _ in selected_triples}
    rows = db.execute(
        select(ProjectPlatform.platform_code).where(
            ProjectPlatform.project_id == project_id
        )
    ).all()
    return {_strip_mobile(r.platform_code) for r in rows if r.platform_code}


# ——— 差异化分析(逐品牌罗列)— end ———


def compute_competitor_analysis(
    *,
    db,
    project_id: int,
    project,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    selected_triples: set[tuple[str, str, bool]] | None = None,
    selected_prompt_texts: list[str] | None = None,
) -> CompetitorAnalysisOut:
    """Drives the 竞品分析 tab. Returns a ``CompetitorAnalysisOut``
    populated with self + competitors + trend + diff_brand + previous
    window dates. The 4 deltas on each KPI and ``previous_window_*``
    are None when ``days < 7`` (spec §1.3).

    selected_triples / selected_prompt_texts 都是 toolbar 联动的筛选口径:
    None 表示「不筛」;非 None 表示严格过滤(三元组 / prompt 文本 IN-list)。
    当前 / 上一窗口、trend、diff_brand 都共享同一组筛选条件。
    """
    win_start, win_end = _resolve_competitor_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    brand_filter = _build_brand_filter(selected_triples, selected_prompt_texts)

    competitor_rows = db.scalars(
        select(ProjectCompetitor).where(ProjectCompetitor.project_id == project_id)
    ).all()
    name_by_brand: dict[str, tuple[str, list[str] | None, bool]] = {}
    for c in competitor_rows:
        name_by_brand[c.name] = (c.name, c.aliases, False)
    self_brand_name = project.brand
    self_brand_aliases = project.aliases
    if self_brand_name:
        name_by_brand[self_brand_name] = (
            self_brand_name,
            self_brand_aliases,
            True,
        )

    brand_rows = db.execute(
        select(
            BrandMention.brand,
            BrandMention.is_self,
            func.sum(case((BrandMention.is_mention > 0, 1), else_=0)).label("matched"),
            func.count().label("rows_total"),
            func.avg(
                case(
                    (
                        BrandMention.is_mention > 0,
                        case(
                            (BrandMention.sentiment == "positive", 1.0),
                            (BrandMention.sentiment == "neutral", 0.5),
                            (BrandMention.sentiment == "negative", 0.0),
                            else_=None,
                        ),
                    ),
                    else_=None,
                )
            ).label("avg_sentiment"),
            func.avg(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.rank_position.is_not(None),
                        ),
                        BrandMention.rank_position,
                    ),
                    else_=None,
                )
            ).label("avg_rank"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.rank_position.is_not(None),
                            BrandMention.rank_position <= 3,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("top3_hits"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.is_recommended.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("rec_hits"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.rank_position == 1,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("top1_hits"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.sentiment == "positive",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sent_pos"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.sentiment == "neutral",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sent_neu"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.is_mention > 0,
                            BrandMention.sentiment == "negative",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sent_neg"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
            *brand_filter,
        )
        .group_by(BrandMention.brand, BrandMention.is_self)
    ).all()

    total_subtasks = db.scalar(
        select(func.count(func.distinct(BrandMention.subtask_id))).where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
            *brand_filter,
        )
    ) or 0

    # ------------------------------------------------------------
    # 1b. Previous-window rollup for the 4 deltas.
    # ------------------------------------------------------------
    days_n = (win_end - win_start).days + 1
    # < 7 天的环比无统计意义(spec §1.3):四 delta 置 None,
    # previous_window_* 留空,跳过整段 SQL。
    prev_by_brand: dict[str, dict[str, float]] = {}
    prev_window_start_d: date | None = None
    prev_window_end_d: date | None = None
    if days_n >= 7:
        prev_window_end_d = win_start - timedelta(days=1)
        prev_window_start_d = prev_window_end_d - timedelta(days=days_n - 1)
        prev_start_dt = datetime.combine(prev_window_start_d, time.min)
        prev_end_dt = datetime.combine(prev_window_end_d, time.max)
        prev_brand_rows = db.execute(
            select(
                BrandMention.brand,
                BrandMention.is_self,
                func.sum(case((BrandMention.is_mention > 0, 1), else_=0)).label("matched"),
                func.avg(
                    case(
                        (
                            BrandMention.is_mention > 0,
                            case(
                                (BrandMention.sentiment == "positive", 1.0),
                                (BrandMention.sentiment == "neutral", 0.5),
                                (BrandMention.sentiment == "negative", 0.0),
                                else_=None,
                            ),
                        ),
                        else_=None,
                    )
                ).label("avg_sentiment"),
                func.sum(
                    case(
                        (and_(BrandMention.is_mention > 0, BrandMention.rank_position == 1), 1),
                        else_=0,
                    )
                ).label("top1_hits"),
                func.sum(
                    case(
                        (and_(BrandMention.is_mention > 0, BrandMention.rank_position.is_not(None),
                              BrandMention.rank_position <= 3), 1),
                        else_=0,
                    )
                ).label("top3_hits"),
            )
            .where(
                BrandMention.project_id == project_id,
                BrandMention.created_at >= prev_start_dt,
                BrandMention.created_at <= prev_end_dt,
                *brand_filter,
            )
            .group_by(BrandMention.brand, BrandMention.is_self)
        ).all()

        prev_total_subtasks = db.scalar(
            select(func.count(func.distinct(BrandMention.subtask_id))).where(
                BrandMention.project_id == project_id,
                BrandMention.created_at >= prev_start_dt,
                BrandMention.created_at <= prev_end_dt,
                *brand_filter,
            )
        ) or 0

        for r in prev_brand_rows:
            matched = int(r.matched or 0)
            prev_by_brand[r.brand] = {
                "mention_rate": matched / prev_total_subtasks if prev_total_subtasks else 0.0,
                "top1_rate": int(r.top1_hits or 0) / prev_total_subtasks if prev_total_subtasks else 0.0,
                "top3_rate": int(r.top3_hits or 0) / prev_total_subtasks if prev_total_subtasks else 0.0,
                "avg_sentiment": float(r.avg_sentiment) if r.avg_sentiment is not None else None,
            }

    daily_by_brand: dict[str, dict[date, int]] = {}
    daily_rows = db.execute(
        select(
            BrandMention.brand,
            func.date(BrandMention.created_at).label("day"),
            func.count(func.distinct(BrandMention.subtask_id)).label("c"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_mention > 0,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
            *brand_filter,
        )
        .group_by(BrandMention.brand, func.date(BrandMention.created_at))
    ).all()
    for r in daily_rows:
        daily_by_brand.setdefault(r.brand, {})[r.day] = r.c

    spark_len = min(15, days_n)
    spark_start = win_end - timedelta(days=spark_len - 1)

    def _kpi_for(brand: str, is_self: bool, r) -> CompetitorKpi:
        matched = int(r.matched or 0)
        top3 = int(r.top3_hits or 0)
        rec = int(r.rec_hits or 0)
        top1 = int(r.top1_hits or 0)
        sent_pos = int(r.sent_pos or 0)
        sent_neu = int(r.sent_neu or 0)
        sent_neg = int(r.sent_neg or 0)
        sent_denom = matched if matched else 1
        avg_sent = float(r.avg_sentiment) if r.avg_sentiment is not None else None
        avg_rk = float(r.avg_rank) if r.avg_rank is not None else None
        display_name, aliases, _is_self_lookup = name_by_brand.get(
            brand, (brand, None, is_self)
        )
        spark: list[int] = []
        for i in range(spark_len):
            d = spark_start + timedelta(days=i)
            if d < win_start:
                spark.append(0)
            else:
                spark.append(daily_by_brand.get(brand, {}).get(d, 0))
        prev = prev_by_brand.get(brand, {})
        mention_rate_delta = (
            (matched / total_subtasks) - prev.get("mention_rate")
            if prev and total_subtasks else None
        )
        top1_rate_delta = (
            (top1 / total_subtasks) - prev.get("top1_rate")
            if prev and total_subtasks else None
        )
        top3_rate_delta = (
            (top3 / total_subtasks) - prev.get("top3_rate")
            if prev and total_subtasks else None
        )
        sentiment_delta = (
            avg_sent - prev.get("avg_sentiment")
            if prev and avg_sent is not None and prev.get("avg_sentiment") is not None
            else None
        )
        return CompetitorKpi(
            brand=brand,
            name=display_name,
            aliases=aliases,
            is_self=is_self,
            is_mention=matched,
            mention_rate=matched / total_subtasks if total_subtasks else 0.0,
            top3_rate=top3 / total_subtasks if total_subtasks else 0.0,
            recommend_rate=rec / total_subtasks if total_subtasks else 0.0,
            avg_sentiment=avg_sent,
            avg_rank=avg_rk,
            spark=spark,
            top1_rate=top1 / total_subtasks if total_subtasks else 0.0,
            sentiment_positive=sent_pos / sent_denom,
            sentiment_neutral=sent_neu / sent_denom,
            sentiment_negative=sent_neg / sent_denom,
            mention_rate_delta=mention_rate_delta,
            top1_rate_delta=top1_rate_delta,
            top3_rate_delta=top3_rate_delta,
            sentiment_delta=sentiment_delta,
        )

    self_kpi: CompetitorKpi | None = None
    competitor_kpis: list[CompetitorKpi] = []
    for r in brand_rows:
        kpi = _kpi_for(r.brand, bool(r.is_self), r)
        if r.is_self:
            self_kpi = kpi
        else:
            competitor_kpis.append(kpi)
    competitor_kpis.sort(key=lambda k: k.is_mention, reverse=True)

    labels: list[str] = []
    for i in range(days_n):
        d = win_start + timedelta(days=i)
        labels.append(d.isoformat())

    def _series_for(brand: str, name: str, is_self: bool, color: str) -> CompetitorTrendSeries:
        per_day = daily_by_brand.get(brand, {})
        data = [per_day.get(win_start + timedelta(days=i), 0) for i in range(days_n)]
        return CompetitorTrendSeries(
            brand=brand, name=name, is_self=is_self, color=color, data=data,
        )

    series: list[CompetitorTrendSeries] = []
    if self_kpi is not None:
        series.append(
            _series_for(self_kpi.brand, self_kpi.name, True, _COMPETITOR_LINE_COLORS[0])
        )
    for i, kpi in enumerate(competitor_kpis[:5], start=1):
        series.append(
            _series_for(
                kpi.brand, kpi.name, False,
                _COMPETITOR_LINE_COLORS[i % len(_COMPETITOR_LINE_COLORS)],
            )
        )

    trend_block = CompetitorTrendBlock(labels=labels, series=series)

    diff_brand = _compute_diff_brand(
        db,
        project_id,
        win_start_dt,
        win_end_dt,
        self_kpi,
        competitor_kpis,
        selected_triples=selected_triples,
        selected_prompt_texts=selected_prompt_texts,
    )

    return CompetitorAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days_n,
        total_subtasks=int(total_subtasks),
        self_brand=self_kpi,
        competitors=competitor_kpis,
        trend=trend_block,
        diff_brand=diff_brand,
        previous_window_start=prev_window_start_d,
        previous_window_end=prev_window_end_d,
    )