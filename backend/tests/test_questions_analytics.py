"""Tests for the 问题提及分析 tab ``status-changes`` endpoint.

Covers ``GET /projects/{id}/questions/status-changes`` 4-quadrant split:
  * ``stable`` — prev window had a mention AND current window has one
  * ``drops`` — per (prompt, platform) loss-of-mention events with reason
  * ``never_listed`` — no mention in either window
  * ``listed`` — at least one mention in current window regardless of prev

Also exercises window-resolution semantics (start/end/days) and the
paused-prompt filter (paused prompts excluded from all four sets).
"""

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
# Fixtures
# --------------------------------------------------------------------------


PLATFORMS = ["doubao", "deepseek", "kimi", "wenxinyiyan", "qianwen", "hunyuan"]
PROMPTS = ["敏感肌护肤品牌推荐", "油皮粉底液推荐", "平价防晒霜"]


def _bootstrap(seed_window_days: int = 15):
    """Create a project + 3 prompts + 6 platforms × 30 days of mentions.

    Each prompt gets mentions on all 6 platforms for the entire seed
    window. rank_position rotates 1..3 so top1/top3 rates are non-zero.
    Competitor rows (is_self=false) are added for the same windows.
    Returns the project id and run day-count metadata.
    """
    now = now_local()
    today = now.date()
    win_start = today - timedelta(days=seed_window_days - 1)
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code="acme")
        db.add(cust)
        db.commit()
        db.refresh(cust)
        proj = Project(
            customer_id=cust.id,
            name="P",
            code="P1",
            status="active",
            brand="Acme",
            category_taxonomy=["引流感", "场景类", "体验类"],
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)
        # Prompts.
        prompt_ids: list[int] = []
        for i, p in enumerate(PROMPTS):
            row = ProjectPrompt(
                project_id=proj.id,
                prompt=p,
                sort=i,
                category=["引流感", "场景类", "体验类"][i % 3],
                status="monitoring",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            prompt_ids.append(row.id)
        # Subtasks + brand_mentions.
        for d_offset in range(seed_window_days + 30):
            day = today - timedelta(days=d_offset)
            for plat in PLATFORMS:
                for p_idx, prompt in enumerate(PROMPTS):
                    sub_id = f"sub-{day.isoformat()}-{plat}-{p_idx}"
                    db.add(
                        Subtask(
                            subtask_id=sub_id,
                            task_id=f"task-{day.isoformat()}",
                            platform=plat,
                            prompt=prompt,
                            status="SUCCESS",
                            answer_content=f"({prompt} on {plat} day {day}) " * 20,
                            updated_at=now - timedelta(days=d_offset),
                        )
                    )
                    rank = (p_idx + d_offset) % 5 + 1
                    db.add(
                        BrandMention(
                            subtask_id=sub_id,
                            task_id=f"task-{day.isoformat()}",
                            project_id=proj.id,
                            customer_id=cust.id,
                            prompt=prompt,
                            platform=plat,
                            brand_canonical="Acme",
                            is_self=True,
                            mention_count=1,
                            rank_position=rank,
                            sentiment_score="positive",
                            is_recommended=True,
                            extract_status=ExtractStatus.SUCCESS,
                            created_at=now - timedelta(days=d_offset),
                        )
                    )
                    # Competitor row for each platform/prompt/day.
                    db.add(
                        BrandMention(
                            subtask_id=sub_id,
                            task_id=f"task-{day.isoformat()}",
                            project_id=proj.id,
                            customer_id=cust.id,
                            prompt=prompt,
                            platform=plat,
                            brand_canonical="珂润",
                            is_self=False,
                            mention_count=1,
                            rank_position=rank,
                            sentiment_score="neutral",
                            is_recommended=False,
                            extract_status=ExtractStatus.SUCCESS,
                            created_at=now - timedelta(days=d_offset),
                        )
                    )
        db.commit()
        return proj.id


# --------------------------------------------------------------------------
# questions/status-changes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_changes_classifies_four_sets(client, h):
    """4 quadrants are populated by the seeded fixture."""
    pid = _bootstrap(seed_window_days=15)
    r = await client.get(
        f"/api/projects/{pid}/questions/status-changes?days=15", headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Fixture seeds 3 prompts × 6 platforms × 15 days — every prompt
    # is mentioned on every day, so:
    #   - stable: all 3 (prev and current both have mentions)
    #   - drops: 0 (no prompt dropped)
    #   - listed: all 3 (at least one mention in current)
    #   - never_listed: 0
    assert len(body["stable"]) == 3
    assert body["drops"] == []
    assert len(body["listed"]) == 3
    assert body["never_listed"] == []


@pytest.mark.asyncio
async def test_status_changes_emits_drop_event(client, h):
    """A prompt with prev mention but no current mention emits a DropEvent."""
    pid = _bootstrap(seed_window_days=15)
    with TestSessionLocal() as db:
        # Wipe the entire CURRENT window's mentions for the first prompt
        # on the first platform — that (prompt, platform) has prev
        # mentions but no current, so it must appear in drops.
        from datetime import datetime, time

        from sqlalchemy import delete

        from app.models.task import Subtask as S
        from app.models.project import BrandMention as BM

        today = now_local().date()
        win_start = today - timedelta(days=14)
        win_start_dt = datetime.combine(win_start, time.min)
        win_end_dt = datetime.combine(today, time.max)
        first_prompt = PROMPTS[0]
        first_plat = PLATFORMS[0]
        db.execute(
            delete(BM).where(
                BM.prompt == first_prompt,
                BM.platform == first_plat,
                BM.created_at >= win_start_dt,
                BM.created_at <= win_end_dt,
            )
        )
        db.execute(
            delete(S).where(
                S.prompt == first_prompt,
                S.platform == first_plat,
                S.updated_at >= win_start_dt,
                S.updated_at <= win_end_dt,
            )
        )
        db.commit()
    r = await client.get(
        f"/api/projects/{pid}/questions/status-changes?days=15", headers=h
    )
    body = r.json()
    drops = body["drops"]
    # The (prompt, platform) we wiped should appear in drops.
    matching = [
        d for d in drops
        if d["prompt"] == first_prompt and d["platform"] == first_plat
    ]
    assert len(matching) >= 1
    e = matching[0]
    assert e["from_rank"] is not None
    assert e["reason"] is not None


@pytest.mark.asyncio
async def test_status_changes_filters_paused_prompts(client, h):
    """A prompt with status=paused is excluded from all 4 quadrants."""
    pid = _bootstrap(seed_window_days=15)
    with TestSessionLocal() as db:
        # Mark the first prompt paused — it should vanish from all sets.
        first_prompt = PROMPTS[0]
        from sqlalchemy import update

        from app.models import ProjectPrompt as PP

        db.execute(
            update(PP)
            .where(PP.prompt == first_prompt)
            .values(status="paused")
        )
        db.commit()
    r = await client.get(
        f"/api/projects/{pid}/questions/status-changes?days=15", headers=h
    )
    body = r.json()
    for arr in (body["stable"], body["listed"]):
        for it in arr:
            assert it["prompt"] != first_prompt
    for d in body["drops"]:
        assert d["prompt"] != first_prompt


@pytest.mark.asyncio
async def test_summary_returns_window_kpis(client, h):
    pid = _bootstrap(seed_window_days=15)
    response = await client.get(
        f"/api/projects/{pid}/questions/summary?days=15", headers=h
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == pid
    assert len(body["items"]) == len(PROMPTS)
    total = sum(item["total"] for item in body["items"])
    # _bootstrap 生成 6 platforms × 15 days × 3 prompts = 270 行 is_self=true
    assert total == 270
    # 每个 prompt 在每个 platform 都被提及,coverage = 6
    assert all(item["coverage"] == len(PLATFORMS) for item in body["items"])
    # category_summary 与 taxonomy 长度一致
    assert len(body["category_summary"]) == len(["引流感", "场景类", "体验类"])


@pytest.mark.asyncio
async def test_product_analytics_returns_platforms_prev_long_prev(client, h):
    pid = _bootstrap(seed_window_days=15)
    from app.models import ProjectPrompt

    with TestSessionLocal() as db:
        first_prompt_id = (
            db.query(ProjectPrompt.id).filter_by(project_id=pid).first()[0]
        )

    response = await client.get(
        f"/api/projects/{pid}/questions/{first_prompt_id}/product-analytics?days=15",
        headers=h,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_id"] == first_prompt_id
    # 6 platforms 都有 stat
    assert len(body["platforms"]) == len(PLATFORMS)
    # prev / long_prev 都是 15 天窗口,各自有数据
    assert body["prev"] is not None
    assert body["long_prev"] is not None
    # 6 平台摘录都返回(只要窗口内有 subtask)
    assert len(body["excerpts"]) == len(PLATFORMS)


@pytest.mark.asyncio
async def test_product_analytics_rejects_cross_project_prompt(client, h):
    pid_a = _bootstrap(seed_window_days=15)
    from app.models import Customer, Project, ProjectPrompt

    with TestSessionLocal() as db:
        cust = db.query(Customer).first()
        other = Project(customer_id=cust.id, name="Other", code="O1", status="active")
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
        first_prompt_id = (
            db.query(ProjectPrompt.id).filter_by(project_id=pid_a).first()[0]
        )

    response = await client.get(
        f"/api/projects/{other_id}/questions/{first_prompt_id}/product-analytics?days=15",
        headers=h,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_product_analytics_stays_within_query_budget(client, h):
    """product-analytics 核心 SQL ≤ 3(spec §4.2),排除 auth/existence。"""
    pid = _bootstrap(seed_window_days=15)
    from app.models import ProjectPrompt
    from tests._query_counter import QueryCounter

    with TestSessionLocal() as db:
        first_prompt_id = (
            db.query(ProjectPrompt.id).filter_by(project_id=pid).first()[0]
        )

    with QueryCounter(test_engine) as counter:
        response = await client.get(
            f"/api/projects/{pid}/questions/{first_prompt_id}/product-analytics?days=15",
            headers=h,
        )
    assert response.status_code == 200
    # 只统计 geo_brand_mentions / geo_subtasks 上的核心业务 SQL
    core = [
        q for q in counter.queries
        if "geo_brand_mentions" in q or "geo_subtasks" in q
    ]
    assert len(core) <= 3, f"core queries exceeded 3: {len(core)}\n" + "\n".join(core)


@pytest.mark.asyncio
async def test_summary_stays_within_query_budget(client, h):
    """summary endpoint 的核心 SQL 必须 ≤ 1 条(spec §4.1)。

    Auth (``geo_admin_users``) + 404 lookup (``geo_projects``) 是路由
    公共开销,与 spec §4.1「不再额外扫描 geo_brand_mentions」无关,
    只校验业务核心表 ``geo_brand_mentions`` 的扫描次数。
    """
    pid = _bootstrap(seed_window_days=15)
    from tests._query_counter import QueryCounter

    with QueryCounter(test_engine) as counter:
        response = await client.get(
            f"/api/projects/{pid}/questions/summary?days=15", headers=h
        )
    assert response.status_code == 200
    bm_queries = [q for q in counter.queries if "geo_brand_mentions" in q]
    assert len(bm_queries) == 1, (
        f"expected exactly 1 scan of geo_brand_mentions, got {len(bm_queries)}:\n"
        + "\n".join(f"  {i + 1}. {q[:200]}" for i, q in enumerate(bm_queries))
    )


@pytest.mark.asyncio
async def test_competitor_analytics_aggregates_by_brand(client, h):
    pid = _bootstrap(seed_window_days=15)
    from app.models import ProjectPrompt

    with TestSessionLocal() as db:
        first_prompt_id = (
            db.query(ProjectPrompt.id).filter_by(project_id=pid).first()[0]
        )

    response = await client.get(
        f"/api/projects/{pid}/questions/{first_prompt_id}/competitor-analytics?days=15",
        headers=h,
    )
    assert response.status_code == 200
    body = response.json()
    # _bootstrap 种了 1 个自身 brand "Acme" + 1 个竞品 "珂润",每个 prompt
    # × 6 platform × 15 天。竞品面板首张卡必须是自身品牌,方便对比。
    canonicals = [(b["brand_canonical"], b["is_self"]) for b in body["brands"]]
    assert ("Acme", True) in canonicals
    assert ("珂润", False) in canonicals
    assert canonicals[0] == ("Acme", True), (
        f"self brand must be first, got order: {canonicals}"
    )
    # 自身品牌拿到保留的 primary blue,竞品走 palette
    self_brand = body["brands"][0]
    assert self_brand["color"] == "#1a55e8"
    # 6 platform 都出现在 model_ranks
    assert len(self_brand["model_ranks"]) == len(PLATFORMS)
    # mention_rate 字段存在,数值在 0-1 之间
    assert 0.0 <= self_brand["mention_rate"] <= 1.0
    # 6 平台摘录 key 都在(只要 subtask 存在)
    assert len(body["excerpts"]) == len(PLATFORMS)


@pytest.mark.asyncio
async def test_competitor_analytics_stays_within_query_budget(client, h):
    """competitor-analytics 核心 SQL ≤ 2(spec §4.3)。"""
    pid = _bootstrap(seed_window_days=15)
    from app.models import ProjectPrompt
    from tests._query_counter import QueryCounter

    with TestSessionLocal() as db:
        first_prompt_id = (
            db.query(ProjectPrompt.id).filter_by(project_id=pid).first()[0]
        )

    with QueryCounter(test_engine) as counter:
        response = await client.get(
            f"/api/projects/{pid}/questions/{first_prompt_id}/competitor-analytics?days=15",
            headers=h,
        )
    assert response.status_code == 200
    core = [
        q for q in counter.queries
        if "geo_brand_mentions" in q or "geo_subtasks" in q
    ]
    assert len(core) <= 2, f"core queries exceeded 2: {len(core)}\n" + "\n".join(core)
