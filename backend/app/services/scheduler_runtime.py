"""APScheduler job loading for the embedded weekly schedule (v4).

The schedule lives on the project row itself:
  - ``schedule_enabled`` master switch
  - ``monitor_schedule``: per-mode map ``{"fast": {"freq", "days"},
    "think": {"freq", "days"}}``. Each mode runs its own cron jobs and
    only submits the platforms whose ``thinking_mode`` matches it.

Time-of-day comes from ``MONITOR_DEFAULT_HOUR`` / ``MONITOR_DEFAULT_MINUTE``
(env, global) — not from the project row. This module turns each
(weekday, project, mode) triple into a cron job that fires at that env
time and forwards ``mode`` to ``run_project`` so the platform filter
knows which half of the platform list to submit.

Importing this module is side-effect free: no settings are read until
:func:`reload_jobs` actually runs.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session_factory
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.services.scheduler import run_project_async

TIMEZONE = "Asia/Shanghai"


def _scheduled_projects(
    db: Session,
) -> list[tuple[int, str, list[str]]]:
    """Return ``(project_id, mode, days)`` for every project/mode pair.

    Modes are ``"fast"`` / ``"think"``. Days are ISO weekday keys
    "1".."7" (Mon=1). A pair is included when the project is enabled,
    active, has a ``monitor_schedule`` row, AND that mode's ``days`` is
    non-empty. ``schedule_enabled`` flips on for the project as a whole
    but is checked once per project — a fully disabled project is
    skipped before the per-mode loop.
    """
    rows = db.execute(
        select(Project.id, Project.monitor_schedule)
        .where(
            Project.schedule_enabled.is_(True),
            Project.status == ProjectStatus.ACTIVE,
            Project.monitor_schedule.isnot(None),
        )
        .order_by(Project.id)
    ).all()
    out: list[tuple[int, str, list[str]]] = []
    for project_id, schedule in rows:
        if not isinstance(schedule, dict):
            continue
        for mode in ("fast", "think"):
            entry = schedule.get(mode)
            if not isinstance(entry, dict):
                continue
            days = entry.get("days") or []
            if not days:
                continue
            out.append((project_id, mode, list(days)))
    return out


# Map our ISO weekday keys ("1".. "7", Mon=1) onto APScheduler's
# CronTrigger ``day_of_week`` format. APScheduler uses Sun=0..Sat=6 in
# its integer form, so ISO 1 (Mon) maps to APScheduler 0 (Mon) and ISO 7
# (Sun) maps to APScheduler 6 (Sun). We use 3-letter names because the
# rendering in ``job.trigger.fields`` is easier to assert on in tests
# than the bare integer, and they survive any future APscheduler default
# tweaks.
_ISO_TO_CRON_WEEKDAY: dict[str, str] = {
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}


def reload_jobs(scheduler: AsyncIOScheduler) -> int:
    """Rebuild the per-project job set from ``geo_projects``.

    Only removes ``project-*-day-*`` jobs — system jobs added in
    ``main.lifespan`` (e.g. ``sync_pending_tasks``) are left alone, so a
    schedule edit doesn't accidentally kill the background poll. Returns
    the number of project jobs registered.
    """
    settings = get_settings()
    for job in scheduler.get_jobs():
        if job.id.startswith("project-"):
            scheduler.remove_job(job.id)
    with get_session_factory()() as db:
        entries = _scheduled_projects(db)

    registered = 0
    for project_id, mode, days in entries:
        for weekday in days:
            cron_day = _ISO_TO_CRON_WEEKDAY.get(weekday, weekday)
            scheduler.add_job(
                run_project_async,
                id=f"project-{project_id}-day-{weekday}-{mode}",
                trigger=CronTrigger(
                    hour=settings.monitor_default_hour,
                    minute=settings.monitor_default_minute,
                    day_of_week=cron_day,
                    timezone=TIMEZONE,
                ),
                # Args list keeps manual trigger compat intact: manual
                # callers pass (project_id, slot_index, trigger_type,
                # run_id=...) and ignore mode. Cron callers append mode
                # so ``run_project`` can pick the matching platform half.
                args=[project_id, int(weekday), "cron", mode],
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
            )
            registered += 1
    return registered