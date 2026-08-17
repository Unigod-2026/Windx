"""FastAPI application entry point.

Importing this module must be side-effect free: no engine is built, no
filesystem is touched, no static directory is mounted and no scheduler is
started. All of that work happens inside the ``lifespan`` handler so the
application only pays for what it actually uses at runtime, and tests that
import ``app.main`` don't need a writable logo directory or a live database.
"""

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, customers, dashboard, projects, tasks
from app.config import get_settings
from app.logging_setup import configure_logging
from app.services.scheduler_runtime import TIMEZONE, reload_jobs
from app.services.sync import sync_pending_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    app.mount(
        "/static",
        StaticFiles(directory=settings.logo_storage_dir, check_dir=False),
        name="static",
    )
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    reload_jobs(scheduler)
    if settings.molizhishu_sync_enabled:
        # Background poll that refreshes in-flight ``geo_tasks`` rows.
        # ``sync_pending_tasks`` is sync; ``AsyncIOScheduler`` runs it
        # in its default executor so it doesn't block the event loop.
        # ``max_instances=1, coalesce=True`` ensure a slow remote call
        # can't stack up overlapping ticks; ``misfire_grace_time=300``
        # lets us absorb a five-minute restart without a thundering
        # herd of catch-up polls.
        scheduler.add_job(
            sync_pending_tasks,
            IntervalTrigger(
                seconds=settings.molizhishu_sync_interval_seconds,
                timezone=TIMEZONE,
            ),
            id="molizhishu-sync-pending-tasks",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="windx-backend", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"ok": True}
