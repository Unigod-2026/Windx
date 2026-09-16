"""FastAPI application entry point.

Importing this module must be side-effect free: no engine is built, no
filesystem is touched, no static directory is mounted and no scheduler is
started. All of that work happens inside the ``lifespan`` handler so the
application only pays for what it actually uses at runtime, and tests that
import ``app.main`` don't need a writable logo directory or a live database.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    admin_media_dictionary,
    auth,
    config,
    customers,
    dashboard,
    molizhishu,
    projects,
    tasks,
)
from app.config import get_settings
from app.logging_setup import configure_logging
from app.services.scheduler_runtime import TIMEZONE, reload_jobs
from app.services.sync import sync_pending_tasks

# 前端构建产物由 deploy.sh 在 host 跑 npm run build 生成,路径与 backend/
# 平级(dev / 生产一致)。
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_FRONTEND_INDEX = _FRONTEND_DIST / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    app.mount(
        "/static",
        StaticFiles(directory=settings.logo_storage_dir, check_dir=False),
        name="static",
    )
    # 前端 dist/ —— StaticFiles 挂在根路径服务真实静态文件(/assets/*、
    # /logo.png、/favicon.ico 等)。SPA 路由(/login、/admin/projects/38)
    # 由下面注册的 catch-all 兜底返回 index.html(Starlette 1.4 的
    # StaticFiles html=True 只 fallback 到 404.html,不会回 index.html,
    # 所以手写一条)。
    if _FRONTEND_DIST.is_dir():
        app.mount(
            "",
            StaticFiles(directory=str(_FRONTEND_DIST)),
            name="frontend-static",
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
app.include_router(config.router)
app.include_router(customers.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(dashboard.router)
app.include_router(molizhishu.router)
app.include_router(admin_media_dictionary.router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """SPA 兜底 —— React Router 的客户端路由(/login、/admin/* 等)都
    走这里回 index.html,让前端 router 接管。静态文件(/assets/*)由
    StaticFiles mount 在更早的位置匹配并服务,不会落到这里。"""
    del full_path  # path param 仅用于路由匹配,handler 不消费具体值
    if _FRONTEND_INDEX.is_file():
        return FileResponse(str(_FRONTEND_INDEX))
    return {"detail": "frontend dist not built"}
