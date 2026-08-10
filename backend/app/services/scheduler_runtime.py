"""APScheduler job loading for the embedded per-project schedule (v2).

v1 kept schedules in ``geo_schedules`` / ``geo_schedule_slots``. In v2 the
schedule lives on the project row itself: ``schedule_enabled`` plus up to two
``slotN_hour`` / ``slotN_minute`` pairs. This module turns those rows into
cron jobs.

Importing this module is side-effect free: no settings are read and no engine
is built until :func:`reload_jobs` actually runs.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.services.scheduler import run_project_async

TIMEZONE = "Asia/Shanghai"


def _scheduled_projects(db: Session) -> list[tuple[int, int, int, int]]:
    """Return ``(project_id, slot_index, hour, minute)`` for every active slot.

    Only projects that are both ``schedule_enabled`` and ``active`` qualify;
    a slot whose hour or minute is NULL is not configured and is skipped.
    """
    rows = db.execute(
        select(
            Project.id,
            Project.slot1_hour,
            Project.slot1_minute,
            Project.slot2_hour,
            Project.slot2_minute,
        )
        .where(
            Project.schedule_enabled.is_(True),
            Project.status == ProjectStatus.ACTIVE,
        )
        .order_by(Project.id)
    ).all()

    slots: list[tuple[int, int, int, int]] = []
    for project_id, slot1_hour, slot1_minute, slot2_hour, slot2_minute in rows:
        pairs = ((slot1_hour, slot1_minute), (slot2_hour, slot2_minute))
        for slot_index, (hour, minute) in enumerate(pairs, start=1):
            if hour is None or minute is None:
                continue
            slots.append((project_id, slot_index, hour, minute))
    return slots


def reload_jobs(scheduler: AsyncIOScheduler) -> int:
    """Rebuild the scheduler's job set from ``geo_projects``.

    Existing jobs are dropped first so a reload always mirrors the database
    exactly. Returns the number of jobs registered.
    """
    scheduler.remove_all_jobs()
    with get_session_factory()() as db:
        entries = _scheduled_projects(db)

    for project_id, slot_index, hour, minute in entries:
        scheduler.add_job(
            run_project_async,
            id=f"project-{project_id}-slot-{slot_index}",
            trigger=CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE),
            args=[project_id, slot_index, "cron"],
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )
    return len(entries)
