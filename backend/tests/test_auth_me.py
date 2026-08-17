"""``GET /api/auth/me`` tests.

The token ``sub`` is the AdminUser id we insert; ``app.deps.get_current_user``
does the decode + lookup. We assert role/customer_id/status come back as
plain strings so the React frontend can use them without parsing enums.
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
from app.models import AdminUser, Customer  # noqa: F401

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
def super_admin_token():
    """Insert an active super_admin and return a signed token."""
    with TestSessionLocal() as db:
        u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture()
def customer_admin_token():
    """Insert a customer_admin scoped to a customer and return (token, customer_id)."""
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code="ACME")
        db.add(cust)
        db.commit()
        db.refresh(cust)
        u = AdminUser(
            username="alice",
            password_hash="x",
            display_name="Alice",
            role="customer_admin",
            status="active",
            customer_id=cust.id,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        uid, cid = u.id, cust.id
    return (
        jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm),
        cid,
    )


@pytest.mark.asyncio
async def test_me_returns_role_and_customer_id_for_super_admin(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["role"] == "super_admin"
    assert data["customer_id"] is None
    assert data["status"] == "active"
    assert data["username"] == "root"


@pytest.mark.asyncio
async def test_me_returns_role_and_customer_id_for_customer_admin(client, customer_admin_token):
    token, cid = customer_admin_token
    h = {"Authorization": f"Bearer {token}"}
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["role"] == "customer_admin"
    assert data["customer_id"] == cid
    assert data["status"] == "active"
    assert data["username"] == "alice"
    assert data["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    r = await client.get("/api/auth/me")
    # FastAPI's HTTPBearer (auto_error=True) returns 403 when no header is
    # present; downstream auth checks return 401. Accept either.
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_returns_401_for_invalid_token(client):
    h = {"Authorization": "Bearer not-a-real-jwt"}
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_403_or_401_for_disabled_user(client):
    """A disabled user still has a valid JWT, but ``/me`` rejects them so
    the frontend can force-logout on its first authenticated call."""
    with TestSessionLocal() as db:
        u = AdminUser(username="doomed", password_hash="x", role="super_admin", status="disabled")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    token = jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    h = {"Authorization": f"Bearer {token}"}
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code in (401, 403)