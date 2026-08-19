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
    populated with self + competitors + trend. 暂未含新字段(top1 /
    情感三档 / 环比 / diff 三件套),后续 task 增量加。
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
    prev_end_dt = win_start_dt - timedelta(seconds=1)
    prev_start_dt = prev_end_dt - timedelta(days=days_n - 1)
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

    prev_window_start_d: date = prev_start_dt.date()
    prev_window_end_d: date = prev_end_dt.date()

    prev_by_brand: dict[str, dict[str, float]] = {}
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

    return CompetitorAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days_n,
        total_subtasks=int(total_subtasks),
        self_brand=self_kpi,
        competitors=competitor_kpis,
        trend=trend_block,
        diff_core={"labels": [], "self": [], "competitor_avg": []},
        diff_model=[],
        diff_quadrant=[],
        previous_window_start=prev_window_start_d if prev_brand_rows else None,
        previous_window_end=prev_window_end_d if prev_brand_rows else None,
    )