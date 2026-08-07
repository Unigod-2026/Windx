from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="windx-backend", lifespan=lifespan)
settings = get_settings()
app.mount("/static", StaticFiles(directory=settings.logo_storage_dir, check_dir=False), name="static")


@app.get("/health")
def health():
    return {"ok": True}
