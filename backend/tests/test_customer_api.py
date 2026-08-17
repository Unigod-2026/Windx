"""Customer CRUD + logo upload API tests.

In-process ASGI + in-memory SQLite setup; logo uploads are redirected to
a per-test tmp dir so the test never tries to write under ``/data/logos``.

Auth: we mint a signed token whose ``sub`` claim is an ``AdminUser.id`` we
just inserted; ``app.deps.get_current_user`` does the decode + lookup and
``require_super_admin`` checks the role.
"""

from __future__ import annotations

import io

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
def _setup_db(monkeypatch, tmp_path):
    # Redirect logo storage into a per-test tmp dir so we don't try to
    # create /data/logos on a developer laptop.
    monkeypatch.setenv("LOGO_STORAGE_DIR", str(tmp_path / "logos"))
    settings.logo_storage_dir = str(tmp_path / "logos")
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
    """Insert a super_admin and return a signed token whose sub is that user."""
    with TestSessionLocal() as db:
        u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_create_customer(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.post(
        "/api/customers",
        json={"name": "Acme", "code": "ACME", "contact": "alice@acme.com"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Acme"
    assert data["code"] == "ACME"
    assert data["status"] == "active"
    assert data["logo_url"] is None


@pytest.mark.asyncio
async def test_create_customer_requires_auth(client):
    r = await client.post("/api/customers", json={"name": "A", "code": "A"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_customer_duplicate_code(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r1 = await client.post("/api/customers", json={"name": "A", "code": "DUP"}, headers=h)
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/api/customers", json={"name": "B", "code": "DUP"}, headers=h)
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_upload_logo_png(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    create = await client.post("/api/customers", json={"name": "L", "code": "LOGO"}, headers=h)
    cid = create.json()["id"]
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    files = {"file": ("logo.png", io.BytesIO(png_bytes), "image/png")}
    r = await client.post(f"/api/customers/{cid}/logo", files=files, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["logo_path"].startswith("logos/")
    assert body["logo_path"].endswith(f"{cid}.png")
    assert body["logo_url"] == f"/static/{body['logo_path']}"


@pytest.mark.asyncio
async def test_upload_logo_rejects_unsupported_type(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    create = await client.post("/api/customers", json={"name": "B", "code": "BAD"}, headers=h)
    cid = create.json()["id"]
    files = {"file": ("logo.gif", io.BytesIO(b"GIF89a"), "image/gif")}
    r = await client.post(f"/api/customers/{cid}/logo", files=files, headers=h)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_logo_rejects_oversize(client, super_admin_token, tmp_path, monkeypatch):
    """A 3MB upload must be rejected even though the Settings default is 2MB."""
    h = {"Authorization": f"Bearer {super_admin_token}"}
    create = await client.post("/api/customers", json={"name": "S", "code": "SIZE"}, headers=h)
    cid = create.json()["id"]
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (3 * 1024 * 1024)
    files = {"file": ("logo.png", io.BytesIO(big), "image/png")}
    r = await client.post(f"/api/customers/{cid}/logo", files=files, headers=h)
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_get_customer(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    r = await client.post("/api/customers", json={"name": "G", "code": "GET"}, headers=h)
    cid = r.json()["id"]
    g = await client.get(f"/api/customers/{cid}", headers=h)
    assert g.status_code == 200
    assert g.json()["code"] == "GET"


@pytest.mark.asyncio
async def test_update_customer(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    cid = (await client.post("/api/customers", json={"name": "U", "code": "UPD"}, headers=h)).json()["id"]
    r = await client.put(f"/api/customers/{cid}", json={"contact": "u@x.com"}, headers=h)
    assert r.status_code == 200
    assert r.json()["contact"] == "u@x.com"


@pytest.mark.asyncio
async def test_list_customers(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    await client.post("/api/customers", json={"name": "L1", "code": "L1"}, headers=h)
    await client.post("/api/customers", json={"name": "L2", "code": "L2"}, headers=h)
    r = await client.get("/api/customers?page=1&size=10", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_delete_customer_blocks_when_projects_exist(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    cid = (await client.post("/api/customers", json={"name": "P", "code": "WITH-PROJ"}, headers=h)).json()["id"]
    # Insert a project directly via the model layer (no project API yet).
    from app.models.project import Project
    with TestSessionLocal() as db:
        db.add(Project(customer_id=cid, name="proj", code="proj"))
        db.commit()
    r = await client.delete(f"/api/customers/{cid}", headers=h)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_customer_soft_disables(client, super_admin_token):
    """Per spec §5: DELETE is a soft-disable, not a hard delete."""
    h = {"Authorization": f"Bearer {super_admin_token}"}
    cid = (await client.post("/api/customers", json={"name": "D", "code": "DEL"}, headers=h)).json()["id"]
    r = await client.delete(f"/api/customers/{cid}", headers=h)
    assert r.status_code == 200
    # Row still exists but status flipped to disabled.
    g = await client.get(f"/api/customers/{cid}", headers=h)
    assert g.status_code == 200
    assert g.json()["status"] == "disabled"