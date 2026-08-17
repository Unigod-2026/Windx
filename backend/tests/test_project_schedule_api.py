"""Project schedule / runs / tasks API tests (plan Appendix A.2).

In v2 there is no standalone schedule entity: the schedule lives on the
project row, so every endpoint here is namespaced under
``/api/projects/{id}``. ``ScheduleRun`` rows are keyed by ``project_id``
and de-duplicated by ``cooldown_key``.
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
from app.models import AdminUser, ScheduleRun, Task  # noqa: F401
from app.models.common import now_local

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
def h():
    with TestSessionLocal() as db:
        u = AdminUser(
            username="root", password_hash="x", role="super_admin", status="active"
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    tok = jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
async def project(client, h):
    """A configured, schedulable project (prompts + platforms present)."""
    cid = (await client.post("/api/customers", json={"name": "C", "code": "C1"}, headers=h)).json()["id"]
    pid = (
        await client.post(
            f"/api/customers/{cid}/projects", json={"name": "P", "code": "P1"}, headers=h
        )
    ).json()["id"]
    await client.put(
        f"/api/projects/{pid}/prompts",
        json={"prompts": [{"prompt": "q1"}]},
        headers=h,
    )
    await client.put(
        f"/api/projects/{pid}/platforms",
        json={"platforms": [{"platform": "deepseek", "mode": "search", "screenshot": 0}]},
        headers=h,
    )
    return pid


# --------------------------------------------------------------------------
# GET / PUT / DELETE /api/projects/{id}/schedule
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schedule_defaults_to_unscheduled(client, h, project):
    r = await client.get(f"/api/projects/{project}/schedule", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["schedule_enabled"] is False
    assert data["slots"] == []
    assert data["next_run_at"] is None
    assert data["last_run"] is None


@pytest.mark.asyncio
async def test_put_schedule_sets_slots_and_enabled(client, h, project):
    r = await client.put(
        f"/api/projects/{project}/schedule",
        json={"schedule_enabled": True, "slots": [{"hour": 9, "minute": 5}, {"hour": 21, "minute": 0}]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["schedule_enabled"] is True
    assert data["slots"] == [
        {"slot_index": 1, "hour": 9, "minute": 5},
        {"slot_index": 2, "hour": 21, "minute": 0},
    ]

    # Shrinking 2 slots -> 1 clears slot2.
    r = await client.put(
        f"/api/projects/{project}/schedule",
        json={"schedule_enabled": True, "slots": [{"hour": 7, "minute": 0}]},
        headers=h,
    )
    assert r.json()["slots"] == [{"slot_index": 1, "hour": 7, "minute": 0}]


@pytest.mark.asyncio
async def test_put_schedule_rejects_three_slots(client, h, project):
    r = await client.put(
        f"/api/projects/{project}/schedule",
        json={
            "schedule_enabled": True,
            "slots": [{"hour": 1, "minute": 0}, {"hour": 2, "minute": 0}, {"hour": 3, "minute": 0}],
        },
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("hour,minute", [(24, 0), (-1, 0), (0, 60), (0, -1)])
async def test_put_schedule_rejects_bad_time(client, h, project, hour, minute):
    r = await client.put(
        f"/api/projects/{project}/schedule",
        json={"schedule_enabled": True, "slots": [{"hour": hour, "minute": minute}]},
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_enabling_schedule_without_slots_is_rejected(client, h, project):
    r = await client.put(
        f"/api/projects/{project}/schedule",
        json={"schedule_enabled": True, "slots": []},
        headers=h,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_schedule_resets_to_unscheduled(client, h, project):
    await client.put(
        f"/api/projects/{project}/schedule",
        json={"schedule_enabled": True, "slots": [{"hour": 9, "minute": 0}]},
        headers=h,
    )
    r = await client.delete(f"/api/projects/{project}/schedule", headers=h)
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/projects/{project}/schedule", headers=h)
    data = r.json()
    assert data["schedule_enabled"] is False
    assert data["slots"] == []
    assert data["next_run_at"] is None


@pytest.mark.asyncio
async def test_schedule_endpoints_404(client, h):
    assert (await client.get("/api/projects/9999/schedule", headers=h)).status_code == 404
    assert (await client.delete("/api/projects/9999/schedule", headers=h)).status_code == 404
    r = await client.put(
        "/api/projects/9999/schedule",
        json={"schedule_enabled": False, "slots": []},
        headers=h,
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# PUT /api/projects/{id}/schedule/status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_status_toggle(client, h, project):
    await client.put(
        f"/api/projects/{project}/schedule",
        json={"schedule_enabled": True, "slots": [{"hour": 9, "minute": 0}]},
        headers=h,
    )

    r = await client.put(
        f"/api/projects/{project}/schedule/status", json={"status": "disabled"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["schedule_enabled"] is False
    # Slots survive a disable so re-enabling restores the same times.
    assert r.json()["slots"] == [{"slot_index": 1, "hour": 9, "minute": 0}]

    r = await client.put(
        f"/api/projects/{project}/schedule/status", json={"status": "enabled"}, headers=h
    )
    assert r.json()["schedule_enabled"] is True


@pytest.mark.asyncio
async def test_schedule_status_rejects_enable_without_slots(client, h, project):
    r = await client.put(
        f"/api/projects/{project}/schedule/status", json={"status": "enabled"}, headers=h
    )
    assert r.status_code == 400
    assert "调度时间槽" in r.json()["detail"]


@pytest.mark.asyncio
async def test_schedule_status_rejects_bad_value(client, h, project):
    r = await client.put(
        f"/api/projects/{project}/schedule/status", json={"status": "on"}, headers=h
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# POST /api/projects/{id}/schedule/trigger
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_creates_queued_run(client, h, project, monkeypatch):
    # The endpoint queues a ScheduleRun and fires ``run_project_async`` as a
    # background task. The runner talks to the remote API (and to the prod
    # ``get_session_factory``, which here points at MySQL while the test
    # override routes through SQLite); stub it out so the test stays
    # local and doesn't try to read a row from a different engine.
    async def fake_run_project_async(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.api.projects.run_project_async", fake_run_project_async
    )

    r = await client.post(f"/api/projects/{project}/schedule/trigger", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] > 0
    assert body["status"] == "queued"

    r = await client.get(f"/api/projects/runs/{body['run_id']}", headers=h)
    run = r.json()
    assert run["project_id"] == project
    assert run["slot_index"] == 0  # manual trigger uses slot 0 in v2
    assert run["trigger_type"] == "manual"
    assert run["status"] == "queued"


@pytest.mark.asyncio
async def test_trigger_is_cooldown_deduped(client, h, project, monkeypatch):
    """Second trigger inside the same 5-minute bucket is skipped, not duplicated."""
    async def fake_run_project_async(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.api.projects.run_project_async", fake_run_project_async
    )

    first = (await client.post(f"/api/projects/{project}/schedule/trigger", headers=h)).json()
    second = (await client.post(f"/api/projects/{project}/schedule/trigger", headers=h)).json()

    assert second["status"] == "skipped"
    assert second["run_id"] == first["run_id"]

    r = await client.get(f"/api/projects/{project}/runs", headers=h)
    assert r.json()["total"] == 1


@pytest.mark.asyncio
async def test_trigger_requires_configured_project(client, h):
    """A project with no prompts has nothing to submit."""
    cid = (await client.post("/api/customers", json={"name": "C", "code": "C9"}, headers=h)).json()["id"]
    pid = (
        await client.post(
            f"/api/customers/{cid}/projects", json={"name": "P", "code": "P9"}, headers=h
        )
    ).json()["id"]
    r = await client.post(f"/api/projects/{pid}/schedule/trigger", headers=h)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_trigger_404(client, h):
    r = await client.post("/api/projects/9999/schedule/trigger", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_trigger_requires_auth(client, project):
    r = await client.post(f"/api/projects/{project}/schedule/trigger")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# GET /api/projects/{id}/runs  &  /api/projects/runs/{run_id}
# --------------------------------------------------------------------------


def _seed_runs(project_id: int, n: int, status: str = "success"):
    with TestSessionLocal() as db:
        for i in range(n):
            db.add(
                ScheduleRun(
                    project_id=project_id,
                    slot_index=1,
                    trigger_type="cron",
                    triggered_at=now_local(),
                    status=status,
                    cooldown_key=f"project-{project_id}-slot-1-seed{status}{i}",
                )
            )
        db.commit()


@pytest.mark.asyncio
async def test_runs_pagination_and_status_filter(client, h, project):
    _seed_runs(project, 3, "success")
    _seed_runs(project, 2, "failed")

    r = await client.get(f"/api/projects/{project}/runs", headers=h)
    assert r.json()["total"] == 5

    r = await client.get(f"/api/projects/{project}/runs?status=failed", headers=h)
    body = r.json()
    assert body["total"] == 2
    assert all(i["status"] == "failed" for i in body["items"])

    r = await client.get(f"/api/projects/{project}/runs?page=2&size=2", headers=h)
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["page"] == 2

    # Newest first.
    r = await client.get(f"/api/projects/{project}/runs", headers=h)
    ids = [i["id"] for i in r.json()["items"]]
    assert ids == sorted(ids, reverse=True)


@pytest.mark.asyncio
async def test_runs_scoped_to_project(client, h, project):
    other = (
        await client.post(
            f"/api/customers/1/projects", json={"name": "P2", "code": "P2"}, headers=h
        )
    ).json()["id"]
    _seed_runs(project, 2)
    _seed_runs(other, 3)

    assert (await client.get(f"/api/projects/{project}/runs", headers=h)).json()["total"] == 2
    assert (await client.get(f"/api/projects/{other}/runs", headers=h)).json()["total"] == 3


@pytest.mark.asyncio
async def test_runs_list_404_for_unknown_project(client, h):
    r = await client.get("/api/projects/9999/runs", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_run_detail_404(client, h):
    r = await client.get("/api/projects/runs/9999", headers=h)
    assert r.status_code == 404


# --------------------------------------------------------------------------
# GET /api/projects/{id}/tasks
# --------------------------------------------------------------------------


def _seed_task(project_id: int, task_id: str, status: str = "completed"):
    with TestSessionLocal() as db:
        db.add(Task(task_id=task_id, status=status, project_id=project_id))
        db.commit()


@pytest.mark.asyncio
async def test_project_tasks_list(client, h, project):
    _seed_task(project, "t1", "completed")
    _seed_task(project, "t2", "running")

    r = await client.get(f"/api/projects/{project}/tasks", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert {i["task_id"] for i in body["items"]} == {"t1", "t2"}

    r = await client.get(f"/api/projects/{project}/tasks?status=running", headers=h)
    assert r.json()["total"] == 1


@pytest.mark.asyncio
async def test_project_tasks_404(client, h):
    r = await client.get("/api/projects/9999/tasks", headers=h)
    assert r.status_code == 404
