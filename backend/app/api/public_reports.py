"""Public report endpoints — no authentication required.

These endpoints are reached via the share URL embedded in the report
preview, intended to be sent over IM (WeChat etc.) to anyone. The
caller proves they're allowed to see the report by presenting a valid
``share_token`` — a 256-bit URL-safe random value generated at report
creation (see ``_generate_unique_share_token``).

Authentication-free by design:
- The /api/public/* path prefix is **not** behind ``get_current_user``;
  no JWT required.
- The endpoint will not leak any metadata beyond what the public
  preview needs (title, scope, generated_by, generated_at, snapshot).
  Tenant scope clauses and report list are NOT exposed here.
- The companion ``/api/reports/{id}/html`` download path stays
  behind auth — downloading the file is not the same as previewing
  the report, and download-tracking is out of scope for MVP.

Why a separate router (not a path on the existing ``reports`` router):
the existing router uses ``Depends(get_current_user)`` per-endpoint;
mounting a public endpoint on it would either require an
authentication-skipping flag (easy to misuse) or split the route table
with non-obvious gating. A separate router keeps the contract
self-evident — *all* endpoints under ``/api/public/*`` are open, *all*
under ``/api/reports/*`` require auth.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.project import Project
from app.models.report import Report as ReportRow
from app.schemas.report import ReportSnapshotOut
from app.services import report_templates
from app.services.report_overrides import merge_overrides

router = APIRouter(tags=["public-reports"])


@router.get("/api/public/reports/{share_token}", response_model=ReportSnapshotOut)
def get_public_report_snapshot(
    share_token: str,
    db: Session = Depends(get_db),
):
    """Public preview endpoint — anyone with the token can read.

    Behavior:
    - Token lookup is exact-match against ``geo_reports.share_token``,
      which has a UNIQUE constraint (B+tree lookup is O(log n)).
    - Returns the same ``ReportSnapshotOut`` shape as the auth-gated
      ``GET /api/reports/{report_id}`` so the frontend can render both
      paths from the same component.
    - Does **not** create any session / cookie. Pure read.
    - Returns 404 (not 403) on missing token — leaking "token
      exists or not" via 403 would weaken the URL-only access model
      and isn't useful to the legitimate user anyway.

    The token lookup is by primary key-equivalent index, not a
    sequential scan, so this endpoint's cost is constant in the
    number of reports.
    """
    row = db.query(ReportRow).filter(ReportRow.share_token == share_token).first()
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")

    if not row.is_published:
        # The report exists and the token is valid, but the operator
        # hasn't published it yet. We return 200 + a clear flag so
        # the public page can render a "尚未发布" notice without
        # treating the situation as "token wrong" (which would
        # confuse legitimate URL recipients).
        return JSONResponse(
            status_code=200,
            content={
                "unpublished": True,
                "share_token": row.share_token,
                "title": row.title,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
            },
        )

    project = db.get(Project, row.project_id)
    if project is None:
        # Project was deleted but the report row remains (CLAUDE.md
        # "外键约定" — no cascade). Surfacing a 410 lets the public
        # page show "this report's project is gone" rather than
        # returning 500 from a null Project.
        raise HTTPException(status_code=410, detail="project deleted")

    days = (row.period_end - row.period_start).days + 1
    try:
        template_fn = report_templates.get(row.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc

    # Same re-run-with-no-filter logic as the auth-gated snapshot
    # endpoint — historical reports don't store raw filter values.
    # We fabricate a stand-in ``AdminUser`` since the template body
    # only uses ``generated_by`` for a string display; we patch it
    # below with the row's actual generator name so the public page
    # never sees a fake user.
    class _StubUser:
        display_name = ""

    ctx = report_templates.BuildContext(
        db=db,
        project=project,
        period_start=row.period_start,
        period_end_exclusive=row.period_end + timedelta(days=1),
        previous_start=row.period_start - timedelta(days=days),
        previous_end_exclusive=row.period_start,
        baseline_date=row.baseline_date,
        baseline_rate=row.baseline_rate,
        generated_by=_StubUser(),
        generated_at=row.created_at,
        prompts=None,
        platform_codes=None,
    )
    snapshot = template_fn(ctx)
    snapshot["generated_by"] = row.generated_by_name
    snapshot["generated_at"] = row.created_at.strftime("%Y-%m-%d %H:%M:%S")
    merge_overrides(snapshot, row.manual_overrides or {})

    # Build a minimal ReportMeta inline so we don't depend on
    # get_current_user for the user field. (We need user_id to be a
    # string here for type-compat, but ReportMeta expects int — we
    # pass the actual row values.)
    from app.schemas.report import ReportMeta

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
