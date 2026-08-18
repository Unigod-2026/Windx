"""Project CRUD, 4-tab config, embedded schedule, runs and task list APIs.

v2 (plan Appendix A.2) folded the old ``/api/schedules`` surface into the
project: there is no standalone schedule entity, so every schedule endpoint
is namespaced under ``/api/projects/{id}/schedule``. ``ScheduleRun`` rows
are keyed by ``project_id``.

Route-order note: ``/api/projects/runs/{run_id}`` is declared before
``/api/projects/{project_id}`` so the literal ``runs`` segment is not
swallowed by the int path converter.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import Integer, and_, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_super_admin, get_current_user
from app.models.common import now_local
from app.models.customer import AdminUser, Customer
from app.models.enums import AdminRole, ProjectStatus, RunStatus, RunTrigger
from app.models.project import (
    BrandMention,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.schedule import ScheduleRun
from app.models.task import Subtask, Task
from app.services.scheduler import run_project_async
from app.services.scheduler_runtime import reload_jobs
from app.schemas.project import (
    BrandMentionListOut,
    BrandMentionOut,
    BrandMentionSummary,
    CitationAnalysisOut,
    CitationOut,
    CompetitorAnalysisOut,
    CompetitorBrandStat,
    CompetitorIn,
    CompetitorKpi,
    CompetitorListOut,
    CompetitorOut,
    CompetitorTrendBlock,
    CompetitorTrendSeries,
    ConcernTag,
    PromptAnswerListOut,
    PromptAnswerOut,
    PromptAnswerDetailOut,
    KeywordsUpdate,
    ModelDimension,
    PlatformsUpdate,
    ProjectCreate,
    ProjectDetailOut,
    ProjectListOut,
    ProjectOut,
    ProjectOverviewOut,
    ProjectTaskListOut,
    ProjectTaskOut,
    ProjectUpdate,
    OverviewKpi,
    PlatformRank,
    PromptOut,
    PromptsUpdate,
    QuestionProductAnalyticsOut,
    QuestionCompetitorAnalyticsOut,
    QuestionCompetitorOut,
    QuestionPlatformStat,
    QuestionPrevStat,
    QuestionStableItem,
    QuestionStatusChangesOut,
    QuestionSummaryItem,
    QuestionSummaryOut,
    PlatformExcerpt,
    CategoryStat,
    DropEvent,
    RunSummary,
    ScheduleOut,
    ScheduleRunListOut,
    ScheduleRunOut,
    ScheduleStatusUpdate,
    ScheduleUpdate,
    SlotOut,
    SubtaskListOut,
    SubtaskOut,
    TrendSeries,
    TriggerOut,
    _CITATION_DOMAIN_RULES,
)
from app.services.schedule_time import cooldown_key, next_run_at

router = APIRouter(prefix="/api", tags=["projects"])


# Sentiment label → float. The DB column is VARCHAR(16) holding the API label
# ("positive" / "neutral" / "negative") since the API-pass refactor (migration
# 20260818_0001). Dashboard KPIs still want a numeric average for the color
# buckets (>=0.7 green / >=0.5 orange / else red), so we translate on the fly.
_SENTIMENT_TO_FLOAT: dict[str, float] = {
    "positive": 1.0,
    "neutral": 0.5,
    "negative": 0.0,
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _paginate(page: int, size: int) -> tuple[int, int]:
    return max(1, page), min(100, max(1, size))


def _get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    return p


def _assert_customer_access(user: AdminUser, project: Project) -> None:
    """Block ``customer_admin`` from peeking at projects outside their tenant."""
    if user.role is AdminRole.CUSTOMER_ADMIN and project.customer_id != user.customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="project does not belong to your customer",
        )


def _resolve_window_inline(
    days: int | None,
    start: date | None,
    end: date | None,
) -> tuple[datetime, datetime]:
    """共用窗口解析:`start`/`end` 优先,否则取最近 N 天(默认 15)。

    返回 ``[win_start_dt, win_end_dt]``,起闭是 ``[00:00, 23:59:59]`` —
    与 ``list_brand_mentions`` 及三个 v2 analytics 端点保持一致;便于
    ``BrandMention.created_at``/``Subtask.updated_at`` 用 ``>=`` / ``<`` 跨端点
    统一比对。

    raises:
      400: ``start`` / ``end`` 必须同进同出,且 end ≥ start;``days`` 落在
           ``[1, 90]``。
    """
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=window_days - 1)
        win_end = today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    return win_start_dt, win_end_dt


def _slots_out(p: Project) -> list[SlotOut]:
    return [
        SlotOut(slot_index=i, hour=s["hour"], minute=s["minute"])
        for i, s in enumerate(p.schedule_slots, start=1)
    ]


def _next_run(p: Project):
    """Only an enabled schedule on an active project has a next run."""
    if not p.schedule_enabled or p.status is not ProjectStatus.ACTIVE:
        return None
    return next_run_at(p.schedule_slots)


def _to_out(p: Project, prompts_count: int | None = None) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.slots = _slots_out(p)
    out.next_run_at = _next_run(p)
    out.prompts_count = prompts_count if prompts_count is not None else 0
    return out


def _prompts_count_for(db: Session, project_ids: list[int]) -> dict[int, int]:
    """One GROUP BY query instead of N+1 — returns {project_id: count}.

    ``project_ids`` may be empty; the caller should fall back to per-row
    computation if needed (currently nothing does).
    """
    if not project_ids:
        return {}
    rows = db.execute(
        select(ProjectPrompt.project_id, func.count(ProjectPrompt.id))
        .where(ProjectPrompt.project_id.in_(project_ids))
        .group_by(ProjectPrompt.project_id)
    ).all()
    return {pid: cnt for pid, cnt in rows}


def _to_detail(p: Project, db: Session) -> ProjectDetailOut:
    # Built from the ProjectOut payload rather than ``model_validate(p)``:
    # the detail fields share names with the ORM relationships, and
    # from_attributes would pull the raw ORM rows instead of the ordered,
    # flattened lists queried below.
    prompts = [
        PromptOut.model_validate(r)
        for r in db.scalars(
            select(ProjectPrompt)
            .where(ProjectPrompt.project_id == p.id)
            .order_by(ProjectPrompt.sort)
        )
    ]
    return ProjectDetailOut(
        **_to_out(p, prompts_count=len(prompts)).model_dump(),
        prompts=prompts,
        keywords=[
            r.keyword
            for r in db.scalars(
                select(ProjectKeyword)
                .where(ProjectKeyword.project_id == p.id)
                .order_by(ProjectKeyword.sort)
            )
        ],
        platforms=[
            {
                "id": r.id,
                "platform": r.platform,
                "mode": r.mode,
                "delivery_mode": r.delivery_mode,
                "thinking_mode": r.thinking_mode,
                "screenshot": r.screenshot,
            }
            for r in db.scalars(
                select(ProjectPlatform)
                .where(ProjectPlatform.project_id == p.id)
                .order_by(ProjectPlatform.sort)
            )
        ],
    )


def _apply_slots(p: Project, slots: list, enabled: bool) -> None:
    """Write slots + enabled onto the project, rejecting enable-without-slots.

    Pydantic already caps the list at 2 and range-checks hour/minute; the
    only rule left is that an enabled schedule must have somewhere to fire.
    """
    if enabled and not slots:
        raise HTTPException(400, "cannot enable a schedule with no slots")
    p.set_schedule_slots([s.model_dump() for s in slots])
    p.schedule_enabled = enabled


# --------------------------------------------------------------------------
# Project CRUD
# --------------------------------------------------------------------------


@router.post("/customers/{customer_id}/projects", response_model=ProjectOut)
def create_project(
    customer_id: int,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "customer not found")
    if db.scalar(
        select(Project).where(
            Project.customer_id == customer_id, Project.code == payload.code
        )
    ):
        raise HTTPException(400, "project code exists in this customer")

    p = Project(
        customer_id=customer_id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
        status=ProjectStatus.ACTIVE,
        sentiment_enabled=payload.sentiment_enabled,
        region_strategy=payload.region_strategy,
        region_codes=payload.region_codes,
        category_taxonomy=payload.category_taxonomy,
    )
    _apply_slots(p, payload.slots, payload.schedule_enabled)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.get("/projects", response_model=ProjectListOut)
def list_projects(
    page: int = 1,
    size: int = 20,
    customer_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    page, size = _paginate(page, size)
    stmt = select(Project)
    # customer_admin is auto-scoped to their own customer; super_admin may
    # pass ?customer_id= to filter. An explicit customer_id still wins so
    # super_admin tooling can scope when it wants to.
    if user.role is AdminRole.CUSTOMER_ADMIN:
        stmt = stmt.where(Project.customer_id == user.customer_id)
    elif customer_id is not None:
        stmt = stmt.where(Project.customer_id == customer_id)
    if status:
        stmt = stmt.where(Project.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Project.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    counts = _prompts_count_for(db, [p.id for p in items])
    return ProjectListOut(
        items=[_to_out(p, prompts_count=counts.get(p.id, 0)) for p in items],
        total=total,
        page=page,
        size=size,
    )


# Declared before /projects/{project_id} so "runs" isn't parsed as an id.
@router.get("/projects/runs/{run_id}", response_model=ScheduleRunOut)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    r = db.get(ScheduleRun, run_id)
    if not r:
        raise HTTPException(404, "run not found")
    counts_map = _subtask_counts_for_runs(db, [run_id])
    return _run_with_counts(r, counts_map.get(run_id, {}))


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    return _to_detail(project, db)


def _apply_category_taxonomy_change(
    db: Session,
    project_id: int,
    old_taxonomy: list[str] | None,
    new_taxonomy: list[str] | None,
    renames: dict[str, str] | None,
) -> None:
    """Reconcile ``geo_project_prompts.category`` against a new taxonomy.

    Called from ``PUT /projects/{id}`` when ``category_taxonomy`` is in the
    payload. Runs in this order:

    1. Apply ``renames``: any prompt with category=old gets category=new.
       This preserves references for labels the admin renamed in-place.
    2. Compute the set of *removed* labels (in old_taxonomy but not in
       new_taxonomy and not consumed by a rename). Set matching prompts'
       category to NULL.
    3. Validate the new taxonomy — no empty strings, no duplicates.
    """
    if new_taxonomy is not None:
        if any(not (name and name.strip()) for name in new_taxonomy):
            raise HTTPException(400, "category names must be non-empty")
        if len(set(new_taxonomy)) != len(new_taxonomy):
            raise HTTPException(400, "category names must be unique")
    renames = renames or {}
    for old_name, new_name in renames.items():
        if not old_name or not new_name:
            raise HTTPException(400, "rename mapping requires non-empty names")
        if old_name == new_name:
            continue
        db.execute(
            update(ProjectPrompt)
            .where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.category == old_name,
            )
            .values(category=new_name)
        )

    if new_taxonomy is not None and old_taxonomy is not None:
        renamed_to = set(renames.values())
        removed = [
            name
            for name in old_taxonomy
            if name not in new_taxonomy and name not in renamed_to
        ]
        if removed:
            db.execute(
                update(ProjectPrompt)
                .where(
                    ProjectPrompt.project_id == project_id,
                    ProjectPrompt.category.in_(removed),
                )
                .values(category=None)
            )


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = _get_project(db, project_id)
    data = payload.model_dump(exclude_unset=True)
    renames = data.pop("category_renames", None)
    old_taxonomy = p.category_taxonomy
    for k, v in data.items():
        setattr(p, k, v)
    if "category_taxonomy" in data:
        _apply_category_taxonomy_change(
            db, project_id, old_taxonomy, p.category_taxonomy, renames
        )
    db.commit()
    db.refresh(p)
    # status ↔ schedule_active: when the project flips active/disabled the
    # APScheduler job set must mirror the change immediately, not on next
    # server boot.
    if "status" in data:
        if (scheduler := getattr(request.app.state, "scheduler", None)):
            reload_jobs(scheduler)
    return _to_out(p, prompts_count=_prompts_count_for(db, [p.id]).get(p.id, 0))


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Soft delete (spec §API). Disabling also stops the schedule, per the
    spec's boundary rule "项目被软删除时调度应停用" — leaving
    ``schedule_enabled`` set would keep the APScheduler job alive."""
    p = _get_project(db, project_id)
    p.status = ProjectStatus.DISABLED
    p.schedule_enabled = False
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# 4-tab config (whole-array replace)
# --------------------------------------------------------------------------


