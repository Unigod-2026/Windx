"""Report API endpoints.

Four endpoints back the 周报 tab:

- ``GET  /api/reports?project_id=...``               list reports for one project
- ``POST /api/reports``                              generate a new report
- ``GET  /api/reports/{report_id}``                  structured snapshot for preview
- ``GET  /api/reports/{report_id}/html``             stream the HTML body (download)

Storage layout (decided upfront — see README 「周报」section):
- HTML files on disk: ``backend/data/reports/{project_id}/{report_id}.html``.
  ``file_path`` column stores the path **relative to backend/** so the
  directory can move without rewriting the table.
- Metadata: ``geo_reports`` row per generated report.

Tenant scope mirrors the rest of the API: ``customer_admin`` users are
restricted to their own ``customer_id``; ``super_admin`` may read any
project's reports.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.common import now_local
from app.models.customer import AdminUser
from app.models.enums import AdminRole
from app.models.project import Project
from app.models.report import Report as ReportRow
from app.schemas.report import (
    GenerateReportIn,
    Report,
    ReportMeta,
    ReportOut,
    ReportSnapshotOut,
    ReportTemplateListOut,
    ReportTemplateOut,
    UpdateReportIn,
)
from app.services import report_render, report_settings, report_templates
from app.services.report_overrides import merge_overrides
from app.services.report_render import _render_admin_html_via_browser, render_html
from app.services.report_templates import TEMPLATE_FIELDS
from app.services.scope_text import compose_scope_text

router = APIRouter(tags=["reports"])

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------- #

# backend/app/api/reports.py → backend/data/reports/...
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPORTS_ROOT = _BACKEND_ROOT / "data" / "reports"


def _project_dir(project_id: int) -> Path:
    return _REPORTS_ROOT / str(project_id)


def _regenerate_report_html(db: Session, row: ReportRow) -> None:
    """用 headless 浏览器渲染 admin 视图,把 HTML 覆写到磁盘。

    渲染源是 admin 路由 ``/reports/:id`` —— 也就是运营在浏览器里看到的
    那份 React 组件树。这样「公网 token URL 看到的」与「admin 编辑视图
    看到的」永远一致,不会有第二套 Python 模板跟 React drift 的问题。

    前置条件:``manual_overrides`` 必须已经 **commit**(浏览器通过独立
    请求读 DB);因此 publish 路径里 operator 的编辑都是先 PATCH 落库再
    publish,天然满足。本函数在 ``is_published`` 置 True **之前**调用,
    但渲染走的是 ``?mode=public`` 只读模式,与 DB 里的发布状态无关 ——
    草稿态也不会把「发布」按钮 / 「编辑」链接烤进公网 HTML。
    """
    html_str = _render_admin_html_via_browser(row.id)

    project_dir = _project_dir(row.project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    abs_path = project_dir / f"{row.id}.html"
    abs_path.write_text(html_str, encoding="utf-8")
    row.file_path = str(abs_path.relative_to(Path(__file__).resolve().parents[2]))


def _generate_unique_share_token(db: Session, *, attempts: int = 5) -> str:
    """Generate a URL-safe random token that doesn't collide with any
    existing ``geo_reports.share_token``.

    ``secrets.token_urlsafe(32)`` produces 256 bits of entropy encoded
    as ~43 base64url characters; enumeration is infeasible. We
    loop-and-retry purely as a safety net against a buggy PRNG.
    """
    for _ in range(attempts):
        token = secrets.token_urlsafe(32)
        exists = db.scalar(
            select(ReportRow.id).where(ReportRow.share_token == token)
        )
        if exists is None:
            return token
    raise RuntimeError("could not generate a unique share_token")


# --------------------------------------------------------------------- #
# Tenant scope helper
# --------------------------------------------------------------------- #


def _scope_clause(user: AdminUser):
    if user.role is AdminRole.CUSTOMER_ADMIN:
        return ReportRow.customer_id == user.customer_id
    return None


# --------------------------------------------------------------------- #
# GET /api/reports/templates — list available templates (auth required)
# --------------------------------------------------------------------- #


@router.get("/api/reports/templates", response_model=ReportTemplateListOut)
def list_report_templates(
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Return templates that are **both** configured in
    ``report_settings.json`` **and** registered in
    ``app.services.report_templates.TEMPLATES``.

    Why the intersection rather than just one source:
    - If we returned ``TEMPLATES`` only, an operator who renames
      a template in the JSON file would still see the old name in the
      UI — confusing.
    - If we returned the JSON list only, an operator could declare
      ids that don't actually generate anything — the modal would
      offer choices that 422 on submit.

    Both halves stay in sync via this endpoint: a typo'd id in the
    JSON is silently dropped (no log noise — a typo'd id is operator
    intent to delete the template from the UI); a registered id
    without a metadata entry falls back to the id itself as the
    display name with no description, so a developer who adds a new
    template to ``TEMPLATES`` but forgets the JSON file still ships
    a usable UI (the drop-down will show ``weekly_summary`` instead
    of the friendly Chinese name).

    Auth: same ``get_current_user`` as the rest of ``/api/reports/*``;
    this is the editor path, not the public preview.
    """
    # Discard the ``db`` parameter — templates come from settings +
    # registry, not from a query. Kept in the signature so the route
    # stays consistent with the file's other endpoints; FastAPI's
    # dependency-injection system will warn if we forget to type it.
    _ = db  # noqa: F841  (intentionally unused)
    _ = user  # noqa: F841  (auth only, no per-user filtering)

    registered = report_templates.list_ids()
    metadata = report_settings.list_template_metadata()
    items: list[ReportTemplateOut] = []
    for tid in registered:
        meta = metadata.get(tid)
        items.append(
            ReportTemplateOut(
                id=tid,
                name=meta.name if meta else tid,
                description=meta.description if meta else None,
            )
        )
    return ReportTemplateListOut(items=items)


