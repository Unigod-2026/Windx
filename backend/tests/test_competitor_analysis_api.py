"""Tests for GET /api/projects/{id}/competitor-analysis endpoint."""

from __future__ import annotations

from datetime import datetime, time, timedelta

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


# --------------------------------------------------------------------------
# Helper + real test for 4 deltas comparing current vs previous window (Task 6)
# --------------------------------------------------------------------------


def _make_subtask_at(db, project_id, customer_id, day, platform="doubao"):
    """Seed a task+subtask pair at a specific calendar day. Caller should also
    backdate the BrandMention rows that reference this subtask (BrandMention
    has its own server-default created_at, so without backdating the
    BrandMention stays in the current window).
    """
    from app.models.task import Subtask as TSubtask, Task as TTask
    task = TTask(
        project_id=project_id, customer_id=customer_id,
        task_id=f"task-{platform}-{day}", status="success",
    )
    db.add(task); db.flush()
    sub = TSubtask(
        task_id=task.task_id, subtask_id=f"sub-{platform}-{day}",
        platform=platform, status="success",
    )
    db.add(sub); db.flush()
    sub.created_at = datetime.combine(day, time.min)
    return sub


def _brandmention_at(db, sub, project_id, customer_id, brand, is_self, day,
                     mention_count, rank, sentiment, extract_status):
    """BrandMention with explicit created_at so window placement is deterministic."""
    from app.models.project import BrandMention as BM
    bm = BM(
        subtask_id=sub.subtask_id, task_id=sub.task_id,
        project_id=project_id, customer_id=customer_id,
        brand_canonical=brand, is_self=is_self,
        mention_count=mention_count, rank_position=rank,
        sentiment_score=sentiment, extract_status=extract_status,
    )
    bm.created_at = datetime.combine(day, time.min)
    db.add(bm)
    return bm


async def test_kpi_deltas_compare_previous_window(client, h):
    """Seeds current window with mention_rate=1.0, prev window with 0.0 → delta=+1.0"""
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-task6", brand="A"); db.add(proj); db.flush()
        pid = proj.id

        today = now_local().date()
        # Current window: today (1 subtask mentioned)
        cur_sub = _make_subtask_at(db, pid, cust.id, today, platform="doubao")
        _brandmention_at(db, cur_sub, pid, cust.id, "A", True, today,
                         mention_count=1, rank=1, sentiment="positive",
                         extract_status=ExtractStatus.SUCCESS)
        # Prev window: 15 days ago (1 subtask, NOT mentioned). Must land in
        # prev window = [today-29d, today-15d] for days=15. Note: a naive
        # "yesterday" seed would actually be in the CURRENT window (15d
        # window spans both today and yesterday), so prev_by_brand would
        # be empty and the deltas would all be None.
        prev_day = today - timedelta(days=15)
        prev_sub = _make_subtask_at(db, pid, cust.id, prev_day, platform="doubao")
        _brandmention_at(db, prev_sub, pid, cust.id, "A", True, prev_day,
                         mention_count=0, rank=None, sentiment=None,
                         extract_status=ExtractStatus.SKIPPED)
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    self_kpi = body["self_brand"]
    # current mention_rate=1.0, prev=0.0 → delta=1.0
    assert self_kpi["mention_rate_delta"] == 1.0
    assert self_kpi["top1_rate_delta"] == 1.0
    assert self_kpi["top3_rate_delta"] == 1.0
    # prev brand was SKIPPED (no sentiment) → sentiment_delta is None
    assert self_kpi["sentiment_delta"] is None
    # previous_window_* should be filled because prev_brand_rows is non-empty
    assert body["previous_window_start"] is not None
    assert body["previous_window_end"] is not None


# --------------------------------------------------------------------------
# diff_core — 3 个指标 self vs competitor avg (Task 7)
# --------------------------------------------------------------------------


