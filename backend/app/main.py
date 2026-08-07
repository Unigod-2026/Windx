"""FastAPI application entry point.

Importing this module must be side-effect free: no engine is built, no
filesystem is touched, and no static directory is mounted. All of that
work happens inside the ``lifespan`` handler so the application only pays
for what it actually uses at runtime, and tests that import ``app.main``
don't need a writable logo directory or a live database.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import customers
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.mount(
        "/static",
        StaticFiles(directory=settings.logo_storage_dir, check_dir=False),
        name="static",
    )
    yield


app = FastAPI(title="windx-backend", lifespan=lifespan)
app.include_router(customers.router)


@app.get("/health")
def health():
    return {"ok": True}
