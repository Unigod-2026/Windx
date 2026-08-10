"""Global /api/tasks list API tests.

Same in-process ASGI + in-memory SQLite setup as ``test_customer_api``.
The autouse ``_setup_db`` fixture re-installs the ``get_db`` override so
sibling test modules that clear ``app.dependency_overrides`` cannot break
this file.

Auth: the plan defers real JWT issuance. We mint signed tokens whose
``sub`` claim is an ``AdminUser.id`` we just inserted; ``app.deps.get_current_user``
does the decode + lookup.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
# Importing the models package ensures every mapper is registered on
# ``Base.metadata`` before ``create_all`` runs.
from app.models import AdminUser, Customer, Project, Task  # noqa: F401

settings = get_settings()

# A dedicated engine so the override doesn't fight the (lazily-built)
# cached engine in app.db. StaticPool + a single shared connection is
# required so every new Session sees the same in-memory database.
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
    """Insert a super_admin and return a signed token whose sub is that user."""
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
def customer_admin_token(seed_tasks):
    """Insert a customer_admin bound to customer A and return a token.

    Depends on ``seed_tasks`` so the Customer row that ``customer_id`` points
    at already exists by the time we mint the token — and so we don't
    collide with seed_tasks' own UNIQUE ``code`` constraint on ``geo_customers``.
    """
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
def seed_tasks():
    """Create Customer A + Customer B, two projects, and 5 tasks distributed
    across them so the filter tests can target specific slices.

    Layout (after insertion):
      Customer A (id=1) -> Project P1 (id=1)
      Customer B (id=2) -> Project P2 (id=2)
      Tasks (newest first when ordered by id desc):
        T1 (customer=1, project=1, status="completed")
        T2 (customer=1, project=1, status="failed")
        T3 (customer=1, project=1, status="completed")
        T4 (customer=2, project=2, status="completed")
        T5 (customer=2, project=2, status="running")
    """
    with TestSessionLocal() as db:
        a = Customer(name="A", code="A")
        b = Customer(name="B", code="B")
        db.add_all([a, b])
        db.commit()
        db.refresh(a)
        db.refresh(b)

        p1 = Project(customer_id=a.id, name="P1", code="P1")
        p2 = Project(customer_id=b.id, name="P2", code="P2")
        db.add_all([p1, p2])
        db.commit()
        db.refresh(p1)
        db.refresh(p2)

        tasks = [
            Task(task_id="t-0001", status="completed", customer_id=a.id, project_id=p1.id,
                 total_items=3, completed_items=3, failed_items=0),
            Task(task_id="t-0002", status="failed", customer_id=a.id, project_id=p1.id,
                 total_items=2, completed_items=1, failed_items=1),
            Task(task_id="t-0003", status="completed", customer_id=a.id, project_id=p1.id,
                 total_items=4, completed_items=4, failed_items=0),
            Task(task_id="t-0004", status="completed", customer_id=b.id, project_id=p2.id,
                 total_items=2, completed_items=2, failed_items=0),
            Task(task_id="t-0005", status="running", customer_id=b.id, project_id=p2.id,
                 total_items=1, completed_items=0, failed_items=0),
        ]
        db.add_all(tasks)
        db.commit()


@pytest.mark.asyncio
async def test_requires_auth(client):
    r = await client.get("/api/tasks")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_tasks_paginates(client, super_admin_token, seed_tasks):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/tasks?page=2&size=2", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["size"] == 2
    assert len(body["items"]) == 2
    # Ordered by id desc -> page 2 is rows 3 and 4.
    assert [it["task_id"] for it in body["items"]] == ["t-0003", "t-0002"]


@pytest.mark.asyncio
async def test_filter_by_status(client, super_admin_token, seed_tasks):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/tasks?status=completed", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert all(it["status"] == "completed" for it in body["items"])


@pytest.mark.asyncio
async def test_filter_by_customer(client, super_admin_token, seed_tasks):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/tasks?customer_id=2", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert all(it["customer_id"] == 2 for it in body["items"])


@pytest.mark.asyncio
async def test_filter_by_project(client, super_admin_token, seed_tasks):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/tasks?project_id=2", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert all(it["project_id"] == 2 for it in body["items"])


@pytest.mark.asyncio
async def test_super_admin_sees_all_customers(client, super_admin_token, seed_tasks):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/tasks", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 5


@pytest.mark.asyncio
async def test_customer_admin_scoped_to_own_customer(
    client, customer_admin_token, seed_tasks
):
    h = {"Authorization": f"Bearer {customer_admin_token}"}
    # Default listing should only show customer A's 3 tasks.
    r = await client.get("/api/tasks", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert all(it["customer_id"] == 1 for it in body["items"])

    # Trying to override the scope by passing customer_id=2 must be ignored:
    # the filter clause only applies to super_admins.
    r2 = await client.get("/api/tasks?customer_id=2", headers=h)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["total"] == 3
    assert all(it["customer_id"] == 1 for it in body2["items"])


@pytest.mark.asyncio
async def test_size_capped_at_100(client, super_admin_token, seed_tasks):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/tasks?size=500", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size"] == 100
    # Only 5 rows exist, so the response has all of them, but the echoed
    # size reflects the clamped page size.
    assert len(body["items"]) == 5