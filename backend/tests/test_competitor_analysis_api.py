"""Tests for GET /api/projects/{id}/competitor-analysis endpoint."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import (
    AdminUser,
    Customer,
    Project,
    ProjectPrompt,
    ScheduleRun,
    Subtask,
    Task,
)
from app.models.common import now_local
from app.models.enums import ExtractStatus, RunStatus, RunTrigger
from app.models.project import BrandMention

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


# --------------------------------------------------------------------------
# Placeholder tests
# --------------------------------------------------------------------------


def test_competitor_kpi_has_new_fields():
    from app.schemas.project import CompetitorKpi
    fields = CompetitorKpi.model_fields
    for name in ("top1_rate", "sentiment_positive", "sentiment_neutral",
                 "sentiment_negative", "mention_rate_delta", "top1_rate_delta",
                 "top3_rate_delta", "sentiment_delta"):
        assert name in fields, f"missing field {name}"


def test_competitor_analysis_out_has_new_fields():
    from app.schemas.project import CompetitorAnalysisOut, ModelDiff, QuadrantPoint
    fields = CompetitorAnalysisOut.model_fields
    for name in ("diff_core", "diff_model", "diff_quadrant",
                 "previous_window_start", "previous_window_end"):
        assert name in fields, f"missing field {name}"
    assert "concern_tags" not in fields, "concern_tags should be removed"
    # Verify the new types are importable
    assert ModelDiff.model_fields.keys() >= {
        "platform", "self_mention_rate", "self_top1_rate", "self_top3_rate",
        "competitor_mention_rate", "competitor_top1_rate", "competitor_top3_rate"
    }
    assert QuadrantPoint.model_fields.keys() >= {
        "platform", "self_mention_rate", "competitor_avg_mention_rate"
    }


# --------------------------------------------------------------------------
# Helper + real test for top1_rate + sentiment 3-way (Task 5)
# --------------------------------------------------------------------------


def _make_subtask(db, project_id, customer_id, platform="doubao"):
    """Seed one subtask + task pair."""
    from app.models.task import Task, Subtask
    task = Task(
        project_id=project_id, customer_id=customer_id,
        task_id=f"task-{platform}-x",
        status="success",
    )
    db.add(task); db.flush()
    sub = Subtask(
        task_id=task.task_id, subtask_id=f"subtask-{platform}-x",
        platform=platform, status="success",
    )
    db.add(sub); db.flush()
    return sub


async def test_kpi_top1_and_sentiment_computed(client, h):
    """Top1_rate + 情感三档真实端到端:种子 1 subtask + 自身/竞品各 1 行,
    验证 self.top1_rate=1.0 / 竞品.top1_rate=0.0 / 情感三档比例正确。"""
    with TestSessionLocal() as db:
        cust = Customer(name="test", code="test")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-task5", brand="自身A")
        db.add(proj); db.flush()
        pid = proj.id

        # Seed 1 subtask, 2 brand mentions: 自身 rank=1 positive; 竞品 rank=2 negative
        sub = _make_subtask(db, pid, cust.id)
        db.add(BrandMention(
            subtask_id=sub.subtask_id, task_id=sub.task_id,
            project_id=pid, customer_id=cust.id,
            brand_canonical="自身A", is_self=True,
            mention_count=1, rank_position=1, sentiment_score="positive",
            extract_status=ExtractStatus.SUCCESS,
        ))
        db.add(BrandMention(
            subtask_id=sub.subtask_id, task_id=sub.task_id,
            project_id=pid, customer_id=cust.id,
            brand_canonical="竞品B", is_self=False,
            mention_count=1, rank_position=2, sentiment_score="negative",
            extract_status=ExtractStatus.SUCCESS,
        ))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    self_kpi = body["self_brand"]
    assert self_kpi["top1_rate"] == 1.0
    assert self_kpi["sentiment_positive"] == 1.0
    assert self_kpi["sentiment_neutral"] == 0.0
    assert self_kpi["sentiment_negative"] == 0.0
    comp = next(c for c in body["competitors"] if c["brand_canonical"] == "竞品B")
    assert comp["top1_rate"] == 0.0  # rank=2,不是 Top1
    assert comp["sentiment_negative"] == 1.0
