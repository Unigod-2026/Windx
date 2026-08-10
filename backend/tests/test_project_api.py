"""Project CRUD + 4-tab config API tests.

Same in-process ASGI + in-memory SQLite setup as ``test_customer_api``.
The ``get_db`` override is (re)installed inside the autouse fixture rather
than only at import time, because sibling test modules clear/reassign
``app.dependency_overrides`` in their own teardown — a module-level
assignment alone would leave this file pointing at another file's engine.
"""

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
from app.models import AdminUser, Project, ProjectPrompt  # noqa: F401

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
        u = AdminUser(
            username="root", password_hash="x", role="super_admin", status="active"
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture()
def h(token):
    return {"Authorization": f"Bearer {token}"}


async def _customer(client, h, code="C1"):
    r = await client.post("/api/customers", json={"name": "C", "code": code}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _project(client, h, cid, code="P1"):
    r = await client.post(
        f"/api/customers/{cid}/projects", json={"name": "P", "code": code}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_crud_and_config_tabs(client, h):
    """The plan's Task 5 acceptance test, verbatim in intent."""
    cid = await _customer(client, h)

    r = await client.post(
        f"/api/customers/{cid}/projects", json={"name": "P", "code": "P1"}, headers=h
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = await client.put(f"/api/projects/{pid}/prompts", json={"prompts": ["q1", "q2"]}, headers=h)
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/projects/{pid}/keywords", json={"keywords": ["k1"]}, headers=h)
    assert r.status_code == 200, r.text
    r = await client.put(
        f"/api/projects/{pid}/platforms",
        json={"platforms": [{"platform": "deepseek", "mode": "search", "screenshot": 1}]},
        headers=h,
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["prompts"] == ["q1", "q2"]
    assert data["keywords"] == ["k1"]
    assert data["platforms"] == [
        {
            "id": data["platforms"][0]["id"],
            "platform": "deepseek",
            "mode": "search",
            "delivery_mode": "web",
            "thinking_mode": False,
            "screenshot": 1,
        }
    ]
    # 需求文档 §4 默认字段
    assert data["sentiment_enabled"] is False
    assert data["region_strategy"] == "fixed"
    assert data["region_codes"] is None


@pytest.mark.asyncio
async def test_create_project_requires_auth(client):
    r = await client.post("/api/customers/1/projects", json={"name": "P", "code": "P1"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_project_unknown_customer(client, h):
    r = await client.post(
        "/api/customers/9999/projects", json={"name": "P", "code": "P1"}, headers=h
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_project_code_unique_per_customer(client, h):
    c1 = await _customer(client, h, "C1")
    c2 = await _customer(client, h, "C2")

    await _project(client, h, c1, "SAME")
    # Duplicate within the same customer is rejected...
    r = await client.post(
        f"/api/customers/{c1}/projects", json={"name": "P", "code": "SAME"}, headers=h
    )
    assert r.status_code == 400
    # ...but the same code under a different customer is fine.
    r = await client.post(
        f"/api/customers/{c2}/projects", json={"name": "P", "code": "SAME"}, headers=h
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_create_project_with_initial_slots(client, h):
    """Spec §API: 创建项目(可含初始 schedule slots)."""
    cid = await _customer(client, h)
    r = await client.post(
        f"/api/customers/{cid}/projects",
        json={
            "name": "P",
            "code": "P1",
            "description": "d",
            "schedule_enabled": True,
            "slots": [{"hour": 9, "minute": 0}, {"hour": 18, "minute": 30}],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["schedule_enabled"] is True
    assert data["slots"] == [
        {"slot_index": 1, "hour": 9, "minute": 0},
        {"slot_index": 2, "hour": 18, "minute": 30},
    ]
    assert data["next_run_at"] is not None


@pytest.mark.asyncio
async def test_create_project_rejects_three_slots(client, h):
    cid = await _customer(client, h)
    r = await client.post(
        f"/api/customers/{cid}/projects",
        json={
            "name": "P",
            "code": "P1",
            "slots": [
                {"hour": 9, "minute": 0},
                {"hour": 12, "minute": 0},
                {"hour": 18, "minute": 0},
            ],
        },
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_filters_and_pagination(client, h):
    c1 = await _customer(client, h, "C1")
    c2 = await _customer(client, h, "C2")
    for i in range(3):
        await _project(client, h, c1, f"A{i}")
    await _project(client, h, c2, "B0")

    r = await client.get("/api/projects", headers=h)
    assert r.json()["total"] == 4

    r = await client.get(f"/api/projects?customer_id={c1}", headers=h)
    assert r.json()["total"] == 3

    r = await client.get(f"/api/projects?customer_id={c1}&page=1&size=2", headers=h)
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1 and body["size"] == 2

    r = await client.get("/api/projects?status=active", headers=h)
    assert r.json()["total"] == 4


@pytest.mark.asyncio
async def test_get_update_project(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)

    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "P"
    assert r.json()["prompts"] == []

    r = await client.put(
        f"/api/projects/{pid}", json={"name": "P2", "description": "hello"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "P2"
    assert r.json()["description"] == "hello"
    # code is immutable — not part of ProjectUpdate
    assert r.json()["code"] == "P1"


@pytest.mark.asyncio
async def test_get_project_404(client, h):
    r = await client.get("/api/projects/9999", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_project_is_soft_and_stops_schedule(client, h):
    """Spec §API 项目 DELETE 是软删除;§边界:软删除时调度应停用。"""
    cid = await _customer(client, h)
    r = await client.post(
        f"/api/customers/{cid}/projects",
        json={"name": "P", "code": "P1", "schedule_enabled": True,
              "slots": [{"hour": 9, "minute": 0}]},
        headers=h,
    )
    pid = r.json()["id"]

    r = await client.delete(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "disabled"
    assert r.json()["schedule_enabled"] is False
    assert r.json()["next_run_at"] is None


# --------------------------------------------------------------------------
# 4-tab config
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_put_is_full_replace_and_keeps_order(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)

    await client.put(f"/api/projects/{pid}/prompts", json={"prompts": ["a", "b", "c"]}, headers=h)
    r = await client.put(f"/api/projects/{pid}/prompts", json={"prompts": ["z", "y"]}, headers=h)
    assert r.json() == {"ok": True, "count": 2}

    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.json()["prompts"] == ["z", "y"]

    # Emptying a tab is allowed.
    await client.put(f"/api/projects/{pid}/keywords", json={"keywords": []}, headers=h)
    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.json()["keywords"] == []


@pytest.mark.asyncio
async def test_config_endpoints_404_for_unknown_project(client, h):
    for path, body in [
        ("prompts", {"prompts": []}),
        ("keywords", {"keywords": []}),
        ("platforms", {"platforms": []}),
    ]:
        r = await client.put(f"/api/projects/9999/{path}", json=body, headers=h)
        assert r.status_code == 404, path


@pytest.mark.asyncio
async def test_platforms_roundtrip_multiple(client, h):
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    payload = [
        {"platform": "deepseek", "mode": "search", "screenshot": 1},
        {"platform": "doubao", "mode": "chat", "screenshot": 0},
    ]
    r = await client.put(f"/api/projects/{pid}/platforms", json={"platforms": payload}, headers=h)
    assert r.json() == {"ok": True, "count": 2}
    r = await client.get(f"/api/projects/{pid}", headers=h)
    platforms = r.json()["platforms"]
    assert [p["platform"] for p in platforms] == ["deepseek", "doubao"]
    assert [p["screenshot"] for p in platforms] == [1, 0]
    assert [p["delivery_mode"] for p in platforms] == ["web", "web"]
    assert [p["thinking_mode"] for p in platforms] == [False, False]


@pytest.mark.asyncio
async def test_platforms_roundtrip_with_thinking_and_mobile(client, h):
    """需求文档 §3: each platform row carries delivery_mode + thinking_mode."""
    cid = await _customer(client, h)
    pid = await _project(client, h, cid)
    payload = [
        {
            "platform": "deepseek",
            "mode": "mobile",
            "delivery_mode": "mobile",
            "thinking_mode": True,
            "screenshot": 0,
        },
    ]
    r = await client.put(f"/api/projects/{pid}/platforms", json={"platforms": payload}, headers=h)
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.json()["platforms"][0]["delivery_mode"] == "mobile"
    assert r.json()["platforms"][0]["thinking_mode"] is True
