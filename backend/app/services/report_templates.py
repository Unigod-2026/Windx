"""Report template registry.

Templates are pure Python callables keyed by ``template_id`` (a short
string). Adding a new template = write one function that consumes the
``BuildContext`` and returns a snapshot dict that
:mod:`app.services.report_render` knows how to render.

Snapshot shape (consumed by :func:`report_render.render_html`):

    {
      "project": {"id": int, "name": str, "brand": str | None},
      "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
      "baseline": {"date": "YYYY-MM-DD" | None, "rate": float | None},
      "title": str,                # shown as <title> + page heading
      "generated_by": str,         # display_name of the user who ran it
      "generated_at": str,         # Asia/Shanghai wall clock, ISO format
      "daily_mention_rate": [
          {"date": "YYYY-MM-DD", "total": int, "mentioned": int, "rate": float},
          ...
      ],
      "platform_breakdown": [
          {
            "platform_code": str,        # raw Subtask.platform value
            "platform_label": str,       # human-readable Chinese name
            "current_total": int, "current_mentioned": int, "current_rate": float,
            "previous_total": int, "previous_mentioned": int, "previous_rate": float,
            "delta_pp": float,
          },
          ...
      ],
    }

Why a Python dict (not Jinja2 / JSON config):
- Templates run server-side with full SQLAlchemy session access; they
  pull their own data via the metrics helpers, no need to expose query
  knobs to operators.
- One template = one function. Adding a section is a code change in
  the same module, easier to review than a separate JSON schema.
- Unit tests can patch ``TEMPLATES`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import AdminUser
from app.models.enums import ExtractStatus
from app.models.project import BrandMention, Project, ProjectPrompt
from app.models.task import Subtask, Task
from app.services import report_metrics
from app.services.platform_labels import platform_label_for_code
from app.services.report_render import default_title


@dataclass(frozen=True)
class BuildContext:
    """Per-build inputs that the template closure receives."""

    db: Session
    project: Project
    period_start: date
    period_end_exclusive: date
    previous_start: date
    previous_end_exclusive: date
    baseline_date: date | None
    baseline_rate: float | None
    generated_by: AdminUser
    generated_at: datetime
    prompts: list[str] | None  # pre-resolved from selected prompt ids
    platform_codes: list[str] | None  # raw Subtask.platform values, None = no filter


# --------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------- #


def weekly_summary(ctx: BuildContext) -> dict:
    """Section 1 + 3.1 of the reference weekly report.

    Aggregates per-day mention rate and per-platform current-vs-previous
    rate, then shapes them into the snapshot dict the renderer expects.
    """
    # 1.1 走势:从基线日期画到今天 — 包含到 today 的最新数据,便于看实时趋势
    # 窗口延到 max(period_end_exclusive, today+1day),这样快照里有今天的数据点。
    # KPI 仍只看 period_end 那天的数据(用 snapshot.period.end 在前端过滤),不混用。
    from app.models.common import now_local
    chart_window_start = ctx.baseline_date or ctx.period_start
    today_excl = now_local().date() + timedelta(days=1)
    chart_window_end = max(ctx.period_end_exclusive, today_excl)
    daily_raw = report_metrics.daily_mention_rate(
        ctx.db,
        project_id=ctx.project.id,
        window_start=chart_window_start,
        window_end_exclusive=chart_window_end,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )
    daily = daily_raw  # 不补零天,保持「只显示有数据的快照日期」
    chart_end_date = (chart_window_end - timedelta(days=1)).isoformat()

    # 3.1 章节口径:仅取周期末日(period.end)与「上周同日」(period.start - 1)的
    # 单日数据 — 不是窗口均值。窗口长度由用户在 GenerateReportIn.period_start/end
    # 决定,3.1 比较的是两端点这两个具体日期。
    breakdown_raw = report_metrics.platform_breakdown(
        ctx.db,
        project_id=ctx.project.id,
        current_start=ctx.period_end_exclusive - timedelta(days=1),
        current_end_exclusive=ctx.period_end_exclusive,
        previous_start=ctx.period_start - timedelta(days=1),
        previous_end_exclusive=ctx.period_start,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )
    breakdown = [
        {
            **row,
            "platform_label": platform_label_for_code(row["platform_code"]),
        }
        for row in breakdown_raw
    ]

    # ---- Section 三.3 / 五.2: 边际变化 + 零提及问题 ----
    changes = report_metrics.weekly_changes(
        ctx.db,
        project_id=ctx.project.id,
        current_start=ctx.period_start,
        current_end_exclusive=ctx.period_end_exclusive,
        previous_start=ctx.previous_start,
        previous_end_exclusive=ctx.previous_end_exclusive,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )
    zero_prompts = report_metrics.zero_mention_prompts(
        ctx.db,
        project_id=ctx.project.id,
        since_date=ctx.baseline_date or ctx.period_start,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )

    # ---- Section 三.3: 问题×平台 矩阵 ----
    # 3.2 章节(每个问题的具体提及率)— 数据源只 BrandMention,不复用 Subtask。
    # 列 = (platform, delivery, thinking_mode) 组合 — 包含「整窗内出现过该组合但本周 0 提及」的列。
    # 行 = 项目配置的 prompt。
    matrix_keys: list[tuple[str, str, str]] = []
    mentioned_by_prompt: dict[str, set[tuple]] = {}

    # 1. 先列全集:窗口内所有出现过的 (platform, delivery, thinking_mode) 组合,
    #    与 is_mention 无关(总提及率 = 0 的列也要显示)。
    all_combo_rows = ctx.db.execute(
        select(
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
        ).where(
            BrandMention.project_id == ctx.project.id,
            BrandMention.is_self == True,
            BrandMention.extract_status != ExtractStatus.PENDING,
            BrandMention.created_at >= ctx.period_start,
            BrandMention.created_at < ctx.period_end_exclusive,
            *([BrandMention.platform.in_(ctx.platform_codes)] if ctx.platform_codes else []),
        ).distinct()
    ).all()
    seen: set[tuple] = set()
    for p_code, delivery, thinking in all_combo_rows:
        key = (p_code or "", (delivery or "web").lower(), "think" if thinking else "fast")
        if key not in seen:
            matrix_keys.append(key)
            seen.add(key)

    # 2. 再查提及明细:is_mention=1 的 (prompt, combo) 关系
    rows = ctx.db.execute(
        select(
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            BrandMention.prompt,
        ).where(
            BrandMention.project_id == ctx.project.id,
            BrandMention.is_self == True,
            BrandMention.is_mention == 1,
            BrandMention.extract_status != ExtractStatus.PENDING,
            BrandMention.created_at >= ctx.period_start,
            BrandMention.created_at < ctx.period_end_exclusive,
            *([BrandMention.platform.in_(ctx.platform_codes)] if ctx.platform_codes else []),
            *([BrandMention.prompt.in_(ctx.prompts)] if ctx.prompts else []),
        )
    ).all()
    for p_code, delivery, thinking, p_text in rows:
        if not p_text:
            continue
        key = (p_code or "", (delivery or "web").lower(), "think" if thinking else "fast")
        mentioned_by_prompt.setdefault(p_text, set()).add(key)

    proj_prompts_rows = ctx.db.execute(
        select(ProjectPrompt.id, ProjectPrompt.prompt).where(
            ProjectPrompt.project_id == ctx.project.id,
            # 2026-09-29 修复:运营在 toolbar 选了 N 个问题,但这里会把项目里
            # 全部 prompt 都铺出来。``ctx.prompts`` 是生成时解析的 prompt
            # **文本**;None/空 = 全选(向后兼容,行为同前)。
            *([ProjectPrompt.prompt.in_(ctx.prompts)] if ctx.prompts else []),
        ).order_by(ProjectPrompt.sort)
    ).all()
    matrix_rows: list[dict] = []
    for pid, p_text in proj_prompts_rows:
        mentioned = mentioned_by_prompt.get(p_text, set())
        matrix_rows.append({
            "prompt_id": pid,
            "prompt_text": p_text,
            "per_platform": {
                f"{pc}|{d}|{t}": ((pc, d, t) in mentioned)
                for (pc, d, t) in matrix_keys
            },
        })

    # ---- (删)平台简评 3.2 — 产品决策移除,不再生成 platform_summary 字段

    # ---- Section 三.4: 稳定提及的前 N 个问题(基线至今累计) ----
    # 窗口:基线日期 → 今天(实时累计),与 1.1 走势图同步
    stable_window_end = max(ctx.period_end_exclusive, now_local().date() + timedelta(days=1))
    stable_result = report_metrics.top_stable_prompts(
        ctx.db,
        project_id=ctx.project.id,
        window_start=ctx.baseline_date or ctx.period_start,
        window_end_exclusive=stable_window_end,
        top_n=5,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )

    # ---- 四、内容运营 ----
    # 4 张 KPI 卡片的数据源:own_articles 表 + 全信源池引用 join + 周期末日提及率。
    # 发布明细表 / 引用分布表 / TOP10 仍为 None —— spec §9 明确不做。
    # 周期末日提及率 = period.end 单日数据(同 Section 一 的「整体提及率」口径)。
    content_ops_period_end = report_metrics.daily_mention_rate(
        ctx.db,
        project_id=ctx.project.id,
        window_start=ctx.period_end_exclusive - timedelta(days=1),
        window_end_exclusive=ctx.period_end_exclusive,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )
    period_end_rate: float | None = None
    if content_ops_period_end:
        period_end_rate = float(content_ops_period_end[0]["rate"])
    citation_metrics = report_metrics.compute_citation_metrics(
        ctx.db,
        project_id=ctx.project.id,
        window_start=ctx.period_start,
        window_end_exclusive=ctx.period_end_exclusive,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
        top_n=10,
    )
    content_ops = {
        "weekly_post_count": report_metrics.weekly_post_count(
            ctx.db,
            project_id=ctx.project.id,
            window_start=ctx.period_start,
            window_end_exclusive=ctx.period_end_exclusive,
        ),
        "distribution_count": report_metrics.weekly_distribution_count(
            ctx.db,
            project_id=ctx.project.id,
            window_start=ctx.period_start,
            window_end_exclusive=ctx.period_end_exclusive,
        ),
        "channel_count": report_metrics.weekly_channel_count(
            ctx.db,
            project_id=ctx.project.id,
            window_start=ctx.period_start,
            window_end_exclusive=ctx.period_end_exclusive,
        ),
        "citation_count": citation_metrics["citation_count"],
        "period_end_mention_rate": period_end_rate,
        # 4.1 表(发布明细)+ 4.2 ①(引用按平台分布)+ 4.2 ②(引用 TOP10)
        "publish_detail": report_metrics.weekly_publish_detail(
            ctx.db,
            project_id=ctx.project.id,
            window_start=ctx.period_start,
            window_end_exclusive=ctx.period_end_exclusive,
        ),
        "citation_by_platform": citation_metrics["citation_by_platform"],
        "citation_top_articles": citation_metrics["citation_top_articles"],
    }

    return {
        "project": {
            "id": ctx.project.id,
            "name": ctx.project.name,
            "brand": ctx.project.brand,
            # 页脚「所属公司 X / 仅供 X 内部使用」用 —— 客户主体,对应示例 PDF 的「山高制药」
            "customer_name": ctx.project.customer.name,
        },
        "period": {
            "start": ctx.period_start.isoformat(),
            "end": (ctx.period_end_exclusive - timedelta(days=1)).isoformat(),
        },
        "baseline": (
            {
                "date": ctx.baseline_date.isoformat(),
                "rate": ctx.baseline_rate,
            }
            if ctx.baseline_date is not None and ctx.baseline_rate is not None
            else {"date": None, "rate": None}
        ),
        "title": default_title(
            ctx.project.name, ctx.period_start, ctx.period_end_exclusive - timedelta(days=1)
        ),
        # 图表 X 轴终点(实时延伸到今天),用于 Sparkline 定位 — KPI 仍按 period_end 取数
        "chart_end_date": chart_end_date,
        # 上一周期末日(供 3.1 表格表头)— 与 period 长度同步
        "previous_end_date": (ctx.previous_end_exclusive - timedelta(days=1)).isoformat(),
        "generated_by": ctx.generated_by.display_name,
        "generated_at": ctx.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "daily_mention_rate": [
            {
                "date": row["date"].isoformat(),
                "total": row["total"],
                "mentioned": row["mentioned"],
                "rate": row["rate"],
            }
            for row in daily
        ],
        "platform_breakdown": breakdown,
        "prompt_platform_matrix": matrix_rows,
        "weekly_changes": changes,
        "zero_mention_prompts": zero_prompts,
        # ---- 1.1 走势说明(图表下方那段文字,运营手填) ----
        "weekly_chart_summary": None,
        # ---- 4.1 发布明细说明(4.1 表格下方那段文字,运营手填) ----
        "weekly_publish_summary": None,
        # ---- 3.3 稳定提及的前 N 个问题 ----
        "stable_prompts": stable_result["stable_prompts"],
        "total_monitor_days": stable_result["total_monitor_days"],
        # ---- 3.1 平台周环比说明(3.1 表格下方那段文字,运营手填) ----
        "weekly_platform_summary": None,
        # ---- 5.1 持续未提及说明(5.1 表格下方那段文字,运营手填) ----
        "weekly_zero_mention_summary": None,
        # ---- 5.2 本周边际变化解读(5.2 四张表下方那段文字,运营手填) ----
        "weekly_change_summary": None,
        # ---- 二、本周总结 (4 块,运营手填) ----
        "weekly_summary": {
            "core_finding": None,
            "platform_dynamic": None,
            "content_result": None,
            "scene_coverage": None,
        },
        "content_ops": content_ops,
        # ---- 5.3 核心归因 (运营手填) ----
        "attribution": None,
    }


# --------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------- #


TemplateFn = Callable[[BuildContext], dict]
TEMPLATES: dict[str, TemplateFn] = {
    "weekly_summary": weekly_summary,
}


# --------------------------------------------------------------------- #
# Editable-field declarations
# --------------------------------------------------------------------- #


# Map of template_id → list of editable section fields.
# Each entry is {key, label, hint}. The ``key`` matches a key in
# ``Report.manual_overrides`` dict; ``label`` and ``hint`` drive the
# preview-page editor UI.
#
# Why this is separate from TEMPLATES (functions): templates run at
# generate-time, but editable-field declarations are static
# configuration. Splitting keeps the function pure-data-flow and the
# field metadata UI-shaped. Adding a new template requires adding both
# an entry to ``TEMPLATES`` and ``TEMPLATE_FIELDS`` with matching
# keys; we assert at module import below.
TEMPLATE_FIELDS: dict[str, list[dict]] = {
    "weekly_summary": [
        {
            "key": "weekly_chart_summary",
            "label": "1.1 走势说明",
            "hint": "图表下方的说明文字,描述本期走势要点",
        },
        {
            "key": "weekly_publish_summary",
            "label": "4.1 发布明细说明",
            "hint": "4.1 表格下方的说明文字,描述本周发布/分发策略要点",
        },
        {
            "key": "weekly_platform_summary",
            "label": "3.1 平台周环比说明",
            "hint": "3.1 表格下方的说明文字,描述平台层面要点",
        },
        {
            "key": "weekly_zero_mention_summary",
            "label": "5.1 持续未提及说明",
            "hint": "5.1 表格下方的说明文字,描述本期持续未提及问题的运营关注点",
        },
        {
            "key": "weekly_change_summary",
            "label": "5.2 本周边际变化解读",
            "hint": "5.2 四张表下方的说明文字,解读本周问题覆盖的正向突破与回落风险",
        },
        {
            "key": "weekly_core_finding",
            "label": "本周核心结论",
            "hint": "1-2 句话总结本周监控结果",
        },
        {
            "key": "weekly_platform_dynamic",
            "label": "平台动态",
            "hint": "本周 AI 平台层面的整体趋势（涨 / 跌 / 稳定）",
        },
        {
            "key": "weekly_content_result",
            "label": "内容成效",
            "hint": "本周发布/分发对提及率的拉动效果",
        },
        {
            "key": "weekly_scene_coverage",
            "label": "场景覆盖",
            "hint": "本周各类问题（放化疗 / 补益类等）的覆盖变化",
        },
        {
            "key": "attribution",
            "label": "5.3 核心归因",
            "hint": "本期空白问题与头部回落的归因说明",
        },
    ],
}


# Every registered template must declare its editable fields. The
# two dicts must agree on which keys are present so a future
# developer adding a new template can't silently leave the editor
# without a config entry.
for _tid in TEMPLATES:
    if _tid not in TEMPLATE_FIELDS:
        raise RuntimeError(
            f"template {_tid!r} registered in TEMPLATES but missing "
            f"from TEMPLATE_FIELDS"
        )


def get(template_id: str) -> TemplateFn:
    if template_id not in TEMPLATES:
        raise KeyError(f"unknown report template: {template_id}")
    return TEMPLATES[template_id]


def list_ids() -> list[str]:
    return list(TEMPLATES.keys())


# --------------------------------------------------------------------- #
# Prompt resolution helper (shared by API router)
# --------------------------------------------------------------------- #


def resolve_prompts(
    db: Session, project_id: int, prompt_ids: list[int] | None
) -> list[str] | None:
    """Map toolbar prompt ids → prompt strings for ``Subtask.prompt`` IN.

    ``None`` / empty list → no filter (mirrors GlobalToolbar's
    null-means-all convention). Subtask stores the literal prompt
    text rather than a FK to ``geo_project_prompts`` so the join is
    on the text column.
    """
    if not prompt_ids:
        return None
    rows = db.execute(
        select(ProjectPrompt.prompt).where(
            ProjectPrompt.project_id == project_id,
            ProjectPrompt.id.in_(prompt_ids),
        )
    ).all()
    return [r[0] for r in rows] if rows else None