def _replace(db: Session, model, project_id: int, rows: list[dict]) -> None:
    db.query(model).filter(model.project_id == project_id).delete()
    for i, row in enumerate(rows):
        db.add(model(project_id=project_id, sort=i, **row))
    db.commit()


@router.put("/projects/{project_id}/prompts")
def put_prompts(
    project_id: int,
    payload: PromptsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    project = _get_project(db, project_id)
    taxonomy = project.category_taxonomy
    # Categories not in the project's taxonomy are silently dropped to NULL.
    # This protects the admin from 400'ing an entire save because a few
    # prompts still carry labels from a previous taxonomy (the legacy data
    # shipped before this column existed). The frontend's "为问题分配分类"
    # card already surfaces those rows with their legacy value visible, so
    # the admin can choose to re-assign them in the next round of edits.
    rows: list[dict] = []
    dropped: list[str] = []
    if taxonomy:
        allowed = set(taxonomy) | {None}
        for item in payload.prompts:
            cat = item.category
            if cat not in allowed:
                dropped.append(cat)
                cat = None
            rows.append(
                {"prompt": item.prompt, "category": cat, "status": item.status}
            )
    else:
        rows = [
            {"prompt": item.prompt, "category": item.category, "status": item.status}
            for item in payload.prompts
        ]
    _replace(db, ProjectPrompt, project_id, rows)
    return {"ok": True, "count": len(rows), "dropped_categories": dropped}


@router.put("/projects/{project_id}/keywords")
def put_keywords(
    project_id: int,
    payload: KeywordsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    _replace(db, ProjectKeyword, project_id, [{"keyword": k} for k in payload.keywords])
    return {"ok": True, "count": len(payload.keywords)}


@router.put("/projects/{project_id}/platforms")
def put_platforms(
    project_id: int,
    payload: PlatformsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    _replace(db, ProjectPlatform, project_id, [p.model_dump() for p in payload.platforms])
    return {"ok": True, "count": len(payload.platforms)}


# --------------------------------------------------------------------------
# Embedded schedule
# --------------------------------------------------------------------------


def _schedule_out(p: Project, db: Session) -> ScheduleOut:
    last = db.scalars(
        select(ScheduleRun)
        .where(ScheduleRun.project_id == p.id)
        .order_by(ScheduleRun.id.desc())
        .limit(1)
    ).first()
    return ScheduleOut(
        project_id=p.id,
        schedule_enabled=p.schedule_enabled,
        slots=_slots_out(p),
        next_run_at=_next_run(p),
        last_run=RunSummary.model_validate(last) if last else None,
    )


@router.get("/projects/{project_id}/schedule", response_model=ScheduleOut)
def get_schedule(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    return _schedule_out(project, db)


@router.put("/projects/{project_id}/schedule", response_model=ScheduleOut)
def put_schedule(
    project_id: int,
    payload: ScheduleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = _get_project(db, project_id)
    _apply_slots(p, payload.slots, payload.schedule_enabled)
    db.commit()
    db.refresh(p)
    # Slot or schedule_enabled changed → APScheduler's in-memory job set is
    # stale (jobs were registered once at lifespan startup). Without this
    # reload, new slots won't fire until the next server restart.
    if (scheduler := getattr(request.app.state, "scheduler", None)):
        reload_jobs(scheduler)
    return _schedule_out(p, db)


@router.delete("/projects/{project_id}/schedule", response_model=ScheduleOut)
def delete_schedule(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Reset to the no-schedule state; run history is kept."""
    p = _get_project(db, project_id)
    p.set_schedule_slots([])
    p.schedule_enabled = False
    db.commit()
    db.refresh(p)
    if (scheduler := getattr(request.app.state, "scheduler", None)):
        reload_jobs(scheduler)
    return _schedule_out(p, db)


@router.put("/projects/{project_id}/schedule/status", response_model=ScheduleOut)
def put_schedule_status(
    project_id: int,
    payload: ScheduleStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Toggle only ``schedule_enabled``; slots are preserved across a disable."""
    p = _get_project(db, project_id)
    enabled = payload.status == "enabled"
    if enabled and not p.schedule_slots:
        raise HTTPException(400, "请先在「编辑监控项目」里配置至少一个调度时间槽,再启用调度")
    p.schedule_enabled = enabled
    db.commit()
    db.refresh(p)
    if (scheduler := getattr(request.app.state, "scheduler", None)):
        reload_jobs(scheduler)
    return _schedule_out(p, db)


@router.post("/projects/{project_id}/schedule/trigger", response_model=TriggerOut)
def trigger_schedule(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Manually queue one run (slot_index 0) and kick off the submission.

    The ``cooldown_key`` unique index is what enforces the 5-minute window —
    we let the INSERT fail and translate the conflict into ``skipped``
    rather than pre-checking, so concurrent triggers can't both pass.
    """
    p = _get_project(db, project_id)
    if not db.scalar(
        select(func.count())
        .select_from(ProjectPrompt)
        .where(ProjectPrompt.project_id == project_id)
    ):
        raise HTTPException(400, "project has no prompts configured")

    now = now_local()
    key = cooldown_key(project_id, 0, now)
    run = ScheduleRun(
        project_id=project_id,
        slot_index=0,
        trigger_type=RunTrigger.MANUAL,
        triggered_at=now,
        status=RunStatus.QUEUED,
        cooldown_key=key,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ScheduleRun).where(ScheduleRun.cooldown_key == key))
        if existing is None:
            raise HTTPException(500, "cooldown conflict")
        return TriggerOut(run_id=existing.id, status="skipped")
    db.refresh(run)
    # Fire-and-forget: the remote submit can take minutes, so we hand it to
    # a background task and let the API return immediately. ``run_project_async``
    # updates ``schedule_runs.status`` and inserts the ``geo_tasks`` row when
    # the remote call resolves.
    background_tasks.add_task(
        run_project_async, project_id, 0, RunTrigger.MANUAL, run_id=run.id
    )
    return TriggerOut(run_id=run.id, status="queued")


# --------------------------------------------------------------------------
# Runs + tasks
# --------------------------------------------------------------------------


def _subtask_counts_for_runs(
    db: Session, run_ids: list[int]
) -> dict[int, dict[str, int]]:
    """Aggregate per-run subtask status counts.

    Joins ``Task`` (filtered by ``schedule_run_id``) to its ``Subtask`` rows and
    bins them by status. Runs that have no Task yet (e.g. a queued manual
    trigger that hasn't submitted) are absent from the result; callers fall
    back to zero counts in that case.
    """
    if not run_ids:
        return {}
    stmt = (
        select(
            Task.schedule_run_id,
            Subtask.status,
            func.count(Subtask.subtask_id),
        )
        .join(Subtask, Subtask.task_id == Task.task_id)
        .where(Task.schedule_run_id.in_(run_ids))
        .group_by(Task.schedule_run_id, Subtask.status)
    )
    out: dict[int, dict[str, int]] = {}
    for run_id, status, n in db.execute(stmt).all():
        bucket = out.setdefault(
            run_id,
            {"success_count": 0, "failed_count": 0, "partial_count": 0, "total_count": 0},
        )
        bucket["total_count"] += n
        if status in ("success", "completed"):
            bucket["success_count"] += n
        elif status == "failed":
            bucket["failed_count"] += n
        elif status == "partial_completed":
            bucket["partial_count"] += n
    return out


def _run_with_counts(r: ScheduleRun, counts: dict[str, int]) -> ScheduleRunOut:
    payload = {
        "id": r.id,
        "project_id": r.project_id,
        "slot_index": r.slot_index,
        "trigger_type": r.trigger_type,
        "status": r.status,
        "triggered_at": r.triggered_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "task_id": r.task_id,
        "error_message": r.error_message,
        **counts,
    }
    return ScheduleRunOut.model_validate(payload)


@router.get("/projects/{project_id}/runs", response_model=ScheduleRunListOut)
def list_runs(
    project_id: int,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    page, size = _paginate(page, size)
    stmt = select(ScheduleRun).where(ScheduleRun.project_id == project_id)
    if status:
        stmt = stmt.where(ScheduleRun.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(ScheduleRun.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    counts_map = _subtask_counts_for_runs(db, [r.id for r in items])
    return ScheduleRunListOut(
        items=[_run_with_counts(r, counts_map.get(r.id, {})) for r in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/projects/{project_id}/tasks", response_model=ProjectTaskListOut)
def list_project_tasks(
    project_id: int,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    page, size = _paginate(page, size)
    stmt = select(Task).where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Task.task_id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ProjectTaskListOut(
        items=[ProjectTaskOut.model_validate(t) for t in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/projects/{project_id}/tasks/{task_id}/subtasks", response_model=SubtaskListOut)
def list_task_subtasks(
    project_id: int,
    task_id: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Return the Subtask rows attached to a single ``geo_tasks`` row.

    Used by the per-project task-detail modal so an operator can see
    which sub-task failed and why without leaving the project list.
    The parent Task is scoped by ``project_id`` so callers can't peek
    at tasks belonging to a different project by guessing IDs.
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="task not found")
    rows = db.scalars(
        select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.subtask_id)
    ).all()
    return SubtaskListOut(
        items=[SubtaskOut.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get(
    "/projects/{project_id}/prompts/{prompt_id}/answers",
    response_model=PromptAnswerListOut,
)
def list_prompt_answers(
    project_id: int,
    prompt_id: int,
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    platform: str | None = None,
    preview_chars: int = 200,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Return every ``geo_subtasks`` row that was generated for this prompt.

    Drives the 问题提及分析 → 模型对比 → 查看原文 modal: when an operator
    wants to read what every AI actually said, we list all subtasks whose
    ``prompt`` text matches the project's ``ProjectPrompt.prompt`` (the
    Subtask table does not store ``prompt_id``; it stores the verbatim text
    that the user submitted). Window filtering rides on the parent task's
    ``created_local_at`` — same semantics as the overview endpoint — so
    ``start``/``end`` win over ``days``.

    ``platform`` narrows the result to a single AI model — used by the
    查看原文 modal so clicking a row in the 模型对比 table only shows
    that model's answers, not the union across all platforms.

    The list intentionally omits the heavy fields (full ``answer_content``
    text, ``page_screenshot`` base64, all structured-payload JSON). Each
    row carries a truncated ``answer_content`` slice of ``preview_chars``
    plus the original ``answer_length`` and a ``truncated`` flag, so the
    modal can render the per-row preview card and only request the full
    payload (via :func:`get_subtask_detail`) when the operator clicks
    展开全部. That keeps the list response small regardless of how long
    each AI's answer is — a 60-row month window with megabyte-scale
    answers still lands well under 100 KB.
    """
    from datetime import timedelta

    from app.models.common import now_local

    if preview_chars < 50 or preview_chars > 2000:
        raise HTTPException(400, "preview_chars must be between 50 and 2000")

    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    prompt = db.get(ProjectPrompt, prompt_id)
    if prompt is None or prompt.project_id != project_id:
        raise HTTPException(404, "prompt not found in this project")
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start, win_end = today - timedelta(days=window_days - 1), today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    base_stmt = (
        select(
            Subtask.subtask_id,
            Subtask.task_id,
            Subtask.platform,
            Subtask.mode,
            Subtask.status,
            Subtask.answer_content,
            Subtask.error_message,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Subtask.prompt == prompt.prompt,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    if platform is not None:
        base_stmt = base_stmt.where(Subtask.platform == platform)
    # Sort key + id first so MySQL can sort on a tiny row, then re-fetch
    # the rest by id. Selecting every JSON / page_screenshot /
    # answer_content straight into the sort buffer blew past the server's
    # ``sort_buffer_size`` (256KB default) on a single prompt that has a
    # few long answers in the window.
    sort_rows = db.execute(
        base_stmt.with_only_columns(
            Subtask.subtask_id,
            Subtask.task_id,
            Task.created_local_at,
        ).order_by(Task.created_local_at.desc(), Subtask.subtask_id)
    ).all()
    if not sort_rows:
        return PromptAnswerListOut(items=[], total=0)
    sub_ids = [r.subtask_id for r in sort_rows]
    created_at_by_sub = {r.subtask_id: r.created_local_at for r in sort_rows}
    # Second pass: only the columns the list actually needs. We pull the
    # full ``answer_content`` here so we can slice it in Python; the JSON
    # columns and ``page_screenshot`` are deliberately left for the detail
    # endpoint.
    light_rows = db.execute(
        select(
            Subtask.subtask_id,
            Subtask.task_id,
            Subtask.platform,
            Subtask.mode,
            Subtask.status,
            Subtask.answer_content,
            Subtask.error_message,
        ).where(Subtask.subtask_id.in_(sub_ids))
    ).all()
    light_by_sub = {r.subtask_id: r for r in light_rows}
    items = [
        _build_preview_answer(
            sid=sid,
            row=light_by_sub[sid],
            created_local_at=created_at_by_sub[sid],
            preview_chars=preview_chars,
        )
        for sid in sub_ids
    ]
    return PromptAnswerListOut(items=items, total=len(items))


def _build_preview_answer(
    *,
    sid: str,
    row,
    created_local_at,
    preview_chars: int,
) -> "PromptAnswerOut":
    """Slice ``answer_content`` to ``preview_chars`` and emit a list-row
    schema. We keep the original length in ``answer_length`` so the UI
    can render the 展开全部 (N 字) affordance without a second fetch.
    """
    full_text = row.answer_content or ""
    length = len(full_text)
    if length <= preview_chars:
        preview = full_text
        truncated = False
    else:
        preview = full_text[:preview_chars]
        truncated = True
    return PromptAnswerOut(
        subtask_id=sid,
        task_id=row.task_id,
        platform=row.platform,
        mode=row.mode,
        status=row.status,
        answer_content=preview,
        answer_length=length,
        truncated=truncated,
        error_message=row.error_message,
        created_local_at=created_local_at,
    )


@router.get(
    "/subtasks/{subtask_id}",
    response_model=PromptAnswerDetailOut,
)
def get_subtask_detail(
    subtask_id: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Single-subtask full payload, fetched on demand from the
    查看原文 → 展开全部 modal. The list endpoint deliberately trims the
    answer text and drops the structured payload; this route restores
    them in one round-trip. Tenant scoping rides on the subtask's parent
    Task → Project chain so a customer_admin can't peek at other
    customers' answers by guessing subtask IDs.
    """
    sub = db.get(Subtask, subtask_id)
    if sub is None:
        raise HTTPException(404, "subtask not found")
    task = db.get(Task, sub.task_id)
    if task is None:
        raise HTTPException(404, "parent task not found")
    _assert_customer_access(user, task.project)
    full_text = sub.answer_content or ""
    return PromptAnswerDetailOut(
        subtask_id=sub.subtask_id,
        task_id=sub.task_id,
        platform=sub.platform,
        mode=sub.mode,
        status=sub.status,
        answer_content=full_text,
        answer_length=len(full_text),
        truncated=False,
        page_screenshot=sub.page_screenshot,
        error_message=sub.error_message,
        created_local_at=task.created_local_at,
        reference_list=sub.reference_list_json,
        citation_list=sub.citation_list_json,
        reasoning_process=sub.reasoning_process_json,
        media_content=sub.media_content_json,
        recommended_questions=sub.recommended_questions_json,
    )


# --------------------------------------------------------------------------
# Competitors (user-defined seed list per project)
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/competitors", response_model=CompetitorListOut)
def list_competitors(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    items = db.scalars(
        select(ProjectCompetitor)
        .where(ProjectCompetitor.project_id == project_id)
        .order_by(ProjectCompetitor.sort, ProjectCompetitor.id)
    ).all()
    return CompetitorListOut(
        items=[CompetitorOut.model_validate(c) for c in items],
        total=len(items),
    )


@router.post(
    "/projects/{project_id}/competitors",
    response_model=CompetitorOut,
    status_code=201,
)
def create_competitor(
    project_id: int,
    payload: CompetitorIn,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    next_sort = (
        db.scalar(
            select(func.coalesce(func.max(ProjectCompetitor.sort), -1)).where(
                ProjectCompetitor.project_id == project_id
            )
        )
        or -1
    ) + 1
    c = ProjectCompetitor(
        project_id=project_id,
        name=payload.name.strip(),
        note=payload.note,
        aliases=payload.aliases,
        origin=payload.origin,
        status=payload.status,
        sort=next_sort,
    )
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        # ``uq_project_competitors_project_name`` — name already in this project.
        db.rollback()
        raise HTTPException(400, "competitor name already exists in this project")
    db.refresh(c)
    return CompetitorOut.model_validate(c)


@router.put(
    "/projects/{project_id}/competitors/{competitor_id}",
    response_model=CompetitorOut,
)
def update_competitor(
    project_id: int,
    competitor_id: int,
    payload: CompetitorIn,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(ProjectCompetitor, competitor_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "competitor not found")
    c.name = payload.name.strip()
    c.note = payload.note
    c.aliases = payload.aliases
    c.origin = payload.origin
    c.status = payload.status
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "competitor name already exists in this project")
    db.refresh(c)
    return CompetitorOut.model_validate(c)


@router.delete("/projects/{project_id}/competitors/{competitor_id}")
def delete_competitor(
    project_id: int,
    competitor_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(ProjectCompetitor, competitor_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "competitor not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Brand mentions (drives overview / per-question / per-competitor pages)
# --------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/brand-mentions",
    response_model=BrandMentionListOut,
)
def list_brand_mentions(
    project_id: int,
    page: int = 1,
    size: int = 50,
    is_self: bool | None = None,
    brand_canonical: str | None = None,
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """List extraction rows for one project, newest first.

    ``is_self=true`` filters to the monitored brand (default for the
    overview tab). ``brand_canonical`` narrows to one specific brand
    (default for the competitor-analysis tab).

    Window filtering rides on ``BrandMention.created_at`` — same as
    :func:`list_prompt_answers`, ``start``/``end`` win over ``days`` and
    are inclusive on both ends. Drives the 问题提及分析 per-question
    delta row (current window vs the immediately preceding window of
    the same length).
    """
    page, size = _paginate(page, size)
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=window_days - 1)
        win_end = today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    stmt = select(BrandMention).where(
        BrandMention.project_id == project_id,
        BrandMention.created_at >= win_start_dt,
        BrandMention.created_at <= win_end_dt,
    )
    if is_self is not None:
        stmt = stmt.where(BrandMention.is_self == is_self)
    if brand_canonical:
        stmt = stmt.where(BrandMention.brand_canonical == brand_canonical)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(BrandMention.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return BrandMentionListOut(
        items=[BrandMentionOut.model_validate(m) for m in items],
        total=total,
    )


def _compute_question_summary(
    db: Session,
    project: Project,
    *,
    start: datetime,
    end: datetime,
) -> QuestionSummaryOut:
    """按项目当前窗口聚合每个 prompt 的 KPI + 项目级 category summary。

    单次 SELECT 取 per-(prompt, category, status, platform, rank) 行,
    在 Python 中派生 per-prompt 和 per-category 两套聚合,严格遵守 spec
    §4.1「从同一统计结果汇总,不再额外扫描 geo_brand_mentions」。
    SQL 预算 = 1 条核心 SELECT。
    """
    rows = db.execute(
        select(
            ProjectPrompt.id,
            BrandMention.prompt,
            ProjectPrompt.category,
            ProjectPrompt.status,
            BrandMention.platform,
            BrandMention.rank_position,
        )
        .join(ProjectPrompt, ProjectPrompt.prompt == BrandMention.prompt)
        .where(
            BrandMention.project_id == project.id,
            ProjectPrompt.project_id == project.id,
            BrandMention.is_self.is_(True),
            BrandMention.created_at >= start,
            BrandMention.created_at < end,
        )
    ).all()

    per_prompt: dict[int, dict] = {}
    cat_prompts: dict[str | None, set[int]] = defaultdict(set)
    cat_matched: dict[str | None, int] = defaultdict(int)
    cat_total: dict[str | None, int] = defaultdict(int)
    cat_top1: dict[str | None, int] = defaultdict(int)
    cat_top3: dict[str | None, int] = defaultdict(int)

    for r in rows:
        bucket = per_prompt.setdefault(
            int(r.id),
            {
                "prompt": r.prompt or "",
                "category": r.category,
                "status": r.status or "active",
                "total": 0,
                "matched": 0,
                "rank_sum": 0,
                "rank_count": 0,
                "top1": 0,
                "top3": 0,
                "platforms": set(),
            },
        )
        bucket["total"] += 1
        bucket["platforms"].add(r.platform)
        if r.rank_position is not None:
            bucket["matched"] += 1
            bucket["rank_sum"] += r.rank_position
            bucket["rank_count"] += 1
            if r.rank_position == 1:
                bucket["top1"] = 1
            if r.rank_position <= 3:
                bucket["top3"] = 1

        cat = r.category
        cat_prompts[cat].add(int(r.id))
        cat_total[cat] += 1
        if r.rank_position is not None:
            cat_matched[cat] += 1
        if r.rank_position == 1:
            cat_top1[cat] += 1
        if r.rank_position is not None and r.rank_position <= 3:
            cat_top3[cat] += 1

    items: list[QuestionSummaryItem] = []
    for prompt_id, b in sorted(per_prompt.items()):
        total = b["total"]
        matched = b["matched"]
        items.append(
            QuestionSummaryItem(
                prompt_id=prompt_id,
                prompt=b["prompt"],
                category=b["category"],
                status=b["status"],
                total=total,
                matched=matched,
                mention_rate=(matched / total) if total else 0.0,
                top1_rate=b["top1"],
                top3_rate=b["top3"],
                rank_avg=(b["rank_sum"] / b["rank_count"]) if b["rank_count"] else None,
                coverage=len(b["platforms"]),
            )
        )

    category_summary: list[CategoryStat] = []
    for cat, prompt_ids in cat_prompts.items():
        total = cat_total[cat]
        category_summary.append(
            CategoryStat(
                category=cat,
                prompt_count=len(prompt_ids),
                mention_rate=(cat_matched[cat] / total) if total else 0.0,
                top1_rate=(cat_top1[cat] / total) if total else 0.0,
                top3_rate=(cat_top3[cat] / total) if total else 0.0,
            )
        )

    return QuestionSummaryOut(
        project_id=project.id,
        start=start,
        end=end,
        items=items,
        category_summary=category_summary,
    )


@router.get("/projects/{project_id}/questions/summary", response_model=QuestionSummaryOut)
def questions_summary(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
) -> QuestionSummaryOut:
    """摘要:左侧列表 + 项目级 category 汇总,只算当前窗口。

    与旧 `/questions/analytics` 的差别:不返回平台明细、prev/long_prev、
    摘录、竞品矩阵;由后续 tasks 的 product-analytics / competitor-analytics
    端点按需加载。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    win_start_dt, win_end_dt = _resolve_window_inline(days, start, end)

    return _compute_question_summary(
        db, project, start=win_start_dt, end=win_end_dt
    )


def _get_project_prompt_or_404(
    db: Session, *, project_id: int, prompt_id: int
) -> ProjectPrompt:
    prompt = db.get(ProjectPrompt, prompt_id)
    if prompt is None or prompt.project_id != project_id:
        raise HTTPException(404, "prompt not found in this project")
    return prompt


def _compute_question_product_analytics(
    db: Session,
    project: Project,
    prompt: ProjectPrompt,
    *,
    start: datetime,
    end: datetime,
) -> QuestionProductAnalyticsOut:
    """单问题产品分析:per-platform 统计 + prev + long_prev + 摘录。

    SQL 预算 = 2 条核心 SELECT:
      1) stats:扫 long_prev → end 期间的所有 (platform, created_at, rank)
         行,在 Python 中按窗口分桶(current / prev / long_prev),避免
         ``CASE WHEN`` 三遍重复 GROUP BY。
      2) excerpts:每个 platform 取窗口内最新 Subtask + 对应 rank,join
         Task 用 project_id 防御(同一 prompt 文本可能跨项目存在)。

    与 ``questions_status_changes`` / ``questions_competitor_analytics`` 的差别:
    本端点不扫全项目竞品矩阵,只看指定 prompt。
    """
    length = (end.date() - start.date()).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    long_prev_end = prev_start - timedelta(days=1)
    long_prev_start = long_prev_end - timedelta(days=length - 1)
    prev_end_dt = datetime.combine(prev_end.date(), time.max)
    prev_start_dt = datetime.combine(prev_start.date(), time.min)
    long_prev_end_dt = datetime.combine(long_prev_end.date(), time.max)
    long_prev_start_dt = datetime.combine(long_prev_start.date(), time.min)

    rows = db.execute(
        select(
            BrandMention.platform,
            BrandMention.created_at,
            BrandMention.rank_position,
        )
        .where(
            BrandMention.project_id == project.id,
            BrandMention.is_self.is_(True),
            BrandMention.prompt == prompt.prompt,
            BrandMention.created_at >= long_prev_start_dt,
            BrandMention.created_at < end,
        )
        .order_by(BrandMention.platform, BrandMention.created_at)
    ).all()

    by_window: dict[tuple[str, str], list[tuple[datetime, int | None]]] = defaultdict(list)
    for r in rows:
        if r.created_at >= start:
            bucket = "current"
        elif r.created_at >= prev_start_dt:
            bucket = "prev"
        else:
            bucket = "long_prev"
        by_window[(r.platform, bucket)].append((r.created_at, r.rank_position))

    def _agg(buckets: list[tuple[datetime, int | None]]) -> dict:
        total = len(buckets)
        ranks = [rk for _, rk in buckets if rk is not None]
        matched = len(ranks)
        top1 = sum(1 for rk in ranks if rk == 1)
        top3 = sum(1 for rk in ranks if rk <= 3)
        return {
            "total": total,
            "matched": matched,
            "top1": top1,
            "top3": top3,
            "rank_avg": (sum(ranks) / len(ranks)) if ranks else None,
        }

    def _prev_stat_for(bucket: str) -> QuestionPrevStat | None:
        # Aggregate across ALL platforms for that window so the prev
        # block is a project-level KPI, not per-platform.
        all_rows: list[tuple[datetime, int | None]] = []
        for (plat, b), items in by_window.items():
            if b == bucket:
                all_rows.extend(items)
        agg = _agg(all_rows)
        if agg["total"] == 0:
            return None
        n = agg["total"]
        return QuestionPrevStat(
            total=n,
            matched=agg["matched"],
            top1_rate=(agg["top1"] / n) if n else 0.0,
            top3_rate=(agg["top3"] / n) if n else 0.0,
            mention_rate=(agg["matched"] / n) if n else 0.0,
            rank_avg=agg["rank_avg"],
        )

    platforms_out: list[QuestionPlatformStat] = []
    platform_keys = sorted({plat for (plat, _) in by_window.keys()})
    for plat in platform_keys:
        cur = by_window.get((plat, "current"), [])
        prev = by_window.get((plat, "prev"), [])
        cur_agg = _agg(cur)
        prev_agg = _agg(prev)
        # best_rank + mention_rate + recommend derived from current only
        cur_ranks = [rk for _, rk in cur if rk is not None]
        best_rank = min(cur_ranks) if cur_ranks else None
        # The plan reuses the same QuestionPlatformStat shape as the
        # analytics endpoint (matched / total / best_rank /
        # avg_sentiment / recommend_yes). self view → is_self filter
        # already applied, brand_canonical stays None.
        platforms_out.append(
            QuestionPlatformStat(
                platform=plat,
                matched=cur_agg["matched"],
                total=cur_agg["total"],
                best_rank=best_rank,
                # Sentiment is intentionally None here: this endpoint
                # is the lazy-loaded detail view (the lightweight
                # product-analytics pane), and sentiment requires
                # joining geo_brand_mentions.sentiment_score which
                # we deliberately omit to keep the row scan narrow.
                # The summary endpoint covers sentiment for the list view.
                avg_sentiment=None,
                # No LLM-extracted recommendation bit in this scan —
                # same reason. UI falls back to "—" when null.
                recommend_yes=False,
                brand_canonical=None,
            )
        )

    prev_stat = _prev_stat_for("prev")
    long_prev_stat = _prev_stat_for("long_prev")

    # 摘录:窗口内每个 platform 取最新 subtask 的 answer_content。
    # LEFT JOIN to Task — production data always has a matching Task
    # row (Subtask.task_id is set on insert), but legacy / test
    # fixtures may not. Filtering by Task.project_id isolates this
    # project's subtasks from same-prompt-text rows of other
    # customers' projects; an outer join keeps the response populated
    # for orphan subtasks instead of dropping them silently.
    excerpt_rows = db.execute(
        select(
            Subtask.platform,
            Subtask.subtask_id,
            Subtask.answer_content,
            Subtask.updated_at,
            BrandMention.rank_position,
        )
        .outerjoin(Task, Task.task_id == Subtask.task_id)
        .outerjoin(
            BrandMention,
            and_(
                BrandMention.subtask_id == Subtask.subtask_id,
                BrandMention.is_self.is_(True),
                BrandMention.prompt == prompt.prompt,
            ),
        )
        .where(
            (Task.project_id.is_(None) | (Task.project_id == project.id)),
            Subtask.prompt == prompt.prompt,
            Subtask.updated_at >= start,
            Subtask.updated_at < end,
        )
        .order_by(Subtask.platform, Subtask.updated_at.desc())
    ).all()

    latest_by_platform: dict[str, PlatformExcerpt] = {}
    for r in excerpt_rows:
        if r.platform in latest_by_platform:
            continue
        text = r.answer_content or ""
        excerpt = text[:200]
        if not excerpt:
            continue
        latest_by_platform[r.platform] = PlatformExcerpt(
            excerpt=excerpt,
            rank=r.rank_position,
            run_id=r.subtask_id,
        )

    return QuestionProductAnalyticsOut(
        project_id=project.id,
        prompt_id=prompt.id,
        start=start,
        end=end,
        platforms=platforms_out,
        prev=prev_stat,
        long_prev=long_prev_stat,
        excerpts=latest_by_platform,
    )


@router.get(
    "/projects/{project_id}/questions/{prompt_id}/product-analytics",
    response_model=QuestionProductAnalyticsOut,
)
def questions_product_analytics(
    project_id: int,
    prompt_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
) -> QuestionProductAnalyticsOut:
    """单问题产品分析:platform 统计 + prev + long_prev + 6 平台摘录。

    与 summary 的差别:返回单问题而非整个项目;与 status-changes 的差别:不扫
    全项目竞品明细。spec §4.2 要求核心 SQL ≤ 3 条(不含鉴权与项目存在性查询)。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    prompt = _get_project_prompt_or_404(
        db, project_id=project.id, prompt_id=prompt_id
    )
    win_start_dt, win_end_dt = _resolve_window_inline(days, start, end)

    return _compute_question_product_analytics(
        db, project, prompt, start=win_start_dt, end=win_end_dt
    )


def _compute_question_competitor_analytics(
    db: Session,
    project: Project,
    prompt: ProjectPrompt,
    *,
    start: datetime,
    end: datetime,
) -> QuestionCompetitorAnalyticsOut:
    """单问题竞品分析:按 brand × platform 聚合,SQL 预算 ≤ 2。

    与产品分析的差别:产品分析走 ``is_self=true`` + per-platform stats +
    prev/long_prev;这里走 ``is_self=false`` + per-brand stats,只取当前
    窗口(竞品面板不显示 prev delta,UI 在 OverviewTab 已经有 delta 行)。

    SQL 预算 = 2 条核心 SELECT:
      1) brand aggregation:扫 ``BrandMention``(过滤 ``is_self=false``),
         在 Python 中按 (brand_canonical, platform) 汇总 ranks。
      2) excerpts:每个 platform 取窗口内最新 Subtask + 对应
         (is_self=false) rank,join ``Task`` 用 project_id 防御
         (同一 prompt 文本可能跨项目存在)。左连接 ``BrandMention`` —
         生产数据总是有 ``BrandMention`` 行,孤儿 subtask(测试 fixture
         可能没有)走外连接以避免静默丢失。
    """
    rows = db.execute(
        select(
            BrandMention.brand_canonical,
            BrandMention.platform,
            BrandMention.rank_position,
        ).where(
            BrandMention.project_id == project.id,
            BrandMention.is_self.is_(False),
            BrandMention.prompt == prompt.prompt,
            BrandMention.created_at >= start,
            BrandMention.created_at < end,
        )
    ).all()

    grouped: dict[tuple[str, str], list[int | None]] = defaultdict(list)
    total_per_brand: dict[str, int] = defaultdict(int)
    for r in rows:
        grouped[(r.brand_canonical, r.platform)].append(r.rank_position)
        total_per_brand[r.brand_canonical] += 1

    by_brand: dict[str, dict[str, list[int | None]]] = defaultdict(dict)
    for (brand, platform), ranks in grouped.items():
        by_brand[brand][platform] = ranks

    # Fixed palette for the competitor panel — same slot cycle as the
    # analytics endpoint's competitor matrix so the visual layout is
    # stable across windows. Self brand color is reserved (not used
    # here since the competitor endpoint never returns self rows).
    _COMP_COLORS = ("#ff6b1a", "#52c41a", "#722ed1", "#13c2c2")

    brands_out: list[CompetitorBrandStat] = []
    # Sort by mention_rate desc so the highest-traffic competitor
    # always lands on the first palette slot; ties broken by
    # brand_canonical so the order is deterministic across windows.
    sorted_brands = sorted(
        by_brand.keys(),
        key=lambda b: (
            -(total_per_brand[b]),
            b,
        ),
    )
    for slot, brand_canonical in enumerate(sorted_brands):
        platforms = by_brand[brand_canonical]
        all_ranks = [r for rs in platforms.values() for r in rs if r is not None]
        matched = len(all_ranks)
        total = total_per_brand[brand_canonical]
        brands_out.append(
            CompetitorBrandStat(
                brand_canonical=brand_canonical,
                is_self=False,
                color=_COMP_COLORS[slot % len(_COMP_COLORS)],
                mention_rate=(matched / total) if total else 0.0,
                top1_rate=(sum(1 for r in all_ranks if r == 1) / total) if total else 0.0,
                top3_rate=(sum(1 for r in all_ranks if r <= 3) / total) if total else 0.0,
                avg_rank=(sum(all_ranks) / len(all_ranks)) if all_ranks else None,
                model_ranks={
                    platform: min((r for r in ranks if r is not None), default=None)
                    for platform, ranks in platforms.items()
                },
            )
        )

    # 摘录:竞品面板也展示 6 平台原文,SQL 一次 join Task 限定项目
    excerpt_rows = db.execute(
        select(
            Subtask.platform,
            Subtask.answer_content,
            Subtask.subtask_id,
            BrandMention.rank_position,
        )
        .outerjoin(Task, Task.task_id == Subtask.task_id)
        .outerjoin(
            BrandMention,
            and_(
                BrandMention.subtask_id == Subtask.subtask_id,
                BrandMention.is_self.is_(False),
                BrandMention.prompt == prompt.prompt,
            ),
        )
        .where(
            (Task.project_id.is_(None) | (Task.project_id == project.id)),
            Subtask.prompt == prompt.prompt,
            Subtask.updated_at >= start,
            Subtask.updated_at < end,
        )
        .order_by(Subtask.platform, Subtask.updated_at.desc())
    ).all()

    latest_by_platform: dict[str, PlatformExcerpt] = {}
    for r in excerpt_rows:
        if r.platform in latest_by_platform:
            continue
        excerpt = (r.answer_content or "")[:200]
        if not excerpt:
            continue
        latest_by_platform[r.platform] = PlatformExcerpt(
            excerpt=excerpt,
            rank=r.rank_position,
            run_id=r.subtask_id,
        )

    return QuestionCompetitorAnalyticsOut(
        project_id=project.id,
        prompt_id=prompt.id,
        start=start,
        end=end,
        brands=brands_out,
        excerpts=latest_by_platform,
    )


@router.get(
    "/projects/{project_id}/questions/{prompt_id}/competitor-analytics",
    response_model=QuestionCompetitorAnalyticsOut,
)
def questions_competitor_analytics(
    project_id: int,
    prompt_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
) -> QuestionCompetitorAnalyticsOut:
    """单问题竞品分析:按 brand × platform 聚合,SQL 预算 ≤ 2。

    旧 ``/questions/analytics?view=competitor`` 路径已删除(见 Task 13)。
    本端点只服务「竞品分析」子面板,不返回 self-brand 行。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    prompt = _get_project_prompt_or_404(
        db, project_id=project.id, prompt_id=prompt_id
    )
    win_start_dt, win_end_dt = _resolve_window_inline(days, start, end)

    return _compute_question_competitor_analytics(
        db, project, prompt, start=win_start_dt, end=win_end_dt
    )


@router.get(
    "/projects/{project_id}/questions/status-changes",
    response_model=QuestionStatusChangesOut,
)
def questions_status_changes(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Classify each question into one of 4 sets for the 稳定与掉落 pane.

    Window handling matches :func:`_resolve_window_inline` (same
    ``start``/``end``/``days`` semantics). ``is_self=true`` rows are
    the only ones considered — the operator's own brand is what the
    project monitors. Paused prompts (``status != monitoring``) are
    filtered out entirely: a paused question can never be "stable" or
    "dropped" because the scheduler isn't asking it.

    Four sets (NOT a 2x2 cross-tab):
      - ``stable``: prev_window had a mention AND current_window has
        at least one mention → kept being mentioned.
      - ``drops``: per (prompt, platform) loss-of-mention events.
        Emitted when prev had a mention and current has either no
        mention or a rank_position that's worse than Top-3.
      - ``never_listed``: no mention in either window.
      - ``listed``: at least one mention in the current window
        (regardless of prev).

    Drops carry a ``reason`` for the UI badge: "从排名 N 跌出 Top3"
    when the rank went from in-range to out-of-range, "从上榜掉出"
    when the mention disappeared entirely.
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    # Window resolution — copy the same shape as `_resolve_window_inline`.
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=window_days - 1)
        win_end = today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    length_days = (win_end - win_start).days + 1
    prev_end_dt = datetime.combine(win_start - timedelta(days=1), time.max)
    prev_start_dt = datetime.combine(
        win_start - timedelta(days=length_days), time.min
    )

    # Pull the catalogue — monitoring prompts only, in the operator's
    # configured order.
    prompt_rows = db.execute(
        select(
            ProjectPrompt.id,
            ProjectPrompt.prompt,
            ProjectPrompt.category,
        )
        .where(
            ProjectPrompt.project_id == project_id,
            ProjectPrompt.status == "monitoring",
        )
        .order_by(ProjectPrompt.sort)
    ).all()
    prompt_meta: dict[str, dict] = {
        prompt: {"id": pid, "category": cat}
        for pid, prompt, cat in prompt_rows
    }

    # Per-(prompt, platform) presence in each window, plus the best
    # rank observed. One row per (prompt, platform) that has at least
    # one mention in either window.
    presence_rows = db.execute(
        select(
            BrandMention.prompt,
            BrandMention.platform,
            func.max(
                case(
                    (
                        and_(
                            BrandMention.created_at >= prev_start_dt,
                            BrandMention.created_at <= prev_end_dt,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("in_prev"),
            func.max(
                case(
                    (
                        and_(
                            BrandMention.created_at >= win_start_dt,
                            BrandMention.created_at <= win_end_dt,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("in_cur"),
            # Best (smallest) rank per window — used by drops to
            # describe the rank transition. Null when no rank rows.
            func.min(
                case(
                    (
                        and_(
                            BrandMention.created_at >= prev_start_dt,
                            BrandMention.created_at <= prev_end_dt,
                            BrandMention.rank_position.is_not(None),
                        ),
                        BrandMention.rank_position,
                    ),
                    else_=None,
                )
            ).label("best_prev_rank"),
            func.min(
                case(
                    (
                        and_(
                            BrandMention.created_at >= win_start_dt,
                            BrandMention.created_at <= win_end_dt,
                            BrandMention.rank_position.is_not(None),
                        ),
                        BrandMention.rank_position,
                    ),
                    else_=None,
                )
            ).label("best_cur_rank"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_self.is_(True),
        )
        .group_by(BrandMention.prompt, BrandMention.platform)
    ).all()

    # Per-prompt current platform list — for the 上榜 quadrant the
    # UI shows the platforms that drove the mention. Cache once.
    cur_platforms: dict[str, set[str]] = {}
    for prompt, platform, _p, in_cur, _bp, _bc in presence_rows:
        if in_cur:
            cur_platforms.setdefault(prompt or "(空问题)", set()).add(platform)
    prev_platforms: dict[str, set[str]] = {}
    for prompt, platform, in_prev, _c, _bp, _bc in presence_rows:
        if in_prev:
            prev_platforms.setdefault(prompt or "(空问题)", set()).add(platform)

    # Build the 4 sets.
    stable: list[QuestionStableItem] = []
    drops: list[DropEvent] = []
    listed: list[QuestionStableItem] = []
    never_listed: list[QuestionStableItem] = []

    # Track which prompts have already been emitted into listed/
    # stable so the loop below doesn't double-emit.
    emitted: set[str] = set()
    # Per-prompt mention count for stable sort (most-mentioned first).
    stable_mentions: dict[str, int] = {}
    listed_mentions: dict[str, int] = {}

    for prompt, meta in prompt_meta.items():
        in_cur_set = cur_platforms.get(prompt, set())
        in_prev_set = prev_platforms.get(prompt, set())
        if in_cur_set and in_prev_set:
            stable.append(
                QuestionStableItem(
                    prompt_id=meta["id"],
                    prompt=prompt,
                    category=meta["category"],
                    platforms=sorted(in_cur_set),
                )
            )
            stable_mentions[prompt] = len(in_cur_set)
            emitted.add(prompt)
        if in_cur_set:
            listed.append(
                QuestionStableItem(
                    prompt_id=meta["id"],
                    prompt=prompt,
                    category=meta["category"],
                    platforms=sorted(in_cur_set),
                )
            )
            listed_mentions[prompt] = len(in_cur_set)
            emitted.add(prompt)

    # Drops — per (prompt, platform) row that was in prev but is
    # either missing in current or fell out of Top-3.
    for prompt, platform, in_prev, in_cur, best_prev, best_cur in presence_rows:
        if not in_prev or in_cur:
            continue
        meta = prompt_meta.get(prompt or "(空问题)")
        if not meta:
            continue
        if best_prev is None:
            # Prev had a mention without a rank — can't describe a
            # rank transition. Fall back to "掉出" wording.
            reason = "从上榜掉出"
        elif best_cur is None:
            reason = f"从排名 {best_prev} 跌出 Top3"
        else:
            reason = f"从排名 {best_prev} 跌出 Top3"
        drops.append(
            DropEvent(
                prompt_id=meta["id"],
                prompt=prompt,
                category=meta["category"],
                platform=platform,
                dropped_day=win_end.isoformat(),
                from_rank=best_prev,
                to_rank=best_cur,
                reason=reason,
            )
        )

    # never_listed — catalogue prompts that never appeared in either
    # window. Sort by configured order (already ordered, but
    # convert set to list for stable JSON output).
    for prompt, meta in prompt_meta.items():
        if prompt in emitted:
            continue
        if not cur_platforms.get(prompt) and not prev_platforms.get(prompt):
            never_listed.append(
                QuestionStableItem(
                    prompt_id=meta["id"],
                    prompt=prompt,
                    category=meta["category"],
                    platforms=[],
                )
            )

    # Sort for stable UI rendering.
    stable.sort(key=lambda x: (-stable_mentions.get(x.prompt, 0), x.prompt_id))
    listed.sort(key=lambda x: (-listed_mentions.get(x.prompt, 0), x.prompt_id))
    drops.sort(key=lambda x: (x.dropped_day, x.platform, x.prompt_id))
    never_listed.sort(key=lambda x: x.prompt_id)

    return QuestionStatusChangesOut(
        project_id=project_id,
        start=win_start.isoformat(),
        end=win_end.isoformat(),
        stable=stable,
        drops=drops,
        never_listed=never_listed,
        listed=listed,
    )


@router.get(
    "/projects/{project_id}/brand-mentions/summary",
    response_model=BrandMentionSummary,
)
def brand_mentions_summary(
    project_id: int,
    days: int = 15,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """KPI roll-up for the overview tab.

    Only counts the *monitored* brand (``is_self=true``) so the cards
    render "your brand's mentions" rather than "everyone's mentions".
    """
    from datetime import timedelta

    from app.models.common import now_local

    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    cutoff = now_local() - timedelta(days=days)
    base = select(BrandMention).where(
        BrandMention.project_id == project_id,
        BrandMention.is_self.is_(True),
        BrandMention.created_at >= cutoff,
    )
    rows = db.scalars(base).all()
    if not rows:
        return BrandMentionSummary(
            project_id=project_id,
            total_mentions=0,
            top1_rate=0.0,
            top3_rate=0.0,
            coverage=0,
            avg_sentiment=None,
            pending_count=0,
            failed_count=0,
        )
    total_mentions = sum(r.mention_count for r in rows)
    n = len(rows)
    top1 = sum(1 for r in rows if r.rank_position == 1)
    top3 = sum(1 for r in rows if r.rank_position is not None and r.rank_position <= 3)
    # sentiment_score is stored as a label string; translate to float for the
    # UI's color buckets (>=0.7 green / >=0.5 orange / else red).
    sentiment_values = [
        _SENTIMENT_TO_FLOAT[r.sentiment_score]
        for r in rows
        if r.sentiment_score in _SENTIMENT_TO_FLOAT
    ]
    avg_sentiment = (
        sum(sentiment_values) / len(sentiment_values) if sentiment_values else None
    )
    pending_count = sum(1 for r in rows if r.extract_status.value == "pending")
    failed_count = sum(1 for r in rows if r.extract_status.value == "failed")
    coverage = len({(r.prompt, r.platform) for r in rows})
    return BrandMentionSummary(
        project_id=project_id,
        total_mentions=total_mentions,
        top1_rate=top1 / n if n else 0.0,
        top3_rate=top3 / n if n else 0.0,
        coverage=coverage,
        avg_sentiment=avg_sentiment,
        pending_count=pending_count,
        failed_count=failed_count,
    )


# --------------------------------------------------------------------------
# Competitor analysis (data tab → 竞品分析)
# --------------------------------------------------------------------------


# Colors mirror ``frontend/src/pages/Projects/platforms.ts::PLATFORM_CATALOG``
# but we hardcode just the slots we need (self + 5 competitor slots) so the
# chart legend stays stable even when the project only has 2 platforms.
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


@router.get(
    "/projects/{project_id}/competitor-analysis",
    response_model=CompetitorAnalysisOut,
)
def competitor_analysis(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Drives the 竞品分析 tab (data tab → 竞品分析).

    Returns a single bundle the frontend renders as the 2×2 grid
    (概览表 / 趋势对比 / 差异化标签云 / 竞争优势矩阵):

    - ``total_subtasks`` — window-wide denominator for every
      ``mention_rate``; same value for every brand so the bars are
      apples-to-apples.
    - ``self_brand`` — monitored brand's KPIs, or ``None`` when the
      project hasn't picked a brand yet.
    - ``competitors`` — every non-self brand that appeared at least
      once in the window, sorted by ``mention_count`` DESC. The KPI
      shape mirrors ``self_brand`` so the table and the chart can mix
      them without special-casing.
    - ``trend`` — daily mention counts per brand for the whole window;
      the frontend draws one line per brand with ``color`` so the
      legend matches the line.
    - ``concern_tags`` — aggregated ``concern_hits_json`` tokens
      (which the LLM extraction writes as "the project's keywords
      that co-occurred with this brand in the AI's reply"). Rendered
      as the 差异化标签云 — until a dedicated NLP keyword-extraction
      step lands, this is the best structured signal for "what
      attributes does the AI associate with this brand?".
    """
    win_start, win_end = _resolve_competitor_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    # Resolve the brand → name/aliases lookup so the chart legend and
    # the 概览 table show the human-readable display name rather than
    # the canonical string. Self brand falls back to
    # ``project.brand`` / ``project.aliases`` because that path is
    # authoritative — there's no competitor row for it.
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

    # ------------------------------------------------------------
    # 1. Per-brand rollup (KPI rows for the 概览 table)
    # ------------------------------------------------------------
    # ``mention_count`` on BrandMention is 0/1 (regex pass), so the
    # matched-subtask count is just rows where mention_count > 0.
    # MySQL doesn't support PostgreSQL's FILTER clause, so we use
    # SUM(CASE WHEN ...) which both engines accept.
    brand_rows = db.execute(
        select(
            BrandMention.brand_canonical,
            BrandMention.is_self,
            func.sum(
                case((BrandMention.mention_count > 0, 1), else_=0)
            ).label("matched"),
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
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
        .group_by(BrandMention.brand_canonical, BrandMention.is_self)
    ).all()

    # Window-wide denominator — total distinct subtasks seen in the
    # window. We use COUNT(DISTINCT subtask_id) of the whole window
    # (any brand) so every brand's mention_rate uses the same base.
    total_subtasks = db.scalar(
        select(func.count(func.distinct(BrandMention.subtask_id))).where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
    ) or 0

    # Daily series for the trend chart. Build a 0-filled (date × brand)
    # matrix so missing days render as 0 instead of a gap.
    days_n = (win_end - win_start).days + 1
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

    # 15-day sparkline (matches the fixed window). For shorter windows we
    # zero-fill trailing days so the chip stays a constant width.
    spark_len = min(15, days_n)
    spark_start = win_end - timedelta(days=spark_len - 1)

    def _kpi_for(brand: str, is_self: bool, r) -> CompetitorKpi:
        matched = int(r.matched or 0)
        top3 = int(r.top3_hits or 0)
        rec = int(r.rec_hits or 0)
        avg_sent = float(r.avg_sentiment) if r.avg_sentiment is not None else None
        avg_rk = float(r.avg_rank) if r.avg_rank is not None else None
        display_name, aliases, _is_self_lookup = name_by_brand.get(
            brand, (brand, None, is_self)
        )
        # Spark = daily mention counts in the trailing 15 days, zero-filled.
        spark: list[int] = []
        for i in range(spark_len):
            d = spark_start + timedelta(days=i)
            if d < win_start:
                spark.append(0)
            else:
                spark.append(daily_by_brand.get(brand, {}).get(d, 0))
        return CompetitorKpi(
            brand_canonical=brand,
            name=display_name,
            aliases=aliases,
            is_self=is_self,
            mention_count=matched,
            mention_rate=matched / total_subtasks if total_subtasks else 0.0,
            # Top3 / 推荐度 跟 mention_rate 共用同一个分母(total_subtasks),
            # 这样三个率都是"所有 subtask 中发生 X 的比例",可以直接对比。
            # 之前用 matched 当分母会让"被提到的 100% 都是 Top3"这种 case
            # 退化成 100%,变成不携带信息的常数。/Q: 这个在 8/18 看截图确认的
            top3_rate=top3 / total_subtasks if total_subtasks else 0.0,
            recommend_rate=rec / total_subtasks if total_subtasks else 0.0,
            avg_sentiment=avg_sent,
            avg_rank=avg_rk,
            spark=spark,
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

    # ------------------------------------------------------------
    # 2. Trend chart series — one line per brand (self + top N
    #    competitors) with a stable color so the legend reads well.
    # ------------------------------------------------------------
    labels: list[str] = []
    for i in range(days_n):
        d = win_start + timedelta(days=i)
        labels.append(d.isoformat())

    def _series_for(brand: str, name: str, is_self: bool, color: str) -> CompetitorTrendSeries:
        per_day = daily_by_brand.get(brand, {})
        data = [per_day.get(win_start + timedelta(days=i), 0) for i in range(days_n)]
        return CompetitorTrendSeries(
            brand_canonical=brand,
            name=name,
            is_self=is_self,
            color=color,
            data=data,
        )

    series: list[CompetitorTrendSeries] = []
    if self_kpi is not None:
        series.append(
            _series_for(
                self_kpi.brand_canonical,
                self_kpi.name,
                True,
                _COMPETITOR_LINE_COLORS[0],
            )
        )
    for i, kpi in enumerate(competitor_kpis[:5], start=1):
        series.append(
            _series_for(
                kpi.brand_canonical,
                kpi.name,
                False,
                _COMPETITOR_LINE_COLORS[i % len(_COMPETITOR_LINE_COLORS)],
            )
        )

    trend_block = CompetitorTrendBlock(labels=labels, series=series)

    # ------------------------------------------------------------
    # 3. Concern tag cloud — flatten concern_hits_json from
    #    non-self rows. Each occurrence counts once per (subtask,
    #    brand) row, so a brand mentioned 5 times with the same
    #    keyword contributes 5 to that keyword's weight.
    # ------------------------------------------------------------
    tag_counter: Counter[str] = Counter()
    tag_rows = db.execute(
        select(
            BrandMention.concern_hits_json,
            BrandMention.sentiment_score,
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_self.is_(False),
            BrandMention.mention_count > 0,
            BrandMention.concern_hits_json.is_not(None),
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
    ).all()
    for hits, _sent in tag_rows:
        if not hits:
            continue
        for h in hits:
            if isinstance(h, str) and h.strip():
                tag_counter[h.strip()] += 1
    top_tags = tag_counter.most_common(20)
    if not top_tags:
        concern_tags: list[ConcernTag] = []
    else:
        # Distribute the four ui-sample tag classes by quartile of the
        # weights so the cloud looks visually varied (top = brand, then
        # positive, default, warn, negative).
        max_w = top_tags[0][1]
        concern_tags = []
        n = len(top_tags)
        for i, (text, w) in enumerate(top_tags):
            ratio = i / max(n - 1, 1)
            if ratio < 0.15:
                cls = "brand"
            elif ratio < 0.45:
                cls = "positive"
            elif ratio < 0.75:
                cls = "default"
            elif ratio < 0.92:
                cls = "warn"
            else:
                cls = "negative"
            concern_tags.append(ConcernTag(text=text, weight=w, cls=cls))

    return CompetitorAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days_n,
        total_subtasks=int(total_subtasks),
        self_brand=self_kpi,
        competitors=competitor_kpis,
        trend=trend_block,
        concern_tags=concern_tags,
    )


# --------------------------------------------------------------------------
# Citation analysis (data tab → 引用源分析)
# --------------------------------------------------------------------------


def _classify_citation(host: str) -> str:
    """Map a citation host string to one of the ui-sample category labels.

    The host is pre-normalized (lowercase, scheme stripped) — this
    function only does substring matching. The first matching rule
    wins; fallback is "其他". Pure function so the unit tests can call
    it without a DB.
    """
    if not host:
        return "其他"
    h = host.lower()
    for type_name, needles in _CITATION_DOMAIN_RULES:
        for n in needles:
            if n in h:
                return type_name
    return "其他"


@router.get(
    "/projects/{project_id}/citation-analysis",
    response_model=CitationAnalysisOut,
)
def citation_analysis(
    project_id: int,
    days: int = 15,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Windowed aggregate of citations the AI models linked in their answers.

    The UI on docs/ui-sample/index.html #tab-citation shows per-URL rows
    with type, citation count and rank position. We pull every
    ``geo_subtasks.citation_list_json`` in the last ``days`` days
    (default 15, max 90 — the same ceiling the 竞品分析 tab uses),
    explode each list into (subtask, rank, url, site, title) rows,
    and aggregate by URL.

    Per Molizhishu API contract: ``referenceList`` is the *complete*
    pool of references the model had available, while ``citationList``
    is the *subset* the model actually cited in the answer body. This
    endpoint therefore reads ``citationList`` — counting every
    reference would inflate the metrics with sources the operator's
    audience never saw. On non-yuanbao platforms ``citationList``
    comes back as plain URL strings; on yuanbao it's a list of
    ``{url, site, title, ...}`` dicts. The handler accepts both.

    The secondary tabs (全部 / 官方网站 / 新闻网站 / 自媒体) and the
    filter bar (模型 / 业务排名 / 关键词) are the only axis the UI
    owns beyond the time selector.

    Domain classification is a small substring table on the host
    substring (see ``_CITATION_DOMAIN_RULES`` in schemas.project). The
    classifier is deliberately conservative — anything that doesn't
    match a known category falls into "其他". This is much cheaper
    than calling out to a third-party DR / traffic API and keeps the
    entire response deterministic.
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    win_start, win_end = _resolve_competitor_window(days, None, None)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = db.execute(
        select(
            Subtask.subtask_id,
            Subtask.platform,
            Subtask.citation_list_json,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    ).all()

    # Per-URL aggregation. We keep two parallel dicts:
    #   buckets[url] -> {site, title, count, sum_rank, n_rank, platforms, first, last}
    #   total_citations -> (subtask, citation) pair count
    total_citations = 0
    buckets: dict[str, dict] = {}
    for subtask_id, platform, cites, created_at in rows:
        items = cites if isinstance(cites, list) else []
        if not items:
            continue
        for idx, item in enumerate(items):
            # citation_list_json shape is platform-dependent:
            #   - yuanbao returns {url, site, title, summary, index, ...}
            #   - deepseek / doubao / hunyuan / qianwen / wenxinyiyan
            #     return a flat list of URL strings
            # Treat both as the same row — the dict carries site/title,
            # the string carries just the URL.
            if isinstance(item, dict):
                url = item.get("url") or item.get("link")
                if not isinstance(url, str) or not url.strip():
                    continue
                site = item.get("site") or ""
                if not isinstance(site, str):
                    site = ""
                title = item.get("title") or ""
                if not isinstance(title, str):
                    title = ""
            elif isinstance(item, str):
                url = item
                site = ""
                title = ""
            else:
                continue
            url = url.strip()
            total_citations += 1
            cur = buckets.get(url)
            if cur is None:
                cur = {
                    "site": site,
                    "title": title,
                    "count": 0,
                    "sum_rank": 0,
                    "n_rank": 0,
                    "platforms": set(),
                    "first_seen": created_at,
                    "last_seen": created_at,
                }
                buckets[url] = cur
            # Last write wins for title (we don't store a history).
            if title:
                cur["title"] = title
            if site and not cur["site"]:
                cur["site"] = site
            cur["count"] += 1
            cur["sum_rank"] += idx
            cur["n_rank"] += 1
            if platform:
                cur["platforms"].add(platform)
            if created_at < cur["first_seen"]:
                cur["first_seen"] = created_at
            if created_at > cur["last_seen"]:
                cur["last_seen"] = created_at

    items: list[CitationOut] = []
    type_counts: dict[str, int] = {}
    for url, cur in buckets.items():
        host = cur["site"] or url
        type_name = _classify_citation(host)
        type_counts[type_name] = type_counts.get(type_name, 0) + cur["count"]
        items.append(
            CitationOut(
                url=url,
                site=cur["site"],
                title=cur["title"] or None,
                type=type_name,
                count=cur["count"],
                avg_rank=(cur["sum_rank"] / cur["n_rank"]) if cur["n_rank"] else None,
                platforms=sorted(cur["platforms"]),
                first_seen=cur["first_seen"],
                last_seen=cur["last_seen"],
            )
        )
    items.sort(key=lambda c: c.count, reverse=True)

    return CitationAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days,
        total_citations=total_citations,
        unique_urls=len(buckets),
        type_counts=type_counts,
        items=items,
    )


# --------------------------------------------------------------------------
# Overview tab (docs/ui-sample #tab-overview)
# --------------------------------------------------------------------------

# A custom range wider than this is rejected: the daily buckets stop being
# readable and the query stops being cheap.
OVERVIEW_MAX_DAYS = 62
OVERVIEW_PRESET_DAYS = (7, 15, 30, 60)


def _overview_window(
    days: int, start: date | None, end: date | None
) -> tuple[date, date]:
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        if (end - start).days + 1 > OVERVIEW_MAX_DAYS:
            raise HTTPException(400, f"range must not exceed {OVERVIEW_MAX_DAYS} days")
        return start, end
    if days not in OVERVIEW_PRESET_DAYS:
        raise HTTPException(400, f"days must be one of {OVERVIEW_PRESET_DAYS}")
    today = now_local().date()
    return today - timedelta(days=days - 1), today


def _rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def _delta_pct(value: float, prev: float) -> float | None:
    """Growth vs the previous window; None when there is no baseline."""
    if prev == 0:
        return None
    return (value - prev) / prev


class _OverviewWindow:
    """Everything one time window contributes to the overview tab."""

    def __init__(
        self, db: Session, project_id: int, start: date, end: date
    ) -> None:
        self.days = [
            start + timedelta(days=i) for i in range((end - start).days + 1)
        ]
        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)

        self.mentions = db.scalars(
            select(BrandMention).where(
                BrandMention.project_id == project_id,
                BrandMention.is_self.is_(True),
                BrandMention.created_at >= lo,
                BrandMention.created_at <= hi,
            )
        ).all()

        # Subtasks carry no timestamp of their own, so they inherit the day
        # of the run that produced them. ``answer_content`` is measured in
        # SQL rather than selected — the column holds full answers.
        self.answers = db.execute(
            select(
                Task.created_local_at,
                Subtask.task_id,
                Subtask.prompt,
                func.length(func.coalesce(Subtask.answer_content, "")) > 0,
            )
            .join(Subtask, Subtask.task_id == Task.task_id)
            .where(
                Task.project_id == project_id,
                Task.created_local_at >= lo,
                Task.created_local_at <= hi,
            )
        ).all()

        # Per-subtask status rollup. Used for:
        #   - ``correct_rate`` 分子 (status in success/completed)
        #   - per-platform ``total_subtasks`` 分母 in model_dimensions
        # We pull only the columns we need; ``answer_content`` (potentially
        # large) stays in self.answers via its own select.
        self.subtask_rows = db.execute(
            select(
                Subtask.platform,
                Subtask.status,
                Task.created_local_at,
            )
            .join(Task, Task.task_id == Subtask.task_id)
            .where(
                Task.project_id == project_id,
                Task.created_local_at >= lo,
                Task.created_local_at <= hi,
            )
        ).all()

    @property
    def total_subtasks(self) -> int:
        """Window subtask count. Denominator for ``mention_rate`` and
        ``correct_rate``."""
        return len(self.subtask_rows)

    @property
    def correct_subtasks(self) -> int:
        """Count of subtasks whose ``status`` is ``success`` (production
        pipeline terminal state) or ``completed`` (legacy mock data).
        Mirrors what frontend used to filter the 查看原文 modal — see
        ``QuestionTab.tsx`` "completed || success" comment."""
        return sum(
            1
            for _platform, status, _created in self.subtask_rows
            if status in ("success", "completed")
        )

    def kpis(self) -> dict[str, tuple[float, list[float]]]:
        """Window totals plus the per-day sparkline for each KPI card."""
        by_day_mentions: dict[date, list[BrandMention]] = {d: [] for d in self.days}
        for m in self.mentions:
            bucket = by_day_mentions.get(m.created_at.date())
            if bucket is not None:
                bucket.append(m)

        asked: dict[date, set[tuple[str, str | None]]] = {d: set() for d in self.days}
        answered: dict[date, int] = {d: 0 for d in self.days}
        for created_at, task_id, prompt, has_answer in self.answers:
            day = created_at.date()
            if day not in asked:
                continue
            asked[day].add((task_id, prompt))
            if has_answer:
                answered[day] += 1

        n = len(self.mentions)
        top1 = sum(1 for m in self.mentions if m.rank_position == 1)
        top3 = sum(
            1
            for m in self.mentions
            if m.rank_position is not None and m.rank_position <= 3
        )

        # Subtask counts bucketed per day, used for the new
        # ``mention_rate`` and ``correct_rate`` sparklines.
        subtasks_by_day: dict[date, int] = {d: 0 for d in self.days}
        correct_by_day: dict[date, int] = {d: 0 for d in self.days}
        for _platform, status, created_at in self.subtask_rows:
            day = created_at.date()
            if day not in subtasks_by_day:
                continue
            subtasks_by_day[day] += 1
            if status in ("success", "completed"):
                correct_by_day[day] += 1

        total_subs = max(self.total_subtasks, 1)
        return {
            # Mention rate: % of subtasks in which the brand was actually
            # named in the answer (mention_count > 0). Sum-of-counts is
            # 0/1 in the new pipeline, but we keep the sum form so a
            # future pipeline that emits per-mention counters stays
            # consistent.
            "mention_rate": (
                _rate(sum(m.mention_count for m in self.mentions), total_subs),
                [
                    _rate(
                        sum(m.mention_count for m in by_day_mentions[d]),
                        max(subtasks_by_day[d], 1),
                    )
                    for d in self.days
                ],
            ),
            "total_mentions": (
                float(sum(m.mention_count for m in self.mentions)),
                [
                    float(sum(m.mention_count for m in by_day_mentions[d]))
                    for d in self.days
                ],
            ),
            "top1_rate": (
                _rate(top1, n),
                [
                    _rate(
                        sum(1 for m in by_day_mentions[d] if m.rank_position == 1),
                        len(by_day_mentions[d]),
                    )
                    for d in self.days
                ],
            ),
            "top3_rate": (
                _rate(top3, n),
                [
                    _rate(
                        sum(
                            1
                            for m in by_day_mentions[d]
                            if m.rank_position is not None and m.rank_position <= 3
                        ),
                        len(by_day_mentions[d]),
                    )
                    for d in self.days
                ],
            ),
            # Correct rate: % of subtasks that returned a usable answer.
            # "Correct" = status in (success, completed) — see
            # correct_subtasks property for the rationale on the dual
            # accepted values.
            "correct_rate": (
                _rate(self.correct_subtasks, total_subs),
                [
                    _rate(correct_by_day[d], max(subtasks_by_day[d], 1))
                    for d in self.days
                ],
            ),
            "question_count": (
                float(sum(len(asked[d]) for d in self.days)),
                [float(len(asked[d])) for d in self.days],
            ),
            "answer_count": (
                float(sum(answered[d] for d in self.days)),
                [float(answered[d]) for d in self.days],
            ),
        }


@router.get("/projects/{project_id}/overview", response_model=ProjectOverviewOut)
def project_overview(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Everything the 首屏概览 tab renders: 4 KPI cards + trend/model sub-panes.

    The 4 KPI cards mirror docs/更新版UI #tab-overview: 总提及率 / Top1 / Top3
    / 正确率. Per-day sparklines come from the same windowed buckets as
    the count card (mention_rate / correct_rate bucket subtasks, top1
    and top3 bucket mentions).

    ``start``/``end`` (inclusive, local dates) drive the 自定义 range and
    win over ``days``; without them the window is the last ``days`` days
    ending today.
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    win_start, win_end = _overview_window(days, start, end)
    span = (win_end - win_start).days + 1
    cur = _OverviewWindow(db, project_id, win_start, win_end)
    prev = _OverviewWindow(
        db, project_id, win_start - timedelta(days=span), win_start - timedelta(days=1)
    )
    cur_kpis, prev_kpis = cur.kpis(), prev.kpis()

    def card(key: str) -> OverviewKpi:
        value, spark = cur_kpis[key]
        prev_value = prev_kpis[key][0]
        return OverviewKpi(
            value=value,
            prev_value=prev_value,
            delta_pct=_delta_pct(value, prev_value),
            spark=spark,
        )

    # Legend order follows the project's configured platforms so a platform
    # with no data in the window still shows up as a flat line.
    platforms = list(
        dict.fromkeys(
            db.scalars(
                select(ProjectPlatform.platform)
                .where(ProjectPlatform.project_id == project_id)
                .order_by(ProjectPlatform.id)
            ).all()
        )
    )
    for m in cur.mentions:
        if m.platform and m.platform not in platforms:
            platforms.append(m.platform)

    # Per-platform subtask counts (for model_dimensions 分母). Built once
    # here so the loop below is O(mentions + subtasks) instead of
    # O(platforms * mentions + platforms * subtasks).
    subtasks_by_platform: dict[str, int] = {}
    for platform, _status, _created in cur.subtask_rows:
        if not platform:
            continue
        subtasks_by_platform[platform] = subtasks_by_platform.get(platform, 0) + 1

    trend: list[TrendSeries] = []
    ranking: list[PlatformRank] = []
    model_dimensions: list[ModelDimension] = []
    for platform in platforms:
        rows = [m for m in cur.mentions if m.platform == platform]
        per_day = {d: 0 for d in cur.days}
        for m in rows:
            day = m.created_at.date()
            if day in per_day:
                per_day[day] += m.mention_count
        trend.append(
            TrendSeries(platform=platform, data=[per_day[d] for d in cur.days])
        )
        ranking.append(
            PlatformRank(
                platform=platform,
                top1_rate=_rate(
                    sum(1 for m in rows if m.rank_position == 1), len(rows)
                ),
                sample=len(rows),
            )
        )

        # 模型维度 4 指标 — 全部用「该平台的 subtasks 总数」做分母,与
        # 竞品分析的 per-brand rate 口径一致(见 _kpi_for / CompetitorKpi)。
        platform_subs = subtasks_by_platform.get(platform, 0)
        model_dimensions.append(
            ModelDimension(
                platform=platform,
                mention_rate=_rate(
                    sum(m.mention_count for m in rows), max(platform_subs, 1)
                ),
                top1_rate=_rate(
                    sum(1 for m in rows if m.rank_position == 1),
                    max(platform_subs, 1),
                ),
                top2_rate=_rate(
                    sum(
                        1
                        for m in rows
                        if m.rank_position is not None and m.rank_position <= 2
                    ),
                    max(platform_subs, 1),
                ),
                top3_rate=_rate(
                    sum(
                        1
                        for m in rows
                        if m.rank_position is not None and m.rank_position <= 3
                    ),
                    max(platform_subs, 1),
                ),
                sample=platform_subs,
            )
        )
    ranking.sort(key=lambda r: (r.top1_rate, r.sample), reverse=True)

    return ProjectOverviewOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=span,
        labels=[d.strftime("%m-%d") for d in cur.days],
        mention_rate=card("mention_rate"),
        top1_rate=card("top1_rate"),
        top3_rate=card("top3_rate"),
        correct_rate=card("correct_rate"),
        total_mentions=card("total_mentions"),
        question_count=card("question_count"),
        answer_count=card("answer_count"),
        trend=trend,
        ranking=ranking,
        model_dimensions=model_dimensions,
        pending_count=sum(
            1 for m in cur.mentions if m.extract_status.value == "pending"
        ),
        failed_count=sum(
            1 for m in cur.mentions if m.extract_status.value == "failed"
        ),
    )
