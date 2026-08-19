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


def _seed_subtask(db, project_id, customer_id, *, platform, day, refs):
    """Seed a Task+Subtask pair at a specific calendar day, with a
    reference_list_json payload. ``refs`` is a list of dicts
    {"url", "site", "title"}. The Subtask's created_at and the Task's
    created_local_at are both backdated to ``day`` so windowing works.
    """
    from datetime import datetime, time
    from app.models.task import Task, Subtask
    suffix = f"{platform}-{day.isoformat()}-{refs[0]['url'] if refs else 'empty'}"
    task = Task(
        project_id=project_id, customer_id=customer_id,
        task_id=f"task-{suffix}", status="success",
    )
    db.add(task); db.flush()
    sub = Subtask(
        task_id=task.task_id, subtask_id=f"sub-{suffix}",
        platform=platform, status="success",
        reference_list_json=refs,
    )
    db.add(sub); db.flush()
    sub.created_at = datetime.combine(day, time.min)
    task.created_local_at = datetime.combine(day, time.min)
    return sub


async def test_empty_window_returns_zeros(client, h):
    """没有任何 subtask → kpi 全 0,所有 list 都空,200。"""
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-empty", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpi"]["total_references"] == 0
    assert body["kpi"]["unique_urls"] == 0
    assert body["kpi"]["cross_platform_urls"] == 0
    assert body["kpi"]["avg_refs_per_subtask"] == 0.0
    assert body["kpi"]["total_subtasks"] == 0
    assert body["type_counts"] == []
    assert body["platform_slices"] == []
    assert body["top_sources"] == []
    assert body["trend"] == []


async def test_kpi_basic_aggregation(client, h):
    """1 个 subtask / 3 条 URL / 1 个 platform → total=3, unique=3,
    cross_platform=0, avg=3.0, total_subtasks=1。"""
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-kpi"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-kpi", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        _seed_subtask(db, pid, cust.id, platform="doubao", day=today, refs=[
            {"url": "https://a.com/", "site": "a.com", "title": "A"},
            {"url": "https://b.com/", "site": "b.com", "title": "B"},
            {"url": "https://c.com/", "site": "c.com", "title": "C"},
        ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    kpi = r.json()["kpi"]
    assert kpi["total_references"] == 3
    assert kpi["unique_urls"] == 3
    assert kpi["cross_platform_urls"] == 0
    assert kpi["avg_refs_per_subtask"] == 3.0
    assert kpi["total_subtasks"] == 1


async def test_kpi_cross_platform_url(client, h):
    """同一 URL 被 2 个不同 platform 的 subtask 引用 → cross_platform_urls=1。"""
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-xp"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-xp", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        for plat in ("doubao", "kimi"):
            _seed_subtask(db, pid, cust.id, platform=plat, day=today, refs=[
                {"url": "https://shared.com/", "site": "shared.com", "title": "Shared"},
                {"url": f"https://{plat}-only.com/", "site": f"{plat}-only.com", "title": f"{plat} only"},
            ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    kpi = r.json()["kpi"]
    # 2 个 subtask,每个 2 条 = total=4, unique=3(shared + 2 个 plat-only),
    # cross_platform=1(shared.com), avg=2.0
    assert kpi["total_references"] == 4
    assert kpi["unique_urls"] == 3
    assert kpi["cross_platform_urls"] == 1
    assert kpi["avg_refs_per_subtask"] == 2.0
    assert kpi["total_subtasks"] == 2
    # platform_slices:每个 platform 一行
    platform_slices = {p["platform"]: p for p in r.json()["platform_slices"]}
    assert platform_slices["doubao"]["total_refs"] == 2
    assert platform_slices["doubao"]["unique_urls"] == 2
    assert platform_slices["kimi"]["total_refs"] == 2
    assert platform_slices["kimi"]["unique_urls"] == 2
