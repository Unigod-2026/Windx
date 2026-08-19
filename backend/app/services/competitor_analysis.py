"""竞品分析 (data tab → 竞品分析) 计算服务。

本文件按页面分开,把所有竞品分析相关的 SQL/聚合/序列化集中在这里,
``api/projects.py`` 只剩薄壳 endpoint 调 :func:`compute_competitor_analysis`。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select

from app.models.common import now_local
from app.models.project import BrandMention, ProjectCompetitor
from app.schemas.project import (
    CompetitorAnalysisOut,
    CompetitorKpi,
    CompetitorTrendBlock,
    CompetitorTrendSeries,
    DiffCore,
    ModelDiff,
    QuadrantPoint,
)


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


def _compute_diff_core(
    self_kpi: CompetitorKpi | None,
    competitor_kpis: list[CompetitorKpi],
) -> DiffCore:
    """核心指标对比 — 3 个指标(mention_rate / top1_rate / top3_rate)的自身 vs 竞品均值,
    单位 0-100(已乘 100),便于 UI 直接画柱状图。spec §2.3。
    """
    labels = ["提及率", "Top1", "Top3"]
    if not self_kpi or not competitor_kpis:
        return DiffCore(
            labels=labels, self_values=[0.0, 0.0, 0.0], competitor_avg=[0.0, 0.0, 0.0]
        )
    n = len(competitor_kpis)
    return DiffCore(
        labels=labels,
        self_values=[
            self_kpi.mention_rate * 100,
            self_kpi.top1_rate * 100,
            self_kpi.top3_rate * 100,
        ],
        competitor_avg=[
            sum(c.mention_rate for c in competitor_kpis) / n * 100,
            sum(c.top1_rate for c in competitor_kpis) / n * 100,
            sum(c.top3_rate for c in competitor_kpis) / n * 100,
        ],
    )


def _compute_diff_model(db, project_id, win_start_dt, win_end_dt):
    """模型维度提及率 — 每个 platform 一行,自身 vs 竞品均值。spec §2.4。

    以 (platform, is_self) 为聚合粒度,按该 platform 在窗口内的
    distinct subtask 数作为分母,分别计算 mention_rate / top1_rate / top3_rate。
    竞品侧是同一 platform 下所有竞品 brand 的算术平均。
    """
    rows = db.execute(
        select(
            BrandMention.platform,
            BrandMention.is_self,
            func.count(func.distinct(BrandMention.subtask_id)).label("total"),
            func.sum(case((and_(BrandMention.mention_count > 0, BrandMention.rank_position == 1), 1), else_=0)).label("top1"),
            func.sum(case((and_(BrandMention.mention_count > 0,
                                  BrandMention.rank_position.is_not(None),
                                  BrandMention.rank_position <= 3), 1), else_=0)).label("top3"),
            func.sum(case((BrandMention.mention_count > 0, 1), else_=0)).label("matched"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
            BrandMention.platform.is_not(None),
        )
        .group_by(BrandMention.platform, BrandMention.is_self)
    ).all()

    by_plat: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows:
        plat = r.platform
        total = int(r.total or 0)
        denom = total if total else 1
        bucket = by_plat.setdefault(plat, {"self": {}, "comp": {}})
        side = "self" if r.is_self else "comp"
        bucket[side] = {
            "mention_rate": int(r.matched or 0) / denom,
            "top1_rate": int(r.top1 or 0) / denom,
            "top3_rate": int(r.top3 or 0) / denom,
        }

    out: list[ModelDiff] = []
    empty_side = {"mention_rate": 0.0, "top1_rate": 0.0, "top3_rate": 0.0}
    for plat, sides in by_plat.items():
        s = sides.get("self") or empty_side
        c = sides.get("comp") or empty_side
        out.append(ModelDiff(
            platform=plat,
            self_mention_rate=s["mention_rate"],
            self_top1_rate=s["top1_rate"],
            self_top3_rate=s["top3_rate"],
            competitor_mention_rate=c["mention_rate"],
            competitor_top1_rate=c["top1_rate"],
            competitor_top3_rate=c["top3_rate"],
        ))
    out.sort(key=lambda m: m.platform)
    return out


def _compute_diff_quadrant(diff_model):
    """四象限 — 从 per-platform 抽 mention_rate 点。每个 platform 一个点。"""
    return [
        QuadrantPoint(
            platform=m.platform,
            self_mention_rate=m.self_mention_rate,
            competitor_avg_mention_rate=m.competitor_mention_rate,
        )
        for m in diff_model
    ]


def compute_competitor_analysis(
    *,
    db,
    project_id: int,
    project,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
) -> CompetitorAnalysisOut:
    """Drives the 竞品分析 tab. Returns a ``CompetitorAnalysisOut``
    populated with self + competitors + trend + diff trio (diff_core /
    diff_model / diff_quadrant) + previous window dates. The 4 deltas on
    each KPI and ``previous_window_*`` are None when ``days < 7``
    (spec §1.3).
    """
    win_start, win_end = _resolve_competitor_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

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
            BrandMention.brand_canonical,
            BrandMention.is_self,
            func.sum(case((BrandMention.mention_count > 0, 1), else_=0)).label("matched"),
            func.count().label("rows_total"),
            func.avg(
                case(
                    (
                        BrandMention.mention_count > 0,
                        case(
                            (BrandMention.sentiment_score == "positive", 1.0),
                            (BrandMention.sentiment_score == "neutral", 0.5),
                            (BrandMention.sentiment_score == "negative", 0.0),
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
                            BrandMention.mention_count > 0,
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
                            BrandMention.mention_count > 0,
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
                            BrandMention.mention_count > 0,
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
                            BrandMention.mention_count > 0,
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
                            BrandMention.mention_count > 0,
                            BrandMention.sentiment_score == "positive",
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
                            BrandMention.mention_count > 0,
                            BrandMention.sentiment_score == "neutral",
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
                            BrandMention.mention_count > 0,
                            BrandMention.sentiment_score == "negative",
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
        )
        .group_by(BrandMention.brand_canonical, BrandMention.is_self)
    ).all()

    total_subtasks = db.scalar(
        select(func.count(func.distinct(BrandMention.subtask_id))).where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
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
                BrandMention.brand_canonical,
                BrandMention.is_self,
                func.sum(case((BrandMention.mention_count > 0, 1), else_=0)).label("matched"),
                func.avg(
                    case(
                        (
                            BrandMention.mention_count > 0,
                            case(
                                (BrandMention.sentiment_score == "positive", 1.0),
                                (BrandMention.sentiment_score == "neutral", 0.5),
                                (BrandMention.sentiment_score == "negative", 0.0),
                                else_=None,
                            ),
                        ),
                        else_=None,
                    )
                ).label("avg_sentiment"),
                func.sum(
                    case(
                        (and_(BrandMention.mention_count > 0, BrandMention.rank_position == 1), 1),
                        else_=0,
                    )
                ).label("top1_hits"),
                func.sum(
                    case(
                        (and_(BrandMention.mention_count > 0, BrandMention.rank_position.is_not(None),
                              BrandMention.rank_position <= 3), 1),
                        else_=0,
                    )
                ).label("top3_hits"),
            )
            .where(
                BrandMention.project_id == project_id,
                BrandMention.created_at >= prev_start_dt,
                BrandMention.created_at <= prev_end_dt,
            )
            .group_by(BrandMention.brand_canonical, BrandMention.is_self)
        ).all()

        prev_total_subtasks = db.scalar(
            select(func.count(func.distinct(BrandMention.subtask_id))).where(
                BrandMention.project_id == project_id,
                BrandMention.created_at >= prev_start_dt,
                BrandMention.created_at <= prev_end_dt,
            )
        ) or 0

        for r in prev_brand_rows:
            matched = int(r.matched or 0)
            prev_by_brand[r.brand_canonical] = {
                "mention_rate": matched / prev_total_subtasks if prev_total_subtasks else 0.0,
                "top1_rate": int(r.top1_hits or 0) / prev_total_subtasks if prev_total_subtasks else 0.0,
                "top3_rate": int(r.top3_hits or 0) / prev_total_subtasks if prev_total_subtasks else 0.0,
                "avg_sentiment": float(r.avg_sentiment) if r.avg_sentiment is not None else None,
            }

    daily_by_brand: dict[str, dict[date, int]] = {}
    daily_rows = db.execute(
        select(
            BrandMention.brand_canonical,
            func.date(BrandMention.created_at).label("day"),
            func.count(func.distinct(BrandMention.subtask_id)).label("c"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.mention_count > 0,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
        .group_by(BrandMention.brand_canonical, func.date(BrandMention.created_at))
    ).all()
    for r in daily_rows:
        daily_by_brand.setdefault(r.brand_canonical, {})[r.day] = r.c

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
            brand_canonical=brand,
            name=display_name,
            aliases=aliases,
            is_self=is_self,
            mention_count=matched,
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
        kpi = _kpi_for(r.brand_canonical, bool(r.is_self), r)
        if r.is_self:
            self_kpi = kpi
        else:
            competitor_kpis.append(kpi)
    competitor_kpis.sort(key=lambda k: k.mention_count, reverse=True)

    labels: list[str] = []
    for i in range(days_n):
        d = win_start + timedelta(days=i)
        labels.append(d.isoformat())

    def _series_for(brand: str, name: str, is_self: bool, color: str) -> CompetitorTrendSeries:
        per_day = daily_by_brand.get(brand, {})
        data = [per_day.get(win_start + timedelta(days=i), 0) for i in range(days_n)]
        return CompetitorTrendSeries(
            brand_canonical=brand, name=name, is_self=is_self, color=color, data=data,
        )

    series: list[CompetitorTrendSeries] = []
    if self_kpi is not None:
        series.append(
            _series_for(self_kpi.brand_canonical, self_kpi.name, True, _COMPETITOR_LINE_COLORS[0])
        )
    for i, kpi in enumerate(competitor_kpis[:5], start=1):
        series.append(
            _series_for(
                kpi.brand_canonical, kpi.name, False,
                _COMPETITOR_LINE_COLORS[i % len(_COMPETITOR_LINE_COLORS)],
            )
        )

    trend_block = CompetitorTrendBlock(labels=labels, series=series)

    diff_core = _compute_diff_core(self_kpi, competitor_kpis)

    diff_model = _compute_diff_model(db, project_id, win_start_dt, win_end_dt)

    diff_quadrant = _compute_diff_quadrant(diff_model)

    return CompetitorAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days_n,
        total_subtasks=int(total_subtasks),
        self_brand=self_kpi,
        competitors=competitor_kpis,
        trend=trend_block,
        diff_core=diff_core,
        diff_model=diff_model,
        diff_quadrant=diff_quadrant,
        previous_window_start=prev_window_start_d,
        previous_window_end=prev_window_end_d,
    )