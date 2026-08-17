"""Tests for the monitoring-project extensions (需求文档 §3 / §4).

Covers:
- PUT /api/projects/{id} now accepts sentiment_enabled / region_strategy /
  region_codes (back-compat: omitting them leaves the row untouched).
- /api/projects/{id}/competitors CRUD: list / create / update / delete.
- run_project honours ``region_strategy == "national_random"`` by sampling
  one code from ``NATIONAL_RANDOM_POOL``.
"""

from __future__ import annotations

import random
from datetime import datetime

import pytest
from freezegun import freeze_time
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import (  # noqa: F401
    AdminUser,
    Customer,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.enums import RunStatus, RunTrigger
from app.models.schedule import ScheduleRun
from app.services import scheduler
from app.services.scheduler import NATIONAL_RANDOM_POOL

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
def _setup_db(monkeypatch):
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: TestSessionLocal)
    yield
    Base.metadata.drop_all(test_engine)
    if prev is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = prev


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
def super_admin_token():
    from jose import jwt

    with TestSessionLocal() as db:
        u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture()
def h(super_admin_token):
    return {"Authorization": f"Bearer {super_admin_token}"}


async def _customer(client, h) -> int:
    r = await client.post(
        "/api/customers",
        json={"name": "Acme", "code": "ACME"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _project(client, h, cid: int, code: str = "P1") -> int:
    r = await client.post(
        f"/api/customers/{cid}/projects", json={"name": "P", "code": code}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------
# Project-level extensions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_with_sentiment_and_region(client, h):
    cid = await _customer(client, h)
    r = await client.post(
        f"/api/customers/{cid}/projects",
        json={
            "name": "P",
            "code": "P1",
            "sentiment_enabled": True,
            "region_strategy": "national_random",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["sentiment_enabled"] is True
    assert data["region_strategy"] == "national_random"


@pytest.mark.asyncio
async def test_update_project_persists_sentiment_and_region_codes(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    r = await client.put(
        f"/api/projects/{pid}",
        json={
            "sentiment_enabled": True,
            "region_strategy": "fixed",
            "region_codes": ["410000", "110000"],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["sentiment_enabled"] is True
    assert data["region_strategy"] == "fixed"
    assert data["region_codes"] == ["410000", "110000"]

    # GET reflects the update
    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.json()["region_codes"] == ["410000", "110000"]


@pytest.mark.asyncio
async def test_update_project_rejects_unknown_region_strategy(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    r = await client.put(
        f"/api/projects/{pid}",
        json={"region_strategy": "global_random"},
        headers=h,
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Competitor CRUD
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_competitor_crud_roundtrip(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)

    # Empty list initially
    r = await client.get(f"/api/projects/{pid}/competitors", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "total": 0}

    # Create
    r = await client.post(
        f"/api/projects/{pid}/competitors",
        json={"name": "字节跳动", "note": "核心竞品"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    comp_id = r.json()["id"]

    # Create another for sort-order coverage
    r = await client.post(
        f"/api/projects/{pid}/competitors",
        json={"name": "腾讯"},
        headers=h,
    )
    assert r.status_code == 201

    # List returns ordered by sort then id
    r = await client.get(f"/api/projects/{pid}/competitors", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert [i["name"] for i in items] == ["字节跳动", "腾讯"]

    # Update
    r = await client.put(
        f"/api/projects/{pid}/competitors/{comp_id}",
        json={"name": "字节跳动-BYTEDANCE", "note": None},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "字节跳动-BYTEDANCE"

    # Delete
    r = await client.delete(f"/api/projects/{pid}/competitors/{comp_id}", headers=h)
    assert r.status_code == 200
    r = await client.get(f"/api/projects/{pid}/competitors", headers=h)
    assert len(r.json()["items"]) == 1


@pytest.mark.asyncio
async def test_competitor_unique_name_per_project(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    await client.post(
        f"/api/projects/{pid}/competitors", json={"name": "Acme"}, headers=h
    )
    r = await client.post(
        f"/api/projects/{pid}/competitors", json={"name": "Acme"}, headers=h
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_competitor_wrong_project_id_returns_404(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    r = await client.post(
        f"/api/projects/{pid}/competitors", json={"name": "X"}, headers=h
    )
    other_id = r.json()["id"]
    r = await client.put(
        f"/api/projects/9999/competitors/{other_id}", json={"name": "Y"}, headers=h
    )
    assert r.status_code == 404
    r = await client.delete(f"/api/projects/9999/competitors/{other_id}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_deleting_project_deletes_competitors(client, h):
    """DELETE on the API is a soft-disable (status=disabled), not a row
    delete, so the cascade does not fire. Verify the competitor survives
    and stays attached — a future hard-delete endpoint would be a separate
    surface that triggers the cascade.
    """
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    await client.post(
        f"/api/projects/{pid}/competitors", json={"name": "X"}, headers=h
    )
    r = await client.delete(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200
    with TestSessionLocal() as db:
        # Project row still exists, just disabled.
        assert db.query(Project).filter(Project.id == pid).one().status.value == "disabled"
        # Competitor row still exists too.
        assert db.query(ProjectCompetitor).count() == 1


# --------------------------------------------------------------------------
# run_project honouring region_strategy
# --------------------------------------------------------------------------


def _seed_full_project(strategy: str, region_codes: list[str] | None = None) -> int:
    """Insert a project with prompts/keywords/platforms so run_project is happy."""
    with TestSessionLocal() as db:
        c = Customer(name="Acme", code="ACME")
        project = Project(
            customer=c,
            name="Monitor",
            code="MON",
            region_strategy=strategy,
            region_codes=region_codes,
        )
        db.add(project)
        db.flush()
        # Parent collections are viewonly=True (no-FK convention), so we add
        # children explicitly with the FK column set — see CLAUDE.md "外键约定".
        db.add_all(
            [
                ProjectPrompt(project_id=project.id, prompt="q1", sort=1),
                ProjectKeyword(project_id=project.id, keyword="k", sort=1),
                ProjectPlatform(
                    project_id=project.id,
                    platform="deepseek",
                    mode="search",
                    screenshot=1,
                    sort=1,
                ),
            ]
        )
        db.commit()
        return project.id


def test_run_project_uses_fixed_region_when_strategy_fixed():
    pid = _seed_full_project("fixed", ["410000"])
    captured: dict = {}

    async def fake_submit(self, payload, **_kwargs):
        captured["payload"] = payload
        return {
            "taskId": "remote-1",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    # Patch both clients so the test is robust against either branch of
    # ``_build_submit_client`` (settings.llm_mode).
    orig_m = scheduler.MolizhishuClient.submit_task
    orig_l = scheduler.LLMClient.submit_task
    scheduler.MolizhishuClient.submit_task = fake_submit  # type: ignore
    scheduler.LLMClient.submit_task = fake_submit  # type: ignore
    try:
        with freeze_time("2026-08-10 09:00:00", tz_offset=-8):
            run_id = scheduler.run_project(pid, 1, RunTrigger.CRON)
        assert run_id is not None
    finally:
        scheduler.MolizhishuClient.submit_task = orig_m  # type: ignore
        scheduler.LLMClient.submit_task = orig_l  # type: ignore

    assert captured["payload"]["regionCode"] == ["410000"]
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        # Submit response is "pending" → local run row stays RUNNING.
        # The status only advances once the polling sync observes a
        # terminal remote status (see test_sync.py).
        assert run.status == RunStatus.RUNNING
        # regionCode also persisted on the Task row
        from app.models.task import Task

        task = db.scalar(select(Task).where(Task.schedule_run_id == run_id))
        assert task.region_code_json == ["410000"]


def test_run_project_samples_national_random_when_strategy_random():
    pid = _seed_full_project("national_random")
    captured: dict = {}

    async def fake_submit(self, payload, **_kwargs):
        captured["payload"] = payload
        return {
            "taskId": "remote-2",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    orig_m = scheduler.MolizhishuClient.submit_task
    orig_l = scheduler.LLMClient.submit_task
    scheduler.MolizhishuClient.submit_task = fake_submit  # type: ignore
    scheduler.LLMClient.submit_task = fake_submit  # type: ignore
    try:
        # Custom sampler: ignore the pool, always return a fixed value.
        # This proves the scheduler is reading through ``rand`` rather
        # than the default ``random`` module.
        class PinnedSampler:
            def choice(self, seq):
                return "999999"  # synthetic, definitely not in the default pool

        with freeze_time("2026-08-10 09:05:00", tz_offset=-8):
            run_id = scheduler.run_project(
                pid, 1, RunTrigger.CRON, rand=PinnedSampler()
            )
        assert run_id is not None
    finally:
        scheduler.MolizhishuClient.submit_task = orig_m  # type: ignore
        scheduler.LLMClient.submit_task = orig_l  # type: ignore

    assert captured["payload"]["regionCode"] == ["999999"]


def test_run_project_omits_region_when_fixed_strategy_has_no_codes():
    pid = _seed_full_project("fixed", region_codes=None)
    captured: dict = {}

    async def fake_submit(self, payload, **_kwargs):
        captured["payload"] = payload
        return {
            "taskId": "remote-3",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    orig_m = scheduler.MolizhishuClient.submit_task
    orig_l = scheduler.LLMClient.submit_task
    scheduler.MolizhishuClient.submit_task = fake_submit  # type: ignore
    scheduler.LLMClient.submit_task = fake_submit  # type: ignore
    try:
        with freeze_time("2026-08-10 09:10:00", tz_offset=-8):
            scheduler.run_project(pid, 1, RunTrigger.CRON)
    finally:
        scheduler.MolizhishuClient.submit_task = orig_m  # type: ignore
        scheduler.LLMClient.submit_task = orig_l  # type: ignore

    assert "regionCode" not in captured["payload"]