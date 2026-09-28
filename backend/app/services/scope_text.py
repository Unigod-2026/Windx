"""拼装报告的"人话筛选范围"文案。

存进 ``geo_reports.scope_text``,在列表与预览页直接展示。
不存原始 platform_codes / prompts 数组 — spec §2.5 明确这个选择。

拼装规则:
- 周期:days 预设 → "近 N 天";自定义 → "自定义 YYYY-MM-DD ~ YYYY-MM-DD"。
  (本期 API 不暴露 days 预设,只接 start/end — 全走自定义格式,后续
  API 升级时再扩 days 预设。)
- 模型:None → "全部模型";空 list → "全部模型"(与 GlobalToolbar
  null-means-all 一致);N > 0 → "N 档模型"。
- 问题:同上 → "全部问题" / "N 个问题"。

三段用 " · " 拼接,跟示例周报 + frontend 元数据行的视觉语言一致。
"""

from __future__ import annotations

from datetime import date


def compose_scope_text(
    *,
    period_start: date,
    period_end: date,
    platform_codes: list[str] | None,
    prompts: list[int] | None,
) -> str:
    period = f"自定义 {period_start.isoformat()} ~ {period_end.isoformat()}"

    if not platform_codes:
        models = "全部模型"
    else:
        models = f"{len(platform_codes)} 档模型"

    if not prompts:
        question = "全部问题"
    else:
        question = f"{len(prompts)} 个问题"

    return f"{period} · {models} · {question}"
