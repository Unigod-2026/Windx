"""Pydantic schemas for the report surface.

The MVP exposes four endpoints:

- ``GET  /api/reports``                       — list reports for one project
- ``POST /api/reports``                       — generate a new report
- ``GET  /api/reports/{report_id}``           — structured snapshot for preview
- ``GET  /api/reports/{report_id}/html``      — stream the HTML body (download)

The wire shape is ``Report`` (one row) / ``ReportOut`` (envelope for
the list endpoint) / ``GenerateReportIn`` (request body for generate) /
``ReportSnapshotOut`` (preview payload).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class Report(BaseModel):
    """One generated report row — drives the list endpoint."""

    id: int
    project_id: int
    template_id: str
    title: str
    manual_overrides: dict
    is_published: bool
    scope_text: str
    # Public-share token. Always non-empty for rows produced by
    # ``POST /api/reports`` after 2026-09-24. The preview page is
    # reachable via ``/public/reports/{share_token}`` without auth.
    share_token: str
    period_start: date
    period_end: date
    baseline_date: date | None
    baseline_rate: float | None
    generated_by_id: int
    generated_by_name: str
    generated_at: datetime


class ReportOut(BaseModel):
    items: list[Report]


class ReportMeta(BaseModel):
    """Subset of ``Report`` shown alongside the rendered snapshot —
    previews surface the title / scope / generated_at without needing
    a second list call."""

    id: int
    project_id: int
    template_id: str
    title: str
    manual_overrides: dict
    is_published: bool
    scope_text: str
    share_token: str
    period_start: date
    period_end: date
    baseline_date: date | None
    baseline_rate: float | None
    generated_by_id: int
    generated_by_name: str
    generated_at: datetime


class ReportSnapshotOut(BaseModel):
    """Structured snapshot for the fullscreen preview page.

    ``snapshot`` is the dict shape ``report_templates.weekly_summary``
    returns — see that module's docstring for the schema. We keep it
    as ``dict`` (no model) because the schema differs per template_id;
    adding a typed model would mean changing it on every template
    addition.
    """

    meta: ReportMeta
    template_id: str
    snapshot: dict


class ReportTemplateOut(BaseModel):
    """One row in the template metadata list returned by
    ``GET /api/reports/templates``.

    Only templates that are **both** configured in
    ``report_settings.json`` **and** registered in
    ``app.services.report_templates.TEMPLATES`` are returned. An
    operator-typo'd id (in the file but not in code) is silently
    dropped — they only see what they can actually generate.
    """

    id: str
    name: str
    description: str | None


class ReportTemplateListOut(BaseModel):
    items: list[ReportTemplateOut]


class GenerateReportIn(BaseModel):
    project_id: int = Field(gt=0)
    template_id: str = Field(min_length=1, max_length=64)
    period_start: date
    period_end: date
    """Optional snapshot overrides. ``None`` falls back to
    ``report_settings.get_baseline(project_id)``."""

    baseline_date: date | None = None
    baseline_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    # Optional toolbar filter; ``None`` = no filter (mirrors GlobalToolbar).
    # ``platform_codes`` are raw ``Subtask.platform`` values (``doubao`` /
    # ``doubao_mobile`` ...); the API doesn't translate compound toolbar
    # keys — the frontend does that before posting.
    platform_codes: list[str] | None = None
    # ProjectPrompt.id values, NOT prompt strings. Router resolves to
    # strings via ProjectPrompt.prompt before pushing into the metrics
    # layer.
    prompts: list[int] | None = None

