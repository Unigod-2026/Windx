"""Dashboard aggregate API.

Task 15 / Section §4.1 of the schedule-management spec. The dashboard is the
default landing page after admin login, so every authenticated user can hit
it; a ``customer_admin`` is automatically scoped to their own customer by the
same rule used elsewhere (``user.customer_id`` filter).

Aggregate shape:
- ``today_*`` counters from ``ScheduleRun`` rows with ``triggered_at`` in
  ``[today_midnight, now]`` (Asia/Shanghai).
- ``enabled_projects`` counts ``Project`` rows with ``schedule_enabled=true``.
- ``status_distribution`` groups the same today slice by ``RunStatus``.
- ``recent_runs`` returns the last 10 runs (any date), joined with project
  for the name + state needed by the timeline row.
- ``upcoming`` recomputes the next ``next_run_at`` for each enabled project
  via ``next_run_at``; the SQL-side column was deliberately dropped from the
  v2 schema, so we compute on the fly for the top 10.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.common import now_local
from app.models.customer import AdminUser, Customer
from app.models.enums import AdminRole, RunStatus
from app.models.project import Project, ProjectPlatform, ProjectPrompt
from app.models.schedule import ScheduleRun
from app.services.schedule_time import next_run_at

router = APIRouter(tags=["dashboard"])


# --------------------------------------------------------------------------
# Response schemas
# --------------------------------------------------------------------------


class DashboardRunItem(BaseModel):
    id: int
    project_id: int
    project_name: str
    project_status: str
    status: str
    triggered_at: datetime
    finished_at: datetime | None
    duration_seconds: int | None
    platforms: list[str]
    prompt_count: int


class DashboardUpcomingItem(BaseModel):
    project_id: int
    project_name: str
    customer_id: int
    customer_name: str
    next_run_at: datetime
    platforms: list[str]


class DashboardOut(BaseModel):
    today_runs: int
    today_success: int
    today_failed: int
    enabled_projects: int
    status_distribution: dict[str, int]
    recent_runs: list[DashboardRunItem]
    upcoming: list[DashboardUpcomingItem]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _customer_filter(user: AdminUser):
    """Return a SQLAlchemy clause to AND into the query, or ``None``."""
    if user.role is AdminRole.CUSTOMER_ADMIN:
        return Project.customer_id == user.customer_id
    return None


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------


@router.get("/api/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    now = now_local()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    scope = _customer_filter(user)

    # ---- today_* counts ---------------------------------------------------
    today_stmt = (
        select(ScheduleRun)
        .join(Project, ScheduleRun.project_id == Project.id)
        .where(ScheduleRun.triggered_at >= today_start)
    )
    if scope is not None:
        today_stmt = today_stmt.where(scope)

    today_runs = db.scalar(
        select(func.count()).select_from(today_stmt.subquery())
    ) or 0

    today_success = db.scalar(
        select(func.count()).select_from(
            today_stmt.where(ScheduleRun.status == RunStatus.SUCCESS).subquery()
        )
    ) or 0

    today_failed = db.scalar(
        select(func.count()).select_from(
            today_stmt.where(ScheduleRun.status == RunStatus.FAILED).subquery()
        )
    ) or 0

    # ---- status distribution (today only) --------------------------------
    dist_stmt = (
        select(ScheduleRun.status, func.count())
        .join(Project, ScheduleRun.project_id == Project.id)
        .where(ScheduleRun.triggered_at >= today_start)
        .group_by(ScheduleRun.status)
    )
    if scope is not None:
        dist_stmt = dist_stmt.where(scope)
    counts: dict[RunStatus, int] = {s: 0 for s in RunStatus}
    for status, count in db.execute(dist_stmt).all():
        counts[status] = count
    status_distribution = {s.value: counts[s] for s in RunStatus}

    # ---- enabled projects -------------------------------------------------
    enabled_stmt = select(func.count()).select_from(Project).where(
        Project.schedule_enabled.is_(True)
    )
    if scope is not None:
        enabled_stmt = enabled_stmt.where(scope)
    enabled_projects = db.scalar(enabled_stmt) or 0

    # ---- recent runs (last 10, any date) ---------------------------------
    recent_stmt = (
        select(ScheduleRun, Project.name, Project.status)
        .join(Project, ScheduleRun.project_id == Project.id)
        .order_by(ScheduleRun.id.desc())
        .limit(10)
    )
    if scope is not None:
        recent_stmt = recent_stmt.where(scope)
    recent_rows = db.execute(recent_stmt).all()

    # Collect platforms/prompt counts for the projects in the recent list.
    recent_project_ids = {run.project_id for run, *_ in recent_rows}
    platforms_by_project: dict[int, list[str]] = {pid: [] for pid in recent_project_ids}
    prompts_by_project: dict[int, int] = {pid: 0 for pid in recent_project_ids}
    if recent_project_ids:
        for pf in db.execute(
            select(ProjectPlatform.project_id, ProjectPlatform.platform)
            .where(ProjectPlatform.project_id.in_(recent_project_ids))
            .order_by(ProjectPlatform.project_id, ProjectPlatform.sort)
        ).all():
            platforms_by_project[pf.project_id].append(pf.platform)
        for pr in db.execute(
            select(ProjectPrompt.project_id, func.count())
            .where(ProjectPrompt.project_id.in_(recent_project_ids))
            .group_by(ProjectPrompt.project_id)
        ).all():
            prompts_by_project[pr.project_id] = pr[1]

    recent_runs = [
        DashboardRunItem(
            id=run.id,
            project_id=run.project_id,
            project_name=project_name,
            project_status=project_status.value,
            status=run.status.value,
            triggered_at=run.triggered_at,
            finished_at=run.finished_at,
            duration_seconds=(
                int((run.finished_at - run.started_at).total_seconds())
                if run.finished_at and run.started_at
                else None
            ),
            platforms=platforms_by_project.get(run.project_id, []),
            prompt_count=prompts_by_project.get(run.project_id, 0),
        )
        for run, project_name, project_status in recent_rows
    ]

    # ---- upcoming (next 10 by next_run_at) -------------------------------
    upcoming_projects_stmt = select(Project).where(
        Project.schedule_enabled.is_(True)
    )
    if scope is not None:
        upcoming_projects_stmt = upcoming_projects_stmt.where(scope)
    upcoming_projects = db.scalars(upcoming_projects_stmt).all()

    customers_by_id: dict[int, Customer] = {}
    upcoming_project_ids = {p.id for p in upcoming_projects}
    upcoming_platforms: dict[int, list[str]] = {
        pid: [] for pid in upcoming_project_ids
    }
    if upcoming_project_ids:
        customers_by_id = {
            c.id: c
            for c in db.scalars(
                select(Customer).where(
                    Customer.id.in_({p.customer_id for p in upcoming_projects})
                )
            ).all()
        }
        for pf in db.execute(
            select(ProjectPlatform.project_id, ProjectPlatform.platform)
            .where(ProjectPlatform.project_id.in_(upcoming_project_ids))
            .order_by(ProjectPlatform.project_id, ProjectPlatform.sort)
        ).all():
            upcoming_platforms[pf.project_id].append(pf.platform)

    upcoming_items: list[DashboardUpcomingItem] = []
    for p in upcoming_projects:
        nra = next_run_at(p.schedule_slots, now=now)
        if nra is None:
            continue
        customer = customers_by_id.get(p.customer_id)
        upcoming_items.append(
            DashboardUpcomingItem(
                project_id=p.id,
                project_name=p.name,
                customer_id=p.customer_id,
                customer_name=customer.name if customer else "",
                next_run_at=nra,
                platforms=upcoming_platforms.get(p.id, []),
            )
        )
    upcoming_items.sort(key=lambda x: x.next_run_at)
    upcoming = upcoming_items[:10]

    return DashboardOut(
        today_runs=today_runs,
        today_success=today_success,
        today_failed=today_failed,
        enabled_projects=enabled_projects,
        status_distribution=status_distribution,
        recent_runs=recent_runs,
        upcoming=upcoming,
    )
