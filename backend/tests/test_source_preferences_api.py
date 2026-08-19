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


async def test_top_sources_limit_50(client, h):
    """seed 60 个不同 URL → top_sources 长度 == 50,按 count desc 排序。"""
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-top"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-top", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        refs = [
            {"url": f"https://u{i:02d}.com/", "site": f"u{i:02d}.com", "title": f"U{i}"}
            for i in range(60)
        ]
        _seed_subtask(db, pid, cust.id, platform="doubao", day=today, refs=refs)
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    top = r.json()["top_sources"]
    assert len(top) == 50
    counts = [it["count"] for it in top]
    assert counts == sorted(counts, reverse=True)


async def test_trend_set_diff(client, h):
    """day1: {A,B}, day2: {A,B,C}, day3: {A,C} → trend 3 个 day。
    day1: new=2(A,B 全新)/lost=0(无前日)
    day2: new=1(C)/lost=0
    day3: new=0 / lost=1(B 流失)"""
    from app.models import Customer, Project
    from app.models.common import now_local
    from datetime import timedelta

    today = now_local().date()
    d1 = today - timedelta(days=2)
    d2 = today - timedelta(days=1)
    d3 = today
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-trend"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-trend", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        for d, urls in [
            (d1, ["https://a.com/", "https://b.com/"]),
            (d2, ["https://a.com/", "https://b.com/", "https://c.com/"]),
            (d3, ["https://a.com/", "https://c.com/"]),
        ]:
            _seed_subtask(db, pid, cust.id, platform="doubao", day=d, refs=[
                {"url": u, "site": u.split("://")[1].rstrip("/"), "title": u} for u in urls
            ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    trend = {t["date"]: t for t in r.json()["trend"]}
    assert trend[d1.isoformat()]["new_urls"] == 2
    assert trend[d1.isoformat()]["lost_urls"] == 0
    assert trend[d2.isoformat()]["new_urls"] == 1
    assert trend[d2.isoformat()]["lost_urls"] == 0
    assert trend[d3.isoformat()]["new_urls"] == 0
    assert trend[d3.isoformat()]["lost_urls"] == 1


async def test_window_excludes_out_of_range_subtasks(client, h):
    """task.created_local_at 在窗口外的 subtask 不计入(等同 citation-analysis)。"""
    from datetime import timedelta
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    out_of_range = today - timedelta(days=30)  # days=15 窗口外
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-win"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-win", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        _seed_subtask(db, pid, cust.id, platform="doubao", day=out_of_range, refs=[
            {"url": "https://outside.com/", "site": "outside.com", "title": "Outside"},
        ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    body = r.json()
    assert body["kpi"]["total_references"] == 0
    assert body["kpi"]["total_subtasks"] == 0


async def test_invalid_days_returns_400(client, h):
    """days=0 / days=91 → HTTP 400。"""
    from app.models import Customer, Project
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-400"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-400", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        db.commit()

    for bad in (0, 91, -1):
        r = await client.get(f"/api/projects/{pid}/source-preferences?days={bad}", headers=h)
        assert r.status_code == 400, f"days={bad} should be 400, got {r.status_code}"
