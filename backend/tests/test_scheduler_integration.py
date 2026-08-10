# SQLite models persist naive Asia/Shanghai wall-clock datetimes.
# ruff: noqa: DTZ001

"""Freezegun-driven integration tests for ``app.services.scheduler``.

These tests live in a dedicated module (rather than appended to
``test_scheduler.py``) so the cooldown-window / bucket-boundary coverage
that depends on ``freezegun`` is isolated from the pure unit tests added
in Task 7. The fixtures mirror the parent file's StaticPool pattern so
each test gets a clean in-memory schema.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.db import Base
from app.models import Customer, Project, ProjectKeyword, ProjectPlatform, ProjectPrompt
from app.models.common import now_local
from app.models.enums import RunStatus, RunTrigger
from app.models.schedule import ScheduleRun
from freezegun import freeze_time
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(
    bind=test_engine, autoflush=False, autocommit=False, future=True
)


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch):
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(
        "app.services.scheduler.get_session_factory", lambda: TestSessionLocal
    )
    yield
    Base.metadata.drop_all(test_engine)


def _create_project() -> int:
    with TestSessionLocal() as db:
        customer = Customer(name="Acme", code="ACME")
        project = Project(customer=customer, name="Monitor", code="MON")
        project.prompts = [
            ProjectPrompt(prompt="first question", sort=1),
        ]
        project.keywords = [
            ProjectKeyword(keyword="alpha", sort=1),
        ]
        project.platforms = [
            ProjectPlatform(
                platform="deepseek", mode="search", screenshot=1, sort=1
            )
        ]
        db.add(project)
        db.commit()
        db.refresh(project)
        return project.id


def _record_skipped_run(project_id: int, slot_index: int) -> int:
    """Mirror the API-layer behaviour of recording a skipped run on cooldown hit.

    ``run_project`` itself returns ``None`` on a cooldown collision but does not
    persist a "skipped" row. The HTTP layer (``projects.trigger_run``) is what
    actually inserts the skipped ScheduleRun; this helper reproduces that side
    effect for the tests that need to assert against it.
    """
    with TestSessionLocal() as db:
        run = ScheduleRun(
            project_id=project_id,
            slot_index=slot_index,
            trigger_type=RunTrigger.MANUAL,
            triggered_at=now_local(),
            status=RunStatus.SKIPPED,
            cooldown_key="manual-cooldown-skip",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# 1. Bucket boundaries — pure unit, no DB or remote calls.
# ---------------------------------------------------------------------------


def test_cooldown_key_bucket_boundaries():
    from app.services.scheduler import cooldown_key

    # Every minute within an hour rolls into the right bucket (0..11).
    for minute in range(0, 5):
        assert cooldown_key(1, 1, datetime(2026, 8, 7, 9, minute)) == (
            "project-1-slot-1-20260807090"
        ), f"minute={minute} should map to bucket 0"
    for minute in range(5, 10):
        assert cooldown_key(1, 1, datetime(2026, 8, 7, 9, minute)) == (
            "project-1-slot-1-20260807091"
        ), f"minute={minute} should map to bucket 1"
    for minute in range(55, 60):
        assert cooldown_key(1, 1, datetime(2026, 8, 7, 9, minute)) == (
            "project-1-slot-1-202608070911"
        ), f"minute={minute} should map to bucket 11"

    # Spot-check the two anchor times from the task spec.
    assert cooldown_key(1, 1, datetime(2026, 8, 7, 9, 0)) == (
        "project-1-slot-1-20260807090"
    )
    assert cooldown_key(1, 1, datetime(2026, 8, 7, 9, 5)) == (
        "project-1-slot-1-20260807091"
    )

    # Different slot_index / project_id produce different keys at the same wall clock.
    same_time = datetime(2026, 8, 7, 9, 0)
    assert cooldown_key(1, 1, same_time) != cooldown_key(1, 2, same_time)
    assert cooldown_key(1, 1, same_time) != cooldown_key(2, 1, same_time)


# ---------------------------------------------------------------------------
# 2. Cooldown window — freezegun moves the clock past the bucket boundary.
# ---------------------------------------------------------------------------


def test_freezegun_cooldown_window_5min(monkeypatch):
    from app.services import scheduler

    project_id = _create_project()

    counter = {"i": 0}

    async def fake_submit(self, payload):
        counter["i"] += 1
        i = counter["i"]
        return {
            "taskId": f"remote-{i}",
            "status": "pending",
            "totalTask": 1,
            "subTaskList": [
                {
                    "subTaskId": f"sub-{i}",
                    "prompt": "first question",
                    "platform": "deepseek",
                    "mode": "search",
                    "status": "pending",
                }
            ],
        }

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task", fake_submit)

    # First cron call at 09:00 lands in bucket 0 → real run.
    with freeze_time("2026-08-07 09:00:00", tz_offset=-8):
        first_run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)
    assert first_run_id is not None
    with TestSessionLocal() as db:
        first = db.get(ScheduleRun, first_run_id)
        assert first.status == RunStatus.SUCCESS
        assert first.cooldown_key == "project-1-slot-1-20260807090"

    # 09:04 is still bucket 0 → manual trigger collides on the unique index.
    with freeze_time("2026-08-07 09:04:00", tz_offset=-8):
        second_run_id = scheduler.run_project(project_id, 1, RunTrigger.MANUAL)
    assert second_run_id is None
    skipped_id = _record_skipped_run(project_id, 1)
    with TestSessionLocal() as db:
        skipped = db.get(ScheduleRun, skipped_id)
        assert skipped.status == RunStatus.SKIPPED

    # Jump past the bucket boundary (09:05 → bucket 1) → fresh run.
    with freeze_time("2026-08-07 09:05:00", tz_offset=-8):
        third_run_id = scheduler.run_project(project_id, 1, RunTrigger.MANUAL)
    assert third_run_id is not None
    assert third_run_id != first_run_id
    with TestSessionLocal() as db:
        third = db.get(ScheduleRun, third_run_id)
        assert third.status == RunStatus.SUCCESS
        assert third.cooldown_key == "project-1-slot-1-20260807091"

    # The two successful runs coexist; the skipped row is preserved too.
    with TestSessionLocal() as db:
        rows = db.scalars(
            select(ScheduleRun)
            .where(ScheduleRun.project_id == project_id)
            .order_by(ScheduleRun.id)
        ).all()
    statuses = sorted(r.status.value for r in rows)
    assert statuses == ["skipped", "success", "success"]


# ---------------------------------------------------------------------------
# 3. Cooldown does not cross slots — slot_index is part of the key.
# ---------------------------------------------------------------------------


def test_freezegun_cooldown_does_not_cross_slots(monkeypatch):
    from app.services import scheduler

    project_id = _create_project()

    counter = {"i": 0}

    async def fake_submit(self, payload):
        counter["i"] += 1
        i = counter["i"]
        return {
            "taskId": f"remote-{i}",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task", fake_submit)

    with freeze_time("2026-08-07 09:00:00", tz_offset=-8):
        run_one = scheduler.run_project(project_id, 1, RunTrigger.CRON)
        run_two = scheduler.run_project(project_id, 2, RunTrigger.CRON)

    assert run_one is not None
    assert run_two is not None
    assert run_one != run_two

    with TestSessionLocal() as db:
        rows = db.scalars(
            select(ScheduleRun)
            .where(ScheduleRun.project_id == project_id)
            .order_by(ScheduleRun.slot_index)
        ).all()
    assert len(rows) == 2
    assert {r.slot_index for r in rows} == {1, 2}
    assert all(r.status == RunStatus.SUCCESS for r in rows)
    assert rows[0].cooldown_key == "project-1-slot-1-20260807090"
    assert rows[1].cooldown_key == "project-1-slot-2-20260807090"


# ---------------------------------------------------------------------------
# 4. Triggered/started timestamps are recorded in Asia/Shanghai wall clock.
# ---------------------------------------------------------------------------


def test_freezegun_run_records_timestamps_in_shanghai(monkeypatch):
    from app.services import scheduler

    project_id = _create_project()

    counter = {"i": 0}

    async def fake_submit(self, payload):
        counter["i"] += 1
        i = counter["i"]
        return {
            "taskId": f"remote-{i}",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task", fake_submit)

    with freeze_time("2026-08-07 09:00:00", tz_offset=-8):
        run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)
    assert run_id is not None

    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)

    expected = datetime(2026, 8, 7, 9, 0, 0)
    # Naive values stored in the DB match the frozen Asia/Shanghai wall clock.
    assert run.triggered_at == expected
    assert run.started_at == expected
    # No tzinfo leaks into the persisted naive datetime.
    assert run.triggered_at.tzinfo is None
    assert run.started_at.tzinfo is None
    # And the Shanghai-aware wall clock agrees too (per task spec: ZoneInfo).
    shanghai = ZoneInfo("Asia/Shanghai")
    assert run.triggered_at == expected.replace(tzinfo=shanghai).replace(tzinfo=None)