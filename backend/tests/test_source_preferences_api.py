"""Tests for GET /api/projects/{id}/source-preferences endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import AdminUser

settings = get_settings()

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(
    bind=test_engine, autoflush=False, autocommit=False, future=True
)


def override_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup_db():
    app.dependency_overrides[get_db] = override_db
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
def token():
    with TestSessionLocal() as db:
        u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
        db.add(u); db.commit(); db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture()
def h(token):
    return {"Authorization": f"Bearer {token}"}


def test_source_preference_out_has_required_fields():
    from app.schemas.project import (
        SourcePreferenceKpi, SourceTypeSlice, SourcePlatformSlice,
        SourceTrendDay, SourcePreferenceItem, SourcePreferenceOut,
    )
    assert set(SourcePreferenceKpi.model_fields.keys()) >= {
        "total_references", "unique_urls", "cross_platform_urls",
        "avg_refs_per_subtask", "total_subtasks",
    }
    assert set(SourceTypeSlice.model_fields.keys()) == {"type", "count"}
    assert set(SourcePlatformSlice.model_fields.keys()) == {"platform", "total_refs", "unique_urls"}
    assert set(SourceTrendDay.model_fields.keys()) == {"date", "new_urls", "lost_urls"}
    assert set(SourcePreferenceItem.model_fields.keys()) == {
        "url", "site", "title", "type", "count", "platforms", "first_seen", "last_seen",
    }
    assert set(SourcePreferenceOut.model_fields.keys()) == {
        "project_id", "start", "end", "days",
        "kpi", "type_counts", "platform_slices", "top_sources", "trend",
    }
