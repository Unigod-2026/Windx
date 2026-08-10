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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_super_admin
from app.models.common import now_local
from app.models.customer import AdminUser, Customer
from app.models.enums import ProjectStatus, RunStatus, RunTrigger
from app.models.project import (
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.schedule import ScheduleRun
from app.models.task import Task
from app.schemas.project import (
    CompetitorIn,
    CompetitorListOut,
    CompetitorOut,
    KeywordsUpdate,
    PlatformsUpdate,
    ProjectCreate,
    ProjectDetailOut,
    ProjectListOut,
    ProjectOut,
    ProjectTaskListOut,
    ProjectTaskOut,
    ProjectUpdate,
    PromptsUpdate,
    RunSummary,
    ScheduleOut,
    ScheduleRunListOut,
    ScheduleRunOut,
    ScheduleStatusUpdate,
    ScheduleUpdate,
    SlotOut,
    TriggerOut,
)
from app.services.schedule_time import cooldown_key, next_run_at

router = APIRouter(prefix="/api", tags=["projects"])


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


def _to_out(p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.slots = _slots_out(p)
    out.next_run_at = _next_run(p)
    return out


def _to_detail(p: Project, db: Session) -> ProjectDetailOut:
    # Built from the ProjectOut payload rather than ``model_validate(p)``:
    # the detail fields share names with the ORM relationships, and
    # from_attributes would pull the raw ORM rows instead of the ordered,
    # flattened lists queried below.
    return ProjectDetailOut(
        **_to_out(p).model_dump(),
        prompts=[
            r.prompt
            for r in db.scalars(
                select(ProjectPrompt)
                .where(ProjectPrompt.project_id == p.id)
                .order_by(ProjectPrompt.sort)
            )
        ],
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
    _: AdminUser = Depends(require_super_admin),
):
    page, size = _paginate(page, size)
    stmt = select(Project)
    if customer_id is not None:
        stmt = stmt.where(Project.customer_id == customer_id)
    if status:
        stmt = stmt.where(Project.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Project.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ProjectListOut(
        items=[_to_out(p) for p in items], total=total, page=page, size=size
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
    return ScheduleRunOut.model_validate(r)


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    return _to_detail(_get_project(db, project_id), db)


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = _get_project(db, project_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _to_out(p)


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
    _get_project(db, project_id)
    _replace(db, ProjectPrompt, project_id, [{"prompt": p} for p in payload.prompts])
    return {"ok": True, "count": len(payload.prompts)}


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
    _: AdminUser = Depends(require_super_admin),
):
    return _schedule_out(_get_project(db, project_id), db)


@router.put("/projects/{project_id}/schedule", response_model=ScheduleOut)
def put_schedule(
    project_id: int,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = _get_project(db, project_id)
    _apply_slots(p, payload.slots, payload.schedule_enabled)
    db.commit()
    db.refresh(p)
    return _schedule_out(p, db)


@router.delete("/projects/{project_id}/schedule", response_model=ScheduleOut)
def delete_schedule(
    project_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Reset to the no-schedule state; run history is kept."""
    p = _get_project(db, project_id)
    p.set_schedule_slots([])
    p.schedule_enabled = False
    db.commit()
    db.refresh(p)
    return _schedule_out(p, db)


@router.put("/projects/{project_id}/schedule/status", response_model=ScheduleOut)
def put_schedule_status(
    project_id: int,
    payload: ScheduleStatusUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Toggle only ``schedule_enabled``; slots are preserved across a disable."""
    p = _get_project(db, project_id)
    enabled = payload.status == "enabled"
    if enabled and not p.schedule_slots:
        raise HTTPException(400, "cannot enable a schedule with no slots")
    p.schedule_enabled = enabled
    db.commit()
    db.refresh(p)
    return _schedule_out(p, db)


@router.post("/projects/{project_id}/schedule/trigger", response_model=TriggerOut)
def trigger_schedule(
    project_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Manually queue one run (slot_index 0) and return immediately.

    Actual execution is wired in Task 7; this only reserves the run row.
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
    return TriggerOut(run_id=run.id, status="queued")


# --------------------------------------------------------------------------
# Runs + tasks
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/runs", response_model=ScheduleRunListOut)
def list_runs(
    project_id: int,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    page, size = _paginate(page, size)
    stmt = select(ScheduleRun).where(ScheduleRun.project_id == project_id)
    if status:
        stmt = stmt.where(ScheduleRun.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(ScheduleRun.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ScheduleRunListOut(
        items=[ScheduleRunOut.model_validate(r) for r in items],
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
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    page, size = _paginate(page, size)
    stmt = select(Task).where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Task.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ProjectTaskListOut(
        items=[ProjectTaskOut.model_validate(t) for t in items],
        total=total,
        page=page,
        size=size,
    )


# --------------------------------------------------------------------------
# Competitors (user-defined seed list per project)
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/competitors", response_model=CompetitorListOut)
def list_competitors(
    project_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
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
