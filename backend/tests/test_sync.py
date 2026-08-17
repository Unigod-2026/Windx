"""Background polling sync tests.

The LLM backend finishes every (prompt × platform) synchronously inside
``submit_task``, so by the time ``run_project`` returns every ``Task``
row is already terminal — there's nothing left to poll. These tests
verify that the polling loop is a safe no-op in that regime and that
existing rows still get advanced when they show up non-terminal.

Same SQLite in-memory pattern as :mod:`tests.test_scheduler`:

- A throwaway engine is built once per test and bound to a
  ``sessionmaker`` we patch into ``app.services.sync.get_session_factory``
  + ``app.services.scheduler.get_session_factory``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Customer,
    Project,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
    ScheduleRun,
    Subtask,
    Task,
)
from app.models.project import BrandMention
from app.models.common import now_local
from app.models.enums import ExtractStatus, RunStatus, RunTrigger
from app.services import sync as sync_module
from app.services.molizhishu_client import MolizhishuClient, MolizhishuError

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
        "app.services.sync.get_session_factory", lambda: TestSessionLocal
    )
    # The sync module carries in-process state across calls
    # (``_in_flight``, ``_backoff_until``, ``_backoff_count``). Reset
    # it between tests so backoff from a previous failure doesn't
    # leak into the next test's expectations.
    sync_module._in_flight.clear()
    sync_module._backoff_until.clear()
    sync_module._backoff_count.clear()
    yield
    Base.metadata.drop_all(test_engine)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_in_flight_task(task_id: str, status: str = "completed") -> Task:
    """Insert one ``Customer`` / ``Project`` / ``Task`` and return the Task row.

    Default status is ``completed`` because that's the realistic state
    after the LLM backend finishes a submit synchronously.
    """
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code=f"C-{task_id[:6]}")
        db.add(cust)
        db.flush()
        project = Project(customer_id=cust.id, name="P", code=f"P-{task_id[:6]}")
        db.add(project)
        db.flush()
        task = Task(
            task_id=task_id,
            status=status,
            customer_id=cust.id,
            project_id=project.id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task


def _seed_run_with_task(task_id: str) -> int:
    """Create a ``ScheduleRun`` linked to a pre-seeded task; return run id."""
    with TestSessionLocal() as db:
        task = db.get(Task, task_id)
        run = ScheduleRun(
            project_id=task.project_id,
            slot_index=0,
            trigger_type=RunTrigger.MANUAL,
            triggered_at=now_local(),
            started_at=now_local(),
            status=RunStatus.RUNNING,
        )
        db.add(run)
        db.flush()
        task.schedule_run_id = run.id
        db.commit()
        db.refresh(run)
        return run.id


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_select_in_flight_task_ids_skips_terminal():
    """``completed`` / ``failed`` / etc. must not appear in the selection."""
    _seed_in_flight_task("a" * 32, status="processing")
    _seed_in_flight_task("b" * 32, status="completed")
    _seed_in_flight_task("c" * 32, status="failed")
    _seed_in_flight_task("d" * 32, status="pending")

    assert sorted(sync_module._select_in_flight_task_ids(TestSessionLocal(), 10)) == [
        "a" * 32,
        "d" * 32,
    ]


def test_sync_pending_tasks_is_noop_when_all_rows_already_terminal():
    """The LLM backend finishes every submit synchronously, so a poll
    tick against a clean DB finds no rows that need advancing."""
    _seed_in_flight_task("a" * 32, status="completed")
    _seed_in_flight_task("b" * 32, status="partial_completed")
    _seed_in_flight_task("c" * 32, status="failed")

    result = sync_module.sync_pending_tasks()

    assert result.polled == 0
    assert result.refreshed == 0
    assert result.advanced == 0
    assert result.failed == 0


def test_refresh_advances_schedule_run_when_linked_run_is_still_running():
    """A legacy row whose linked ``ScheduleRun`` is still RUNNING must
    be promoted to SUCCESS on the next poll tick."""
    tid = "a" * 32
    _seed_in_flight_task(tid, status="completed")
    run_id = _seed_run_with_task(tid)

    result = sync_module.sync_pending_tasks()

    assert result.polled == 0  # already terminal, not selected
    assert result.advanced == 1
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        assert run.status == RunStatus.SUCCESS
        assert run.finished_at is not None


def test_refresh_idempotent_on_repeat_calls():
    """Polling twice must not double-advance or raise."""
    tid = "a" * 32
    _seed_in_flight_task(tid, status="completed")
    run_id = _seed_run_with_task(tid)

    sync_module.sync_pending_tasks()
    sync_module.sync_pending_tasks()

    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        assert run.status == RunStatus.SUCCESS


def test_sync_pending_tasks_runs_under_limit():
    """``limit`` caps the number of rows refreshed per tick."""
    # Seed a non-terminal row so the loop actually walks something
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code="ACME")
        db.add(cust)
        db.flush()
        project = Project(customer_id=cust.id, name="P", code="P")
        db.add(project)
        db.flush()
        for tid in ("a" * 32, "b" * 32, "c" * 32):
            db.add(
                Task(
                    task_id=tid,
                    status="pending",
                    customer_id=cust.id,
                    project_id=project.id,
                )
            )
        db.commit()

    result = sync_module.sync_pending_tasks(limit=2)
    assert result.polled == 2


# --------------------------------------------------------------------------
# Refresh path: status / result / backoff / concurrency / business errors
# --------------------------------------------------------------------------


def _patch_remote(monkeypatch, *, status_payload=None, result_payload=None,
                  status_error=None, result_error=None):
    """Wire ``MolizhishuClient`` sync methods onto controllable stubs.

    Returns the call counters so tests can assert how many times the
    remote was hit. ``status_payload`` is returned by
    ``get_task_status_sync``; if ``status_error`` is set it's raised
    instead. Same shape for the result endpoint.
    """
    calls = {"status": 0, "result": 0}

    def fake_status(self, task_id):
        calls["status"] += 1
        if status_error is not None:
            raise status_error
        return status_payload

    def fake_result(self, task_id):
        calls["result"] += 1
        if result_error is not None:
            raise result_error
        return result_payload

    monkeypatch.setattr(MolizhishuClient, "get_task_status_sync", fake_status)
    monkeypatch.setattr(MolizhishuClient, "get_task_result_sync", fake_result)
    return calls


def test_refresh_does_not_pull_result_when_status_is_processing(monkeypatch):
    """``status=processing`` + ``completedItems=0`` ⇒ cheap snapshot only.

    Per ``docs/api/get-task-status.md`` line 42, the heavy result
    endpoint should only fire once something has actually finished.
    The polling loop must respect that to keep bandwidth + cost down
    on the typical 5-60 minute wait.
    """
    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    calls = _patch_remote(
        monkeypatch,
        status_payload={
            "status": "processing",
            "totalItems": 2,
            "completedItems": 0,
            "failedItems": 0,
            "subTaskList": [
                {"subTaskId": "s1", "status": "processing"},
                {"subTaskId": "s2", "status": "processing"},
            ],
        },
        result_payload={"subTaskList": []},
    )

    result = sync_module.sync_pending_tasks()

    assert result.polled == 1
    assert result.refreshed == 1
    assert calls["status"] == 1
    assert calls["result"] == 0
    with TestSessionLocal() as db:
        task = db.get(Task, tid)
        assert task.status == "processing"
        assert task.total_items == 2


def test_refresh_pulls_result_when_completed_items_positive(monkeypatch):
    """``completedItems > 0`` ⇒ also call ``GET /task/result``.

    This is the transition from "wait" to "fetch": at least one
    subtask has produced output worth pulling.
    """
    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    calls = _patch_remote(
        monkeypatch,
        status_payload={
            "status": "processing",
            "totalItems": 2,
            "completedItems": 1,
            "failedItems": 0,
            "subTaskList": [
                {"subTaskId": "s1", "status": "completed"},
                {"subTaskId": "s2", "status": "processing"},
            ],
        },
        result_payload={
            "status": "processing",
            "subTaskList": [
                {
                    "subTaskId": "s1",
                    "status": "completed",
                    "platform": "deepseek",
                    "mode": "search",
                    "prompt": "q1",
                    "answerContent": "answer-1",
                }
            ],
        },
    )

    result = sync_module.sync_pending_tasks()

    assert result.polled == 1
    assert result.refreshed == 1
    assert calls["status"] == 1
    assert calls["result"] == 1
    with TestSessionLocal() as db:
        sub = db.get(Subtask, "s1")
        assert sub is not None
        assert sub.status == "completed"
        assert sub.answer_content == "answer-1"


def test_refresh_advances_run_after_remote_says_completed(monkeypatch):
    """A remote ``completed`` with no linked ``ScheduleRun`` keeps the
    ``Task`` row but doesn't change the ``SyncResult.advanced`` count.

    The test exercises the case where ``run_project`` was the most
    recent writer and the linked run was already advanced in the
    same submit — there should be nothing left for the polling loop
    to advance.
    """
    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    run_id = _seed_run_with_task(tid)
    # Pre-advance the run so the polling tick has nothing to do here.
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        run.status = RunStatus.SUCCESS
        run.finished_at = now_local()
        db.commit()

    _patch_remote(
        monkeypatch,
        status_payload={
            "status": "completed",
            "totalItems": 1,
            "completedItems": 1,
            "failedItems": 0,
            "subTaskList": [
                {"subTaskId": "s1", "status": "completed"},
            ],
        },
        result_payload={
            "status": "completed",
            "subTaskList": [
                {
                    "subTaskId": "s1",
                    "status": "completed",
                    "platform": "deepseek",
                    "mode": "search",
                    "prompt": "q1",
                    "answerContent": "answer-1",
                }
            ],
        },
    )

    result = sync_module.sync_pending_tasks()

    assert result.polled == 1
    assert result.advanced == 0  # run was already terminal
    assert result.refreshed == 1
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        assert run.status == RunStatus.SUCCESS


def test_refresh_transport_failure_schedules_backoff_and_writes_event(monkeypatch):
    """A 5xx from molizhishu increments the backoff ladder and writes
    a ``geo_compensation_events`` row.

    This is the canonical "remote is down, back off" path documented
    in ``docs/api/errors.md`` §处理建议.
    """
    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    _patch_remote(
        monkeypatch,
        status_error=MolizhishuError(
            code=None, message="gateway timeout", http_status=503, body=None
        ),
    )

    result = sync_module.sync_pending_tasks()

    assert result.polled == 1
    assert result.failed == 1
    assert result.refreshed == 0
    # First failure → ladder[0] = 60s.
    assert sync_module._backoff_count[tid] == 1
    assert tid in sync_module._backoff_until
    from datetime import timedelta

    from app.models.task import CompensationEvent

    with TestSessionLocal() as db:
        events = db.query(CompensationEvent).filter_by(task_id=tid).all()
        assert len(events) == 1
        assert events[0].source == "background-sync:refresh"
        assert events[0].action == "status"
        assert events[0].http_status == 503
        assert events[0].success is False


def test_refresh_business_error_403_404_does_not_schedule_backoff(monkeypatch):
    """``code=403/404/500`` from the remote ⇒ stop retrying.

    These codes carry information ("token invalid", "task not
    found") that no amount of retrying will resolve. The handler
    writes a compensation row but leaves the backoff map empty so
    the row is left alone on the next tick.
    """
    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    _patch_remote(
        monkeypatch,
        status_error=MolizhishuError(
            code=404, message="task not found", http_status=404, body=None
        ),
    )

    result = sync_module.sync_pending_tasks()

    assert result.polled == 1
    assert result.failed == 1
    assert tid not in sync_module._backoff_until
    assert sync_module._backoff_count.get(tid, 0) == 0


def test_refresh_skips_task_in_backoff(monkeypatch):
    """A task that failed recently must be skipped on the next tick.

    Backoff deadline is set in the future; the polling loop must
    notice and not bother the remote again until it expires.
    """
    from datetime import timedelta

    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    sync_module._backoff_until[tid] = now_local() + timedelta(minutes=5)
    sync_module._backoff_count[tid] = 1
    calls = _patch_remote(
        monkeypatch,
        status_payload={"status": "processing"},
    )

    result = sync_module.sync_pending_tasks()

    assert result.polled == 1  # selected by the in-flight query
    assert result.failed == 0
    assert result.refreshed == 0
    assert calls["status"] == 0  # ...but the remote was NOT called


def test_refresh_concurrent_same_task_id_only_one_remote_call(monkeypatch):
    """Two ticks overlapping on the same ``task_id`` must yield a
    single remote call.

    The ``_in_flight`` set is the lock — the second call sees the
    first still running and bails out. This protects us from a
    callback firing while the polling tick is mid-refresh, per
    ``api调用prompt.md`` §六.
    """
    tid = "a" * 32
    _seed_in_flight_task(tid, status="processing")
    # Pre-claim the task as if another path (e.g. a callback) is
    # already refreshing it.
    sync_module._in_flight.add(tid)
    calls = _patch_remote(
        monkeypatch,
        status_payload={"status": "processing"},
    )

    result = sync_module.sync_pending_tasks()

    assert calls["status"] == 0
    assert result.refreshed == 0
    assert result.failed == 0


@pytest.mark.asyncio
async def test_lifespan_registers_sync_job_with_configured_interval(monkeypatch):
    """The lifespan installs an ``IntervalTrigger`` matching
    ``MOLIZHISHU_SYNC_INTERVAL_SECONDS`` (in seconds, Asia/Shanghai)."""
    monkeypatch.setenv("MOLIZHISHU_SYNC_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("MOLIZHISHU_SYNC_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        job = scheduler.get_job("molizhishu-sync-pending-tasks")
        assert job is not None
        assert job.func is sync_module.sync_pending_tasks
        # ``IntervalTrigger.interval`` is a ``timedelta``.
        assert job.trigger.interval.total_seconds() == 120
        assert str(job.trigger.timezone) == "Asia/Shanghai"

    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_lifespan_skips_sync_job_when_disabled(monkeypatch):
    """``MOLIZHISHU_SYNC_ENABLED=false`` means no background polling job."""
    monkeypatch.setenv("MOLIZHISHU_SYNC_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        assert scheduler.get_job("molizhishu-sync-pending-tasks") is None

    await asyncio.sleep(0)


def test_apply_full_subtask_payload_writes_fields_but_returns_none():
    """The payload upsert no longer doubles as the extraction trigger.

    Extraction is now driven by ``_detect_newly_terminal``; the payload
    upsert must only persist the heavy fields and not second-guess
    what counts as "newly filled".
    """
    with TestSessionLocal() as db:
        db.add(Task(task_id="t-upsert", status="processing"))
        db.add(Subtask(task_id="t-upsert", subtask_id="s-1", status="processing"))
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed", "answerContent": "答案A"}]
        assert sync_module._apply_full_subtask_payload(db, "t-upsert", items) is None
        row = db.scalar(select(Subtask).where(Subtask.subtask_id == "s-1"))
        assert row.answer_content == "答案A"
        assert row.status == "completed"


def test_pending_extraction_fires_on_status_completed():
    """API says completed and no mention rows yet → trigger."""
    with TestSessionLocal() as db:
        db.add(Task(task_id="t-c", status="processing"))
        db.add(Subtask(task_id="t-c", subtask_id="s-1", status="processing"))
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed"}]
        assert sync_module._pending_extraction_ids(db, items) == ["s-1"]


def test_pending_extraction_fires_on_status_failed():
    """Failed subtasks also get extracted so the denominator stays full."""
    with TestSessionLocal() as db:
        db.add(Task(task_id="t-f", status="processing"))
        db.add(Subtask(task_id="t-f", subtask_id="s-1", status="processing"))
        db.commit()

        items = [{"subTaskId": "s-1", "status": "failed", "errorMessage": "x"}]
        assert sync_module._pending_extraction_ids(db, items) == ["s-1"]


def test_pending_extraction_skips_when_brand_mention_row_exists():
    """Already-extracted subtask (SUCCESS rows) must not re-fire."""
    with TestSessionLocal() as db:
        cust = Customer(name="x", code="X")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="P")
        db.add(proj); db.flush()
        db.add(Task(task_id="t-x", status="completed", customer_id=cust.id, project_id=proj.id))
        db.add(Subtask(task_id="t-x", subtask_id="s-1", status="completed"))
        # Row exists and is SUCCESS — terminal, no re-extraction needed.
        db.add(BrandMention(
            subtask_id="s-1", task_id="t-x", project_id=proj.id,
            customer_id=cust.id, brand_canonical="b",
            extract_status=ExtractStatus.SUCCESS,
        ))
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed"}]
        assert sync_module._pending_extraction_ids(db, items) == []


def test_pending_extraction_ignores_non_terminal_and_empty():
    """``processing`` / missing sid never trigger."""
    with TestSessionLocal() as db:
        db.add(Task(task_id="t-p", status="processing"))
        db.commit()

        items = [
            {"subTaskId": "s-1", "status": "processing"},
            {"subTaskId": "s-2", "status": "completed"},
            {"status": "completed"},
            {},
        ]
        assert sync_module._pending_extraction_ids(db, items) == ["s-2"]


def test_pending_extraction_mixed_already_and_pending():
    """Mixed payload: SUCCESS rows → skipped, PENDING/FAILED/missing → returned."""
    with TestSessionLocal() as db:
        cust = Customer(name="x", code="X")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="P")
        db.add(proj); db.flush()
        db.add(Task(task_id="t-mix", status="processing", customer_id=cust.id, project_id=proj.id))
        db.add(Subtask(task_id="t-mix", subtask_id="s-already", status="completed"))
        db.add(Subtask(task_id="t-mix", subtask_id="s-new", status="processing"))
        # s-already has a SUCCESS row — terminal, skipped.
        db.add(BrandMention(
            subtask_id="s-already", task_id="t-mix", project_id=proj.id,
            customer_id=cust.id, brand_canonical="b",
            extract_status=ExtractStatus.SUCCESS,
        ))
        db.commit()

        items = [
            {"subTaskId": "s-already", "status": "completed"},
            {"subTaskId": "s-new", "status": "completed"},
        ]
        assert sync_module._pending_extraction_ids(db, items) == ["s-new"]


def test_pending_extraction_retries_pending_row():
    """A subtask with a PENDING BrandMention row must re-fire (LLM never completed)."""
    with TestSessionLocal() as db:
        cust = Customer(name="x", code="X")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="P")
        db.add(proj); db.flush()
        db.add(Task(task_id="t-pend", status="processing", customer_id=cust.id, project_id=proj.id))
        db.add(Subtask(task_id="t-pend", subtask_id="s-1", status="completed"))
        db.add(BrandMention(
            subtask_id="s-1", task_id="t-pend", project_id=proj.id,
            customer_id=cust.id, brand_canonical="b",
            extract_status=ExtractStatus.PENDING,
        ))
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed"}]
        assert sync_module._pending_extraction_ids(db, items) == ["s-1"]


def test_pending_extraction_retries_failed_row():
    """A subtask with a FAILED BrandMention row must re-fire (LLM gave up, retry)."""
    with TestSessionLocal() as db:
        cust = Customer(name="x", code="X")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="P")
        db.add(proj); db.flush()
        db.add(Task(task_id="t-fail", status="processing", customer_id=cust.id, project_id=proj.id))
        db.add(Subtask(task_id="t-fail", subtask_id="s-1", status="completed"))
        db.add(BrandMention(
            subtask_id="s-1", task_id="t-fail", project_id=proj.id,
            customer_id=cust.id, brand_canonical="b",
            extract_status=ExtractStatus.FAILED,
            mention_count=0,
            extract_error="LLM 3次尝试均失败: timeout",
        ))
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed"}]
        assert sync_module._pending_extraction_ids(db, items) == ["s-1"]


def test_pending_extraction_skips_when_only_skipped_or_success():
    """A subtask whose rows are all SKIPPED (brand not mentioned) is terminal."""
    with TestSessionLocal() as db:
        cust = Customer(name="x", code="X")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="P")
        db.add(proj); db.flush()
        db.add(Task(task_id="t-skip", status="completed", customer_id=cust.id, project_id=proj.id))
        db.add(Subtask(task_id="t-skip", subtask_id="s-1", status="completed"))
        # Mix of SKIPPED + SUCCESS — both terminal, no re-fire.
        db.add_all([
            BrandMention(
                subtask_id="s-1", task_id="t-skip", project_id=proj.id,
                customer_id=cust.id, brand_canonical="b1",
                extract_status=ExtractStatus.SKIPPED,
            ),
            BrandMention(
                subtask_id="s-1", task_id="t-skip", project_id=proj.id,
                customer_id=cust.id, brand_canonical="b2",
                extract_status=ExtractStatus.SUCCESS,
            ),
        ])
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed"}]
        assert sync_module._pending_extraction_ids(db, items) == []


def test_pending_extraction_partial_incomplete():
    """One FAILED row among many SUCCESS — subtask still re-fires (FAILED row needs retry)."""
    with TestSessionLocal() as db:
        cust = Customer(name="x", code="X")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="P")
        db.add(proj); db.flush()
        db.add(Task(task_id="t-part", status="completed", customer_id=cust.id, project_id=proj.id))
        db.add(Subtask(task_id="t-part", subtask_id="s-1", status="completed"))
        db.add_all([
            BrandMention(
                subtask_id="s-1", task_id="t-part", project_id=proj.id,
                customer_id=cust.id, brand_canonical="b1",
                extract_status=ExtractStatus.SUCCESS,
            ),
            BrandMention(
                subtask_id="s-1", task_id="t-part", project_id=proj.id,
                customer_id=cust.id, brand_canonical="b2",
                extract_status=ExtractStatus.FAILED,
            ),
        ])
        db.commit()

        items = [{"subTaskId": "s-1", "status": "completed"}]
        assert sync_module._pending_extraction_ids(db, items) == ["s-1"]
