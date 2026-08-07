"""Integration tests for the FastAPI app entry point using httpx AsyncClient."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    """GET /health returns 200 with body {"ok": True}."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_app_title() -> None:
    """The FastAPI app is titled 'windx-backend'."""
    assert app.title == "windx-backend"
