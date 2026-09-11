"""APScheduler job loading for the embedded per-project schedule (v2).

v1 kept schedules in ``geo_schedules`` / ``geo_schedule_slots``. v2 first
embedded 1-2 daily slots on the project row (``slotN_hour`` /
``slotN_minute``), then migration ``20260911_0001`` replaced those with a
per-mode ``monitor_schedule`` JSON column.

The ORM is mid-refactor: those legacy columns are now dropped from
``Project`` but the new ``monitor_schedule`` column isn't declared on the
model yet, and ``app.api.projects`` / ``app.api.dashboard`` still expect
the slot-based ``schedule_slots`` / ``set_schedule_slots`` helpers.
While that lands, :func:`reload_jobs` is a no-op so the lifespan can start
without 1054'ing on a missing column.

Importing this module is side-effect free: no settings are read and no engine
is built until :func:`reload_jobs` actually runs.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

TIMEZONE = "Asia/Shanghai"


def reload_jobs(scheduler: AsyncIOScheduler) -> int:
    """Rebuild the per-project job set from ``geo_projects``.

    No-op until the per-mode ``monitor_schedule`` refactor lands. System
    jobs added in ``main.lifespan`` (e.g. ``sync_pending_tasks``) are left
    alone.
    """
    for job in scheduler.get_jobs():
        if job.id.startswith("project-"):
            scheduler.remove_job(job.id)
    return 0
