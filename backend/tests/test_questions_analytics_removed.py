"""Sentinel:确认旧 /questions/analytics endpoint 已删除。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import AdminUser, Customer, Project, ProjectPrompt
from app.models.project import BrandMention
from app.models.enums import ExtractStatus
from app.models.common import now_local
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

settings = get_settings()

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


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
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture()
def h(token):
    return {"Authorization": f"Bearer {token}"}


def _seed():
    now = now_local()
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code="acme")
        db.add(cust)
        db.commit()
        db.refresh(cust)
        proj = Project(customer_id=cust.id, name="P", code="P1", status="active", brand="Acme")
        db.add(proj)
        db.commit()
        db.refresh(proj)
        return proj.id


@pytest.mark.asyncio
async def test_old_analytics_endpoint_removed(client, h):
    pid = _seed()
    response = await client.get(
        f"/api/projects/{pid}/questions/analytics?days=15", headers=h
    )
    assert response.status_code == 404