async def test_diff_core_self_vs_competitor_avg(client, h):
    """3 个指标 self vs competitor avg,百分比 0-100。"""
    from app.models import Customer, Project
    from app.models.enums import ExtractStatus
    from app.models.project import BrandMention

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-task7", brand="自身A"); db.add(proj); db.flush()
        pid = proj.id

        # 1 subtask, 自身 rank=1 mentioned, 2 竞品 各 rank=2 mentioned
        sub = _make_subtask(db, pid, cust.id)
        for b, is_self, rank in [("自身A", True, 1), ("竞品B", False, 2), ("竞品C", False, 2)]:
            db.add(BrandMention(
                subtask_id=sub.subtask_id, task_id=sub.task_id,
                project_id=pid, customer_id=cust.id,
                brand_canonical=b, is_self=is_self,
                mention_count=1, rank_position=rank,
                sentiment_score="positive" if is_self else "neutral",
                extract_status=ExtractStatus.SUCCESS,
            ))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    body = r.json()["diff_core"]
    assert body["labels"] == ["提及率", "Top1", "Top3"]
    # 自身:mention_rate=1.0, top1=1.0, top3=1.0 → 100,100,100
    assert body["self"] == [100.0, 100.0, 100.0]
    # 竞品均值:mention_rate=1.0 each (avg=1.0), top1=0.0 (rank=2 不算 Top1),
    # top3=1.0 (rank=2 仍算 Top3,定义是 rank<=3) → 100,0,100
    assert body["competitor_avg"] == [100.0, 0.0, 100.0]


# --------------------------------------------------------------------------
# diff_model — 每个 platform 一行,自身 vs 竞品均值 (Task 8)
# --------------------------------------------------------------------------


async def test_diff_model_per_platform_self_vs_competitor(client, h):
    """每个 platform 一行,自身/竞品均值 in 提及率/Top1/Top3。"""
    from app.models import Customer, Project
    from app.models.enums import ExtractStatus
    from app.models.project import BrandMention

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-task8", brand="A"); db.add(proj); db.flush()
        pid = proj.id

        # doubao: 自身 rank=1 + 1 竞品 rank=2 (1 subtask)
        sub1 = _make_subtask(db, pid, cust.id, platform="doubao")
        db.add(BrandMention(subtask_id=sub1.subtask_id, task_id=sub1.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="A", is_self=True,
            mention_count=1, rank_position=1, sentiment_score="positive",
            platform="doubao", extract_status=ExtractStatus.SUCCESS))
        db.add(BrandMention(subtask_id=sub1.subtask_id, task_id=sub1.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="B", is_self=False,
            mention_count=1, rank_position=2, sentiment_score="neutral",
            platform="doubao", extract_status=ExtractStatus.SUCCESS))
        # kimi: 自身 未提及 + 1 竞品 rank=1
        sub2 = _make_subtask(db, pid, cust.id, platform="kimi")
        db.add(BrandMention(subtask_id=sub2.subtask_id, task_id=sub2.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="A", is_self=True,
            mention_count=0, platform="kimi", extract_status=ExtractStatus.SKIPPED))
        db.add(BrandMention(subtask_id=sub2.subtask_id, task_id=sub2.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="B", is_self=False,
            mention_count=1, rank_position=1, sentiment_score="positive",
            platform="kimi", extract_status=ExtractStatus.SUCCESS))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    diff_model = {m["platform"]: m for m in r.json()["diff_model"]}
    assert "doubao" in diff_model
    assert "kimi" in diff_model
    # doubao: self mention_rate=1.0, top1=1.0, top3=1.0; comp avg mention=1.0, top1=0.0, top3=0.0
    assert diff_model["doubao"]["self_mention_rate"] == 1.0
    assert diff_model["doubao"]["self_top1_rate"] == 1.0
    assert diff_model["doubao"]["competitor_top1_rate"] == 0.0
    # kimi: self mention_rate=0.0, comp avg mention=1.0, top1=1.0
    assert diff_model["kimi"]["self_mention_rate"] == 0.0
    assert diff_model["kimi"]["competitor_mention_rate"] == 1.0
    assert diff_model["kimi"]["competitor_top1_rate"] == 1.0
