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
    daily_raw = report_metrics.daily_mention_rate(
        ctx.db,
        project_id=ctx.project.id,
        window_start=ctx.period_start,
        window_end_exclusive=ctx.period_end_exclusive,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )
    daily = report_metrics.fill_window_gaps(
        daily_raw, ctx.period_start, ctx.period_end_exclusive
    )

    breakdown_raw = report_metrics.platform_breakdown(
        ctx.db,
        project_id=ctx.project.id,
        current_start=ctx.period_start,
        current_end_exclusive=ctx.period_end_exclusive,
        previous_start=ctx.previous_start,
        previous_end_exclusive=ctx.previous_end_exclusive,
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
        since_date=ctx.period_start,
        platform_codes=ctx.platform_codes,
        prompts=ctx.prompts,
    )

    # ---- Section 三.3: 问题×平台 矩阵 ----
    platform_codes_in_window = sorted({
        r[0] for r in ctx.db.execute(
            select(Subtask.platform).distinct()
        ).all() if r[0]
    })
    matrix_rows: list[dict] = []
    if platform_codes_in_window:
        rows = ctx.db.execute(
            select(Subtask.prompt, Subtask.platform)
            .join(Task, Task.task_id == Subtask.task_id)
            .join(Project, Project.id == Task.project_id)
            .join(
                BrandMention,
                (BrandMention.subtask_id == Subtask.subtask_id)
                & (BrandMention.brand == func.coalesce(Project.brand, ""))
            )
            .where(
                Task.project_id == ctx.project.id,
                Task.created_local_at >= ctx.period_start,
                Task.created_local_at < ctx.period_end_exclusive,
                BrandMention.extract_status == ExtractStatus.SUCCESS,
                Subtask.platform.in_(platform_codes_in_window),
                *([Subtask.platform.in_(ctx.platform_codes)] if ctx.platform_codes else []),
                *([Subtask.prompt.in_(ctx.prompts)] if ctx.prompts else []),
            )
        ).all()
        mentioned_by_prompt: dict[str, set[str]] = {}
        for p_text, p_code in rows:
            mentioned_by_prompt.setdefault(p_text, set()).add(p_code)

        proj_prompts_rows = ctx.db.execute(
            select(ProjectPrompt.id, ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == ctx.project.id
            ).order_by(ProjectPrompt.sort)
        ).all()
        for pid, p_text in proj_prompts_rows:
            mentioned = mentioned_by_prompt.get(p_text, set())
            matrix_rows.append({
                "prompt_id": pid,
                "prompt_text": p_text,
                "per_platform": {
                    pc: (pc in mentioned) for pc in platform_codes_in_window
                },
            })

    # ---- Section 三.2: 平台简评 ----
    platform_summary: list[dict] = []
    for r in breakdown:
        if r["delta_pp"] > 0.0005:
            direction = "↑"
        elif r["delta_pp"] < -0.0005:
            direction = "↓"
        else:
            direction = "="
        sign = "+" if r["delta_pp"] > 0 else ""
        platform_summary.append({
            "platform_code": r["platform_code"],
            "platform_label": r["platform_label"],
            "note": (
                f"{r['platform_label']}: 本期 {r['current_mentioned']}/{r['current_total']} "
                f"提及 {direction} {sign}{r['delta_pp'] * 100:.1f}pp"
            ),
        })

    return {
        "project": {
            "id": ctx.project.id,
            "name": ctx.project.name,
            "brand": ctx.project.brand,
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
        "platform_summary": platform_summary,
        "prompt_platform_matrix": matrix_rows,
        "weekly_changes": changes,
        "zero_mention_prompts": zero_prompts,
        # ---- 二、本周总结 (4 块,运营手填) ----
        "weekly_summary": {
            "core_finding": None,
            "platform_dynamic": None,
            "content_result": None,
            "scene_coverage": None,
        },
        # ---- 四、内容运营 (no data source yet) ----
        "content_ops": None,
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
            "hint": "下一阶段重点关注的归因分析",
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
