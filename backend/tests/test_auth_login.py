"""``POST /api/auth/login`` tests.

We use ``app.services.password.hash_password`` so the stored hash matches
what the endpoint verifies with — verifying against a hand-written bcrypt
hash would work too but couples the tests to the salt format.
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
from app.services.password import hash_password

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
def seeded_admin():
    """Insert an active super_admin with a known password and return the row."""
    with TestSessionLocal() as db:
        u = AdminUser(
            username="admin",
            password_hash=hash_password("s3cret"),
            display_name="超级管理员",
            role="super_admin",
            status="active",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u.id


@pytest.fixture()
def disabled_admin():
    with TestSessionLocal() as db:
        u = AdminUser(
            username="doomed",
            password_hash=hash_password("s3cret"),
            role="super_admin",
            status="disabled",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u.id


def _decode_sub(token: str) -> str:
    return jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )["sub"]


@pytest.mark.asyncio
async def test_login_success_returns_token_and_user(client, seeded_admin):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "s3cret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert _decode_sub(body["token"]) == str(seeded_admin)
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "super_admin"
    assert body["user"]["customer_id"] is None
    assert body["user"]["status"] == "active"


@pytest.mark.asyncio
async def test_login_records_last_login_at(client, seeded_admin):
    r = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "s3cret"}
    )
    assert r.status_code == 200, r.text
    # The login handler commits ``last_login_at`` via its own session; end
    # the test session's open transaction and expire the cached row so the
    # next read picks up the API's update.
    with TestSessionLocal() as db:
        db.expire_all()
        u = db.get(AdminUser, seeded_admin)
        assert u.last_login_at is not None


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client, seeded_admin):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_unknown_username_returns_same_401(client):
    """Unknown username must produce the same error as a wrong password to
    avoid leaking which usernames exist."""
    r = await client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_disabled_admin_returns_403(client, disabled_admin):
    """A disabled account has a valid password but must be rejected with 403
    so the frontend can show "账号已停用" instead of "密码错误"."""
    r = await client.post(
        "/api/auth/login", json={"username": "doomed", "password": "s3cret"}
    )
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_missing_fields_returns_422(client):
    r = await client.post("/api/auth/login", json={"username": "admin"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_login_password_over_72_bytes_rejected(client):
    """Bcrypt's 72-byte cap is enforced at the schema layer; the request
    never reaches the verifier with an overlong password."""
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "x" * 73},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_login_issued_token_works_on_me(client, seeded_admin):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "s3cret"})
    token = r.json()["token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"