# SQLite models persist naive Asia/Shanghai wall-clock datetimes.

from __future__ import annotations

import asyncio

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Customer, Project
from app.models.enums import ProjectStatus

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
        "app.services.scheduler_runtime.get_session_factory", lambda: TestSessionLocal
    )
    yield
    Base.metadata.drop_all(test_engine)


def _create_project(**kwargs) -> int:
    """Insert one customer + project; ``kwargs`` override project columns."""
    with TestSessionLocal() as db:
        customer = Customer(name="Acme", code=f"ACME{kwargs.get('code', 'MON')}")
        project = Project(
            customer=customer,
            name="Monitor",
            code=kwargs.pop("code", "MON"),
            status=kwargs.pop("status", ProjectStatus.ACTIVE),
            **kwargs,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project.id


def test_reload_jobs_skips_disabled_projects():
    from app.services.scheduler_runtime import reload_jobs

    _create_project(schedule_enabled=False, slot1_hour=9, slot1_minute=30)
    scheduler = AsyncIOScheduler()

    assert reload_jobs(scheduler) == 0
    assert scheduler.get_jobs() == []


def test_reload_jobs_skips_inactive_projects():
    from app.services.scheduler_runtime import reload_jobs

    _create_project(
        schedule_enabled=True,
        status=ProjectStatus.DISABLED,
        slot1_hour=9,
        slot1_minute=30,
    )
    scheduler = AsyncIOScheduler()

    assert reload_jobs(scheduler) == 0
    assert scheduler.get_jobs() == []


def test_reload_jobs_adds_one_job_per_slot():
    from app.services.scheduler_runtime import reload_jobs

    both = _create_project(
        code="BOTH",
        schedule_enabled=True,
        slot1_hour=9,
        slot1_minute=30,
        slot2_hour=21,
        slot2_minute=0,
    )
    single = _create_project(
        code="ONE", schedule_enabled=True, slot1_hour=8, slot1_minute=15
    )
    scheduler = AsyncIOScheduler()

    assert reload_jobs(scheduler) == 3
    assert sorted(job.id for job in scheduler.get_jobs()) == sorted(
        [
            f"project-{both}-slot-1",
            f"project-{both}-slot-2",
            f"project-{single}-slot-1",
        ]
    )


def test_reload_jobs_skips_slot_with_null_minute():
    from app.services.scheduler_runtime import reload_jobs

    project_id = _create_project(
        schedule_enabled=True,
        slot1_hour=9,
        slot1_minute=30,
        slot2_hour=21,
        slot2_minute=None,
    )
    scheduler = AsyncIOScheduler()

    assert reload_jobs(scheduler) == 1
    assert [job.id for job in scheduler.get_jobs()] == [f"project-{project_id}-slot-1"]


def test_reload_jobs_passes_cron_trigger_and_args():
    from app.services import scheduler_runtime

    project_id = _create_project(
        schedule_enabled=True, slot1_hour=9, slot1_minute=30
    )
    scheduler = AsyncIOScheduler()

    scheduler_runtime.reload_jobs(scheduler)

    job = scheduler.get_jobs()[0]
    assert job.func is scheduler_runtime.run_project_async
    assert tuple(job.args) == (project_id, 1, "cron")
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["hour"] == "9"
    assert fields["minute"] == "30"
    assert str(job.trigger.timezone) == "Asia/Shanghai"


def test_reload_jobs_idempotent():
    from app.services.scheduler_runtime import reload_jobs

    _create_project(
        schedule_enabled=True,
        slot1_hour=9,
        slot1_minute=30,
        slot2_hour=21,
        slot2_minute=0,
    )
    scheduler = AsyncIOScheduler()

    first = reload_jobs(scheduler)
    first_ids = sorted(job.id for job in scheduler.get_jobs())
    second = reload_jobs(scheduler)
    second_ids = sorted(job.id for job in scheduler.get_jobs())

    assert first == second == 2
    assert first_ids == second_ids


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_scheduler():
    from app.main import app

    _create_project(schedule_enabled=True, slot1_hour=9, slot1_minute=30)

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        assert scheduler.running is True
        assert [job.id for job in scheduler.get_jobs()] != []

    # AsyncIOScheduler.shutdown() defers the real teardown onto the event loop,
    # so yield once before asserting the scheduler actually stopped.
    await asyncio.sleep(0)
    assert scheduler.running is False
