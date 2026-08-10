"""Dashboard aggregate API tests.

Task 15 / spec §4.1. Same in-process ASGI + in-memory SQLite setup as
``test_tasks_api``. Auth via minted JWTs (``get_current_user`` decodes
``sub`` -> ``AdminUser.id``).

Seeding strategy:
- Each test seeds its own data with explicit ``triggered_at`` so the
  "today" / "yesterday" split is deterministic and doesn't depend on when
  the suite runs.
- Cooldown keys are not auto-generated; we set them to ``None`` on
  ``ScheduleRun`` so the unique constraint can't fire when we seed
  multiple rows for the same project/slot in the same 5-minute window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
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
    ProjectPlatform,
    ScheduleRun,
)
from app.models.common import now_local
from app.models.enums import ProjectStatus, RunStatus, RunTrigger

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


def _mint_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id)}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


@pytest.fixture()
def super_admin_token():
    with TestSessionLocal() as db:
        u = AdminUser(
            username="root", password_hash="x", role="super_admin", status="active"
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return _mint_token(uid)


@pytest.fixture()
def customer_admin_token(seed_two_customers):
    """customer_admin bound to customer A (created by ``seed_two_customers``)."""
    with TestSessionLocal() as db:
        a = db.scalar(select(Customer).where(Customer.code == "A"))
        u = AdminUser(
            username="alice",
            password_hash="x",
            role="customer_admin",
            status="active",
            customer_id=a.id,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return _mint_token(uid)


@pytest.fixture()
def seed_two_customers():
    """Customer A and Customer B with a project each."""
    with TestSessionLocal() as db:
        a = Customer(name="A", code="A")
        b = Customer(name="B", code="B")
        db.add_all([a, b])
        db.commit()
        db.refresh(a)
        db.refresh(b)
        pa = Project(customer_id=a.id, name="PA", code="PA", status=ProjectStatus.ACTIVE)
        pb = Project(customer_id=b.id, name="PB", code="PB", status=ProjectStatus.ACTIVE)
        db.add_all([pa, pb])
        db.commit()
        db.refresh(pa)
        db.refresh(pb)
        return {"a_id": a.id, "b_id": b.id, "pa_id": pa.id, "pb_id": pb.id}


def _add_run(
    project_id: int,
    status: RunStatus,
    triggered_at: datetime,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_message: str | None = None,
) -> None:
    with TestSessionLocal() as db:
        db.add(
            ScheduleRun(
                project_id=project_id,
                slot_index=1,
                trigger_type=RunTrigger.CRON,
                status=status,
                triggered_at=triggered_at,
                started_at=started_at,
                finished_at=finished_at,
                error_message=error_message,
                cooldown_key=None,
            )
        )
        db.commit()


# --------------------------------------------------------------------------
# Helpers required to silence the scheduler lifespan
# --------------------------------------------------------------------------


# Tasks tests didn't need this because the lifespan only runs on ``app``
# startup. We've imported ``app.main`` so the lifespan hook is set up; tests
# that hit the app via ``AsyncClient`` will trigger the lifespan, which is
# fine — there's no DB connection to break.


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client):
    r = await client.get("/api/dashboard")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_today_counts(client, super_admin_token, seed_two_customers):
    now = now_local()
    today_1h = now - timedelta(hours=1)
    today_2h = now - timedelta(hours=2)
    today_3h = now - timedelta(hours=3)
    yesterday = now - timedelta(days=1)

    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, today_1h)
    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, today_2h)
    _add_run(seed_two_customers["pa_id"], RunStatus.FAILED, today_3h)
    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, yesterday)

    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["today_runs"] == 3
    assert body["today_success"] == 2
    assert body["today_failed"] == 1


@pytest.mark.asyncio
async def test_dashboard_status_distribution(
    client, super_admin_token, seed_two_customers
):
    now = now_local()
    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, now - timedelta(minutes=10))
    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, now - timedelta(minutes=20))
    _add_run(seed_two_customers["pa_id"], RunStatus.FAILED, now - timedelta(minutes=30))
    _add_run(seed_two_customers["pa_id"], RunStatus.RUNNING, now - timedelta(minutes=40))
    _add_run(seed_two_customers["pa_id"], RunStatus.SKIPPED, now - timedelta(minutes=50))
    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, now - timedelta(days=1))

    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    dist = r.json()["status_distribution"]
    assert dist["success"] == 2
    assert dist["failed"] == 1
    assert dist["running"] == 1
    assert dist["skipped"] == 1
    assert dist["queued"] == 0


@pytest.mark.asyncio
async def test_dashboard_enabled_projects(
    client, super_admin_token, seed_two_customers
):
    with TestSessionLocal() as db:
        # 2 enabled projects + 1 disabled project for the same customer.
        db.add(
            Project(
                customer_id=seed_two_customers["a_id"],
                name="PA-enabled",
                code="PA-enabled",
                status=ProjectStatus.ACTIVE,
                schedule_enabled=True,
                slot1_hour=9,
                slot1_minute=0,
            )
        )
        db.add(
            Project(
                customer_id=seed_two_customers["a_id"],
                name="PA-disabled",
                code="PA-disabled",
                status=ProjectStatus.ACTIVE,
                schedule_enabled=False,
            )
        )
        db.commit()

    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    # The base seed (PA, PB) has no schedule_enabled, so only the new
    # "PA-enabled" counts. "PA-disabled" is excluded.
    assert r.json()["enabled_projects"] == 1


@pytest.mark.asyncio
async def test_dashboard_recent_runs_limit(client, super_admin_token, seed_two_customers):
    now = now_local()
    for i in range(15):
        _add_run(
            seed_two_customers["pa_id"],
            RunStatus.SUCCESS,
            now - timedelta(minutes=i),
        )

    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    recent = r.json()["recent_runs"]
    assert len(recent) == 10
    # newest first → ids 15..6 (we added 15 runs with descending age).
    assert [it["id"] for it in recent] == list(range(15, 5, -1))


@pytest.mark.asyncio
async def test_dashboard_customer_admin_scoped(
    client, customer_admin_token, seed_two_customers
):
    now = now_local()
    _add_run(seed_two_customers["pa_id"], RunStatus.SUCCESS, now - timedelta(minutes=10))
    _add_run(seed_two_customers["pa_id"], RunStatus.FAILED, now - timedelta(minutes=20))
    _add_run(seed_two_customers["pb_id"], RunStatus.SUCCESS, now - timedelta(minutes=30))
    _add_run(seed_two_customers["pb_id"], RunStatus.FAILED, now - timedelta(minutes=40))

    h = {"Authorization": f"Bearer {customer_admin_token}"}
    r = await client.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # Customer A only sees its own 2 runs.
    assert body["today_runs"] == 2
    assert body["today_success"] == 1
    assert body["today_failed"] == 1
    # Recent runs all belong to project A.
    assert all(it["project_id"] == seed_two_customers["pa_id"] for it in body["recent_runs"])


@pytest.mark.asyncio
async def test_dashboard_upcoming_orders_by_next_run_at(
    client, super_admin_token, seed_two_customers
):
    """Three enabled projects with different slot times; verify ordering."""
    now = now_local()
    # Choose three slots all guaranteed to be in the future today: every
    # project's first slot is at ``current_minute + N*10`` so the test is
    # deterministic regardless of the wall clock.
    base_minute = (now.minute + 5) % 60
    slot_a = {"hour": now.hour, "minute": base_minute}
    slot_b = {"hour": now.hour, "minute": (base_minute + 10) % 60}
    slot_c = {"hour": now.hour, "minute": (base_minute + 20) % 60}

    def _add(name, code, slot):
        with TestSessionLocal() as db:
            db.add(
                Project(
                    customer_id=seed_two_customers["a_id"],
                    name=name,
                    code=code,
                    status=ProjectStatus.ACTIVE,
                    schedule_enabled=True,
                    slot1_hour=slot["hour"],
                    slot1_minute=slot["minute"],
                )
            )
            db.commit()

    _add("P-first", "P-first", slot_a)
    _add("P-second", "P-second", slot_b)
    _add("P-third", "P-third", slot_c)

    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    upcoming = r.json()["upcoming"]
    assert len(upcoming) == 3
    when_list = [it["next_run_at"] for it in upcoming]
    assert when_list == sorted(when_list)
    assert upcoming[0]["project_name"] == "P-first"
    assert upcoming[1]["project_name"] == "P-second"
    assert upcoming[2]["project_name"] == "P-third"
    # Customer name is populated.
    assert all(it["customer_name"] for it in upcoming)