# --------------------------------------------------------------------- #
# GET /api/reports/projects/{project_id}/baseline — default baseline
# --------------------------------------------------------------------- #


class ProjectBaselineOut(BaseModel):
    """The project's currently-configured baseline.

    Returned to the generate-modal open handler so the modal can
    pre-fill the two required baseline fields with whatever was
    persisted by the most recent generation. ``null`` fields mean
    "no baseline configured" — the modal will surface this as
    "请填写" rather than fabricating a value.
    """

    project_id: int
    baseline_date: date | None
    baseline_rate: float | None


@router.get(
    "/api/reports/projects/{project_id}/baseline",
    response_model=ProjectBaselineOut,
)
def get_project_baseline(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if (
        user.role is AdminRole.CUSTOMER_ADMIN
        and project.customer_id != user.customer_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")
    baseline = report_settings.get_baseline(project_id)
    return ProjectBaselineOut(
        project_id=project_id,
        baseline_date=baseline.date if baseline else None,
        baseline_rate=baseline.rate if baseline else None,
    )


# --------------------------------------------------------------------- #
# GET /api/reports — list
# --------------------------------------------------------------------- #


@router.get("/api/reports", response_model=ReportOut)
def list_reports(
    project_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if (
        user.role is AdminRole.CUSTOMER_ADMIN
        and project.customer_id != user.customer_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")

    stmt = (
        select(ReportRow)
        .where(ReportRow.project_id == project_id)
        .order_by(ReportRow.created_at.desc())
        .limit(200)
    )
    scope = _scope_clause(user)
    if scope is not None:
        stmt = stmt.where(scope)

    rows = db.execute(stmt).scalars().all()
    items = [
        Report(
            id=r.id,
            project_id=r.project_id,
            template_id=r.template_id,
            title=r.title,
            manual_overrides=r.manual_overrides or {},
            is_published=r.is_published,
            scope_text=r.scope_text,
            share_token=r.share_token,
            period_start=r.period_start,
            period_end=r.period_end,
            baseline_date=r.baseline_date,
            baseline_rate=r.baseline_rate,
            generated_by_id=r.generated_by_id,
            generated_by_name=r.generated_by_name,
            generated_at=r.created_at,
        )
        for r in rows
    ]
    return ReportOut(items=items)


# --------------------------------------------------------------------- #
# POST /api/reports — generate
# --------------------------------------------------------------------- #


_MAX_WINDOW_DAYS = 60


@router.post("/api/reports", response_model=Report, status_code=201)
def generate_report(
    payload: GenerateReportIn,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=422, detail="period_end must be >= period_start")
    days = (payload.period_end - payload.period_start).days + 1
    if days > _MAX_WINDOW_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"window cannot exceed {_MAX_WINDOW_DAYS} days",
        )
    try:
        report_templates.get(payload.template_id)  # 仅校验模板存在
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if (
        user.role is AdminRole.CUSTOMER_ADMIN
        and project.customer_id != user.customer_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")

    # Baseline resolution: the modal makes both fields required, so
    # callers from the UI always send both. We additionally allow the
    # API to be called with neither (e.g. by a future scheduled job)
    # and fall back to whatever is in ``report_settings.json`` — but
    # if THAT is also missing, we 422 rather than generate a baseline-
    # less report (the "较基线" KPI renders as "未配置基线" which is
    # fine for one-off reads but not for a stored report).
    baseline_date = payload.baseline_date
    baseline_rate = payload.baseline_rate
    if (baseline_date is None) != (baseline_rate is None):
        raise HTTPException(
            status_code=422,
            detail="baseline_date and baseline_rate must both be set or both be null",
        )
    if baseline_date is None and baseline_rate is None:
        fallback = report_settings.get_baseline(payload.project_id)
        if fallback is not None and fallback.date is not None and fallback.rate is not None:
            baseline_date = fallback.date
            baseline_rate = fallback.rate
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    "baseline required: pass baseline_date + baseline_rate, "
                    "or pre-configure the project's baseline in "
                    "backend/configs/report_settings.json"
                ),
            )

    # Compose the human-readable scope string now (spec §2.5) so the
    # row carries it from the first write — historical reports stay
    # stable even when toolbar options are later renamed.
    scope_text = compose_scope_text(
        period_start=payload.period_start,
        period_end=payload.period_end,
        platform_codes=payload.platform_codes,
        prompts=payload.prompts,
    )

    # 256-bit URL-safe random token for public sharing. Collision
    # probability is negligible (2^256) but we still loop-and-retry
    # because the column is UNIQUE — a single collision from a buggy
    # PRNG would otherwise turn into a 500.
    share_token = _generate_unique_share_token(db)

    # toolbar 选的 prompt 是 ID,指标函数要的是文本。提前解析,直接存
    # 解析后的文本到行里 —— GET snapshot 时不必再查 geo_project_prompts,
    # 且历史报告不受 prompt 改名/删除影响(参见迁移 20260928_0003)。
    filter_prompts = report_templates.resolve_prompts(
        db, project.id, payload.prompts
    )
    filter_platform_codes = payload.platform_codes

    # Write the metadata row first so we can derive file_path from the
    # autoincrement id (avoids a "filename guess + rename" race).
    row = ReportRow(
        project_id=project.id,
        customer_id=project.customer_id,
        template_id=payload.template_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        baseline_date=baseline_date,
        baseline_rate=baseline_rate,
        # 标题跟 template 的 default_title 同源,避免为了拿标题跑一遍全量
        # snapshot(那会重算所有指标 SQL)。
        title=report_render.default_title(
            project.name, payload.period_start, payload.period_end
        ),
        # 草稿**不生成** HTML —— 未发布的报告需要登录才能看,公网 token
        # URL 直接 404;publish 时才用 headless 浏览器渲染落盘。这样新建
        # 周报的响应时间不再包含 3-5s 的浏览器渲染。
        # 必须是 None 而不是 "" —— file_path 有 UNIQUE 约束,空串只能存
        # 一行,第二份草稿会撞 ``Duplicate entry ''``(见迁移 20260928_0002)。
        file_path=None,
        scope_text=scope_text,
        share_token=share_token,
        filter_prompts=filter_prompts,
        filter_platform_codes=filter_platform_codes,
        generated_by_id=user.id,
        generated_by_name=user.display_name,
        created_at=now_local(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Persist the operator's chosen baseline so the next generation
    # starts from the right value (the modal defaults to whatever's
    # in ``report_settings.json``). We only write if the caller
    # actually supplied values — payload-baseline was already resolved
    # to a real (date, rate) pair above (422 otherwise), so reaching
    # here with a baseline is the only branch.
    if baseline_date is not None and baseline_rate is not None:
        try:
            report_settings.upsert_baseline(
                project_id=payload.project_id,
                baseline_date=baseline_date,
                baseline_rate=baseline_rate,
            )
        except Exception as exc:  # noqa: BLE001
            # Best-effort write — the report row is already committed.
            # Log + continue; the operator still got their report.
            logger.warning(
                "failed to persist baseline for project_id=%s: %s",
                payload.project_id,
                exc,
            )

    return Report(
        id=row.id,
        project_id=row.project_id,
        template_id=row.template_id,
        title=row.title,
        manual_overrides=row.manual_overrides or {},
        is_published=row.is_published,
        scope_text=row.scope_text,
        share_token=row.share_token,
        period_start=row.period_start,
        period_end=row.period_end,
        baseline_date=row.baseline_date,
        baseline_rate=row.baseline_rate,
        generated_by_id=row.generated_by_id,
        generated_by_name=row.generated_by_name,
        generated_at=row.created_at,
    )


# --------------------------------------------------------------------- #
# GET /api/reports/{report_id} — structured snapshot for preview
# --------------------------------------------------------------------- #


@router.get("/api/reports/{report_id}", response_model=ReportSnapshotOut)
def get_report_snapshot(
    report_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Return the structured snapshot for the preview page.

    Re-runs ``report_templates.weekly_summary`` against current data
    rather than parsing the HTML on disk. Two reasons:
    - HTML files are kept for download only; the preview page wants
      React-rendered output with the SPA's visual tokens, not the
      self-contained HTML's inline styles.
    - Re-running picks up any tasks/mentions written since the
      report was originally generated, so the preview always reflects
      what the template would produce *now*. The file is still the
      historical record.

    Same tenant scoping as ``get_report_html``.
    """
    row = db.get(ReportRow, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    scope = _scope_clause(user)
    if scope is not None:
        if db.scalar(
            select(ReportRow.id).where(ReportRow.id == report_id, scope)
        ) is None:
            raise HTTPException(status_code=403, detail="forbidden")

    project = db.get(Project, row.project_id)
    if project is None:
        raise HTTPException(status_code=410, detail="project deleted")

    days = (row.period_end - row.period_start).days + 1
    try:
        template_fn = report_templates.get(row.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc

    # Historical reports don't store raw prompt ids (spec §2.5), so
    # we re-run with no prompt filter — matches what the file on disk
    # represents. platform_codes also default to None.
    # 2026-09-28 修复:之前的实现「永远传 None」让生成时的 toolbar 筛选
    # 选择落空;现在从行里读生成时解析并保存的文本/平台原样传给
    # BuildContext。两列允许 NULL,所以历史报告(没有的列)退回到无筛选,
    # 行为与改动前一致。
    ctx = report_templates.BuildContext(
        db=db,
        project=project,
        period_start=row.period_start,
        period_end_exclusive=row.period_end + timedelta(days=1),
        previous_start=row.period_start - timedelta(days=days),
        previous_end_exclusive=row.period_start,
        baseline_date=row.baseline_date,
        baseline_rate=row.baseline_rate,
        generated_by=user,
        generated_at=row.created_at,
        prompts=row.filter_prompts,
        platform_codes=row.filter_platform_codes,
    )
    snapshot = template_fn(ctx)
    # Patch generated_by / generated_at so the preview shows the
    # historical record, not "now" — template_fn would otherwise use
    # ``ctx.generated_by`` which we just set to the current viewer.
    snapshot["generated_by"] = row.generated_by_name
    snapshot["generated_at"] = row.created_at.strftime("%Y-%m-%d %H:%M:%S")
    merge_overrides(snapshot, row.manual_overrides or {})

    return ReportSnapshotOut(
        meta=ReportMeta(
            id=row.id,
            project_id=row.project_id,
            template_id=row.template_id,
            title=row.title,
            manual_overrides=row.manual_overrides or {},
            is_published=row.is_published,
            scope_text=row.scope_text,
            share_token=row.share_token,
            period_start=row.period_start,
            period_end=row.period_end,
            baseline_date=row.baseline_date,
            baseline_rate=row.baseline_rate,
            generated_by_id=row.generated_by_id,
            generated_by_name=row.generated_by_name,
            generated_at=row.created_at,
        ),
        template_id=row.template_id,
        snapshot=snapshot,
    )


# --------------------------------------------------------------------- #
# PATCH /api/reports/{report_id} — save manual overrides
# --------------------------------------------------------------------- #


@router.patch("/api/reports/{report_id}", response_model=Report)
def update_report(
    report_id: int,
    payload: UpdateReportIn,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Save operator-edited narrative content (save-as-draft).

    **Merges** the supplied dict into the report's existing
    ``manual_overrides`` — keys not present in the payload keep their
    previously-saved value. The preview UI saves one block per
    request, so a wholesale replace would silently erase every block
    the operator filled in earlier.

    Keys must be declared in the template's ``TEMPLATE_FIELDS``; an
    unrecognized key returns 422 so a stale client doesn't sneak
    garbage into the persisted JSON.

    Drafts (is_published=False) are the default — calling this
    endpoint does NOT publish. Use POST .../publish for that.
    """
    row = db.get(ReportRow, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    if (
        user.role is AdminRole.CUSTOMER_ADMIN
        and row.customer_id != user.customer_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")

    # Validate keys against the template's editable-field list. We
    # only check field presence — values can be empty strings (operator
    # may want to clear a field they previously filled).
    editable_keys = {
        f["key"]
        for fields in TEMPLATE_FIELDS.values()
        for f in fields
    }
    bad_keys = set(payload.manual_overrides.keys()) - editable_keys
    if bad_keys:
        raise HTTPException(
            status_code=422,
            detail=f"unknown manual_overrides keys: {sorted(bad_keys)}",
        )

    # Assign a NEW dict rather than mutating in place — SQLAlchemy
    # doesn't track in-place mutation of a JSON column.
    row.manual_overrides = {
        **(row.manual_overrides or {}),
        **payload.manual_overrides,
    }
    db.commit()
    db.refresh(row)
    return Report(
        id=row.id,
        project_id=row.project_id,
        template_id=row.template_id,
        title=row.title,
        scope_text=row.scope_text,
        share_token=row.share_token,
        period_start=row.period_start,
        period_end=row.period_end,
        baseline_date=row.baseline_date,
        baseline_rate=row.baseline_rate,
        manual_overrides=row.manual_overrides or {},
        is_published=row.is_published,
        generated_by_id=row.generated_by_id,
        generated_by_name=row.generated_by_name,
        generated_at=row.created_at,
    )


# --------------------------------------------------------------------- #
# POST /api/reports/{report_id}/publish — flip is_published=True
# --------------------------------------------------------------------- #


@router.post("/api/reports/{report_id}/publish", response_model=Report)
def publish_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Publish the report: makes its public URL accessible.

    No field-level validation — partial overrides are allowed and
    unfilled sections render as "暂无数数据" on the public page.
    Operator workflow: publish early, fill later (also via
    ``unpublish`` → edit → ``publish``).

    Side effects:
      - 若之前 ``is_published=False``,本次轮换 ``share_token`` —— 旧的公开
        URL 立即失效,避免被缓存 / 截屏引用了「草稿 ID」后还能看。
      - 用当前 ``manual_overrides`` 重新渲染 HTML 写盘,public URL 看到的
        是这次 publish 的快照;后续编辑不会自动反映到 public 页面,
        必须重新 publish。
    """
    row = db.get(ReportRow, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    if (
        user.role is AdminRole.CUSTOMER_ADMIN
        and row.customer_id != user.customer_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")

    # 每次 publish 都轮换 token —— 不论首次发布还是「重新发布」,
    # 运营点这个按钮的语义就是「重新暴露一份对外链接」,旧 URL 应立即
    # 失效,防止被截屏 / 群发后还能看到上一版内容。
    row.share_token = _generate_unique_share_token(db)
    _regenerate_report_html(db, row)
    row.is_published = True
    db.commit()
    db.refresh(row)
    return Report(
        id=row.id,
        project_id=row.project_id,
        template_id=row.template_id,
        title=row.title,
        scope_text=row.scope_text,
        share_token=row.share_token,
        period_start=row.period_start,
        period_end=row.period_end,
        baseline_date=row.baseline_date,
        baseline_rate=row.baseline_rate,
        manual_overrides=row.manual_overrides or {},
        is_published=row.is_published,
        generated_by_id=row.generated_by_id,
        generated_by_name=row.generated_by_name,
        generated_at=row.created_at,
    )


# --------------------------------------------------------------------- #
# POST /api/reports/{report_id}/unpublish — flip is_published=False
# --------------------------------------------------------------------- #


@router.post("/api/reports/{report_id}/unpublish", response_model=Report)
def unpublish_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Take the report back to draft state. The public URL becomes
    invisible again. ``manual_overrides`` content is preserved —
    re-publishing restores the same edited text.

    Side effects:
      - 删除磁盘上的 HTML 文件 —— 已发布的报告内容不应在文件系统
        残留可被任何能读 backend/data/ 的人访问到。重新 publish 会重新写。
      - ``share_token`` 保留(但不公开了);重新 publish 时会轮换。
    """
    row = db.get(ReportRow, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    if (
        user.role is AdminRole.CUSTOMER_ADMIN
        and row.customer_id != user.customer_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")

    if row.file_path:
        try:
            html_path = Path(__file__).resolve().parents[2] / row.file_path
            if html_path.exists():
                html_path.unlink()
        except OSError as exc:
            # 文件已被人手动删 / 文件夹被改名 —— 不阻断 unpublish
            # 主流程,只在 log 里记一笔供查
            logger.warning("failed to unlink %s: %s", html_path, exc)
    row.is_published = False
    db.commit()
    db.refresh(row)
    return Report(
        id=row.id,
        project_id=row.project_id,
        template_id=row.template_id,
        title=row.title,
        scope_text=row.scope_text,
        share_token=row.share_token,
        period_start=row.period_start,
        period_end=row.period_end,
        baseline_date=row.baseline_date,
        baseline_rate=row.baseline_rate,
        manual_overrides=row.manual_overrides or {},
        is_published=row.is_published,
        generated_by_id=row.generated_by_id,
        generated_by_name=row.generated_by_name,
        generated_at=row.created_at,
    )


# --------------------------------------------------------------------- #
# GET /api/reports/{report_id}/html — stream HTML
# ⚠️  功能已取消(2026-09-28):HTML 下载不在产品范围内。保留路由 + 函数
#    以避免破坏遗留 URL/客户端引用;不再维护。整套 HTML 渲染链路
#    (report_render.render_html + data/reports/*.html 文件) 都不再迭代。
# --------------------------------------------------------------------- #


@router.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(
    report_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """下载报告 HTML —— serve 磁盘上 publish 时渲染的同一份文件。

    与 ``GET /api/public/reports/{token}`` 同源:都是 publish 时用 headless
    浏览器渲染 admin 视图落盘的 ``data/reports/{project_id}/{id}.html``。
    这样下载 / 公网 / admin 三个入口看到的永远是同一份内容。

    草稿(file_path 为空)会返回 404 —— 未发布的报告没有渲染产物,请先
    在 admin 视图里点「发布」。
    """
    row = db.get(ReportRow, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    scope = _scope_clause(user)
    if scope is not None:
        if db.scalar(
            select(ReportRow.id).where(ReportRow.id == report_id, scope)
        ) is None:
            raise HTTPException(status_code=403, detail="forbidden")

    if not row.file_path:
        raise HTTPException(
            status_code=404,
            detail="report not published yet — publish it to generate HTML",
        )
    html_path = _BACKEND_ROOT / row.file_path
    if not html_path.exists():
        raise HTTPException(status_code=503, detail="html file missing")

    return HTMLResponse(
        content=html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )
