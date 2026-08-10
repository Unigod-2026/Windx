"""FastAPI application entry point.

Importing this module must be side-effect free: no engine is built, no
filesystem is touched, no static directory is mounted and no scheduler is
started. All of that work happens inside the ``lifespan`` handler so the
application only pays for what it actually uses at runtime, and tests that
import ``app.main`` don't need a writable logo directory or a live database.
"""

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, customers, dashboard, projects, tasks
from app.config import get_settings
from app.services.scheduler_runtime import TIMEZONE, reload_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.mount(
        "/static",
        StaticFiles(directory=settings.logo_storage_dir, check_dir=False),
        name="static",
    )
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    reload_jobs(scheduler)
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
