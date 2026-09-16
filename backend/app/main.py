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
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

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


# 前端静态 + SPA 兜底 —— 只用一条 catch-all,handler 里手判:
#   1. ``frontend_dist/<full_path>`` 是真实文件 → FileResponse(原内容)
#   2. 否则 → FileResponse(index.html),让 React Router 接管
# 不用 StaticFiles mount 是因为 Starlette Mount 一旦路径前缀命中就
# 把请求吃掉、不会再 fallback 到后面的 catch-all;mount + 手动 catch-all
# 的组合会让 /login 这种 SPA 路径被 StaticFiles 截胡返回 404,而不是
# index.html(在 Starlette 1.4 上无法简单修)。
async def _serve_frontend(request):
    raw_path = request.url.path.lstrip("/")
    target = (_FRONTEND_DIST / raw_path).resolve()
    # 防 path traversal —— 解析后必须在 _FRONTEND_DIST 之下
    try:
        target.relative_to(_FRONTEND_DIST.resolve())
    except ValueError:
        target = _FRONTEND_INDEX
    if target.is_file():
        return FileResponse(str(target))
    if _FRONTEND_INDEX.is_file():
        return FileResponse(str(_FRONTEND_INDEX))
    return PlainTextResponse("frontend dist not built", status_code=500)


# 直接往 Starlette router 追加 Route 对象 —— app.add_route 在 FastAPI
# 路径解析里把 endpoint 当 FastAPI handler 处理(只传 request,不会传
# scope/receive/send),所以 raw ASGI 必须用 Starlette Route。
app.router.routes.append(
    Route(
        "/{full_path:path}",
        _serve_frontend,
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
)

