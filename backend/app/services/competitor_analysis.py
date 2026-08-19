"""竞品分析 (data tab → 竞品分析) 计算服务。

本文件按页面分开,把所有竞品分析相关的 SQL/聚合/序列化集中在这里,
``api/projects.py`` 只剩薄壳 endpoint 调 :func:`compute_competitor_analysis`。
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException

from app.models.common import now_local


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