# SQLite models persist naive Asia/Shanghai wall-clock datetimes.
# ruff: noqa: DTZ001

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from app.db import Base
from app.models import Customer, Project, ProjectKeyword, ProjectPlatform, ProjectPrompt
from app.models.enums import RunStatus, RunTrigger
from app.models.schedule import ScheduleRun
from app.models.task import Subtask, Task
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
    monkeypatch.setattr("app.services.scheduler.get_session_factory", lambda: TestSessionLocal)
    yield
    Base.metadata.drop_all(test_engine)


def _create_project(*, with_prompts: bool = True) -> int:
    with TestSessionLocal() as db:
        customer = Customer(name="Acme", code="ACME")
        project = Project(customer=customer, name="Monitor", code="MON")
        db.add(project)
        db.flush()
        # Parent collections are viewonly=True (no-FK convention) — see
        # CLAUDE.md "外键约定" — so we add children explicitly with the
        # project_id column populated.
        children: list = []
        if with_prompts:
            children += [
                ProjectPrompt(project_id=project.id, prompt="second question", sort=2),
                ProjectPrompt(project_id=project.id, prompt="first question", sort=1),
            ]
        children += [
            ProjectKeyword(project_id=project.id, keyword="beta", sort=2),
            ProjectKeyword(project_id=project.id, keyword="alpha", sort=1),
            ProjectPlatform(
                project_id=project.id,
                platform="deepseek",
                mode="search",
                screenshot=1,
                sort=1,
            ),
        ]
        db.add_all(children)
        db.commit()
        return project.id


@pytest.mark.asyncio
async def test_submit_task_posts_bearer_json_and_returns_data(monkeypatch):
    from app.services.molizhishu_client import MolizhishuClient

    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": 200,
                "message": "ok",
                "data": {"taskId": "remote-1", "status": "pending"},
            },
        )

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.molizhishu_client.httpx.AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    payload = {"prompts": ["question"], "platforms": []}

    data = await MolizhishuClient("https://example.test/base/", "secret", 9).submit_task(
        payload
    )

    request = seen["request"]
    assert request.url == "https://example.test/base/task/batch/shared"
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["Content-Type"] == "application/json"
    assert request.read() == b'{"prompts":["question"],"platforms":[]}'
    assert data == {"taskId": "remote-1", "status": "pending"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "response_body", "expected_code", "expected_message"),
    [
        (200, {"success": False, "code": 500, "message": "Token invalid"}, 500, "Token invalid"),
        (503, {"code": 500001, "message": "gateway unavailable"}, 500001, "gateway unavailable"),
    ],
)
async def test_submit_task_raises_molizhishu_error(
    monkeypatch, status, response_body, expected_code, expected_message
):
    from app.services.molizhishu_client import MolizhishuClient, MolizhishuError

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json=response_body)
    )
    monkeypatch.setattr(
        "app.services.molizhishu_client.httpx.AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(MolizhishuError) as exc_info:
        await MolizhishuClient("https://example.test", "secret").submit_task({})

    error = exc_info.value
    assert error.code == expected_code
    assert error.message == expected_message
    assert error.http_status == status
    assert error.body == response_body


def test_cooldown_key_uses_five_minute_bucket():
    from app.services.scheduler import cooldown_key

    assert cooldown_key(7, 2, datetime(2026, 8, 10, 9, 4)) == (
        "project-7-slot-2-20260810090"
    )
    assert cooldown_key(7, 2, datetime(2026, 8, 10, 9, 5)) == (
        "project-7-slot-2-20260810091"
    )


def test_run_project_submits_project_configuration_and_persists_results(monkeypatch):
    from app.services import scheduler

    project_id = _create_project()
    captured = {}

    def fake_submit(self, payload, **_kwargs):
        captured["payload"] = payload
        return {
            "taskId": "remote-1",
            "status": "pending",
            "totalTask": 1,
            "pollUrl": "/task/status/remote-1",
            "callbackUrl": "https://callback.test/hook",
            "subTaskList": [
                {
                    "subTaskId": "sub-1",
                    "prompt": "first question",
                    "platform": "deepseek",
                    "mode": "search",
                    "status": "pending",
                }
            ],
        }

    # Patch both clients so the test is robust against either branch of
    # ``_build_submit_client`` (Settings.llm_mode).
    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task_sync", fake_submit)
    monkeypatch.setattr(scheduler.LLMClient, "submit_task_sync", fake_submit)
    monkeypatch.setattr(scheduler, "now_local", lambda: datetime(2026, 8, 10, 9, 4))

    run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)

    assert captured["payload"] == {
        "prompts": ["first question", "second question"],
        "platforms": [
            {"platform": "deepseek", "mode": "search", "screenshot": 1, "thinkingMode": False}
        ],
        "monitorKeywords": "alpha,beta",
    }
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        task = db.scalar(select(Task).where(Task.schedule_run_id == run_id))
        subtask = db.scalar(select(Subtask).where(Subtask.task_id == task.task_id))
        # The remote returns ``status=pending`` from submit_task — the task
        # has been accepted but its subtasks haven't been processed yet.
        # The local run row must mirror the remote state and stay RUNNING
        # until something polls/callbacks us to advance it; otherwise the
        # project list would show "成功" while 0/N subtasks are unprocessed.
        assert run.status == RunStatus.RUNNING
        assert run.finished_at is None
        assert run.task_id == task.task_id
        assert task.customer_id is not None
        assert task.project_id == project_id
        assert task.task_id == "remote-1"
        assert task.prompts_json == ["first question", "second question"]
        assert task.platforms_json == [
            {"platform": "deepseek", "mode": "search", "screenshot": 1, "thinkingMode": False}
        ]
        assert task.total_items == 1
        assert task.raw_request_json == captured["payload"]
        assert task.raw_response_json["taskId"] == "remote-1"
        assert subtask.subtask_id == "sub-1"
        assert subtask.prompt == "first question"


def test_run_project_marks_missing_prompts_failed_without_remote_call(monkeypatch):
    from app.services import scheduler

    project_id = _create_project(with_prompts=False)
    called = False

    def fake_submit(self, payload, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task_sync", fake_submit)
    monkeypatch.setattr(scheduler.LLMClient, "submit_task_sync", fake_submit)

    run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)

    assert called is False
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        assert run.status == RunStatus.FAILED
        assert run.error_message == "prompts 为空"


def test_run_project_returns_none_on_cooldown_collision(monkeypatch):
    from app.services import scheduler

    project_id = _create_project()
    fixed_now = datetime(2026, 8, 10, 9, 4)
    monkeypatch.setattr(scheduler, "now_local", lambda: fixed_now)

    def fake_submit(self, payload, **_kwargs):
        return {
            "taskId": "remote-1",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task_sync", fake_submit)
    monkeypatch.setattr(scheduler.LLMClient, "submit_task_sync", fake_submit)

    first_run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)
    second_run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)

    assert first_run_id is not None
    assert second_run_id is None
    with TestSessionLocal() as db:
        assert db.scalar(select(ScheduleRun).where(ScheduleRun.id == first_run_id))
        assert len(db.scalars(select(ScheduleRun)).all()) == 1


@pytest.mark.asyncio
async def test_run_project_async_uses_executor(monkeypatch):
    from app.services import scheduler

    captured = {}

    def fake_run_project(project_id, slot_index, trigger_type, **kwargs):
        captured["args"] = (project_id, slot_index, trigger_type, kwargs)
        return 42

    monkeypatch.setattr(scheduler, "run_project", fake_run_project)

    assert await scheduler.run_project_async(3, 0, RunTrigger.MANUAL) == 42
    assert captured["args"][:3] == (3, 0, RunTrigger.MANUAL)


@pytest.mark.parametrize(
    "remote_status, expected",
    [
        # Submit endpoint contract: ``status=pending`` is what we get back
        # the moment the remote accepts the batch. The local run must NOT
        # flip to SUCCESS — its subtasks haven't been processed yet.
        ("pending", RunStatus.RUNNING),
        ("processing", RunStatus.RUNNING),
        ("assigned", RunStatus.RUNNING),
        # Genuine terminal statuses from the remote. ``partial_completed``
        # is treated as SUCCESS because the local RunStatus enum has no
        # ``PARTIAL`` member; some subtasks succeeded, so the run did its
        # job. ``stopped`` and ``error`` map to FAILED.
        ("completed", RunStatus.SUCCESS),
        ("partial_completed", RunStatus.SUCCESS),
        ("failed", RunStatus.FAILED),
        ("stopped", RunStatus.FAILED),
        ("error", RunStatus.FAILED),
        # Defensive: a missing/unknown status must NOT lie — default to
        # RUNNING so the UI keeps the badge honest.
        (None, RunStatus.RUNNING),
        ("some-future-value", RunStatus.RUNNING),
    ],
)
def test_run_project_maps_remote_status_onto_local_run_status(
    monkeypatch, remote_status, expected
):
    """The submit response's ``status`` field decides the local row.

    Regression for the bug where ``run_project`` hard-coded
    ``run.status = SUCCESS`` right after submit, so the project list
    showed "成功" while 0/N subtasks were still unprocessed.
    """
    from app.services import scheduler

    project_id = _create_project()
    fixed_now = datetime(2026, 8, 10, 9, 4)
    monkeypatch.setattr(scheduler, "now_local", lambda: fixed_now)

    response: dict = {
        "taskId": "remote-1",
        "totalTask": 1,
        "subTaskList": [
            {"subTaskId": "sub-1", "prompt": "q", "platform": "deepseek", "mode": "search"},
        ],
    }
    if remote_status is not None:
        response["status"] = remote_status

    def fake_submit(self, payload, **_kwargs):
        return response

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task_sync", fake_submit)
    monkeypatch.setattr(scheduler.LLMClient, "submit_task_sync", fake_submit)

    run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)
    assert run_id is not None
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        assert run.status == expected
        if expected in (RunStatus.SUCCESS, RunStatus.FAILED):
            assert run.finished_at == fixed_now
        else:
            assert run.finished_at is None


# --------------------------------------------------------------------------
# Extraction hook gating
# --------------------------------------------------------------------------


def _patch_submit_with_answers(monkeypatch, *, answers: dict[str, str]):
    """Patch both clients to return full subtask rows with answerContent.

    ``answers`` is keyed by ``subTaskId`` so the test can stage a
    different payload for each subtask.
    """
    def fake_submit(self, payload, **_kwargs):
        sub_tasks = [
            {
                "subTaskId": sid,
                "prompt": payload["prompts"][i] if i < len(payload["prompts"]) else "q",
                "platform": "deepseek",
                "mode": "search",
                "status": "completed",
                "answerContent": answers.get(sid, ""),
            }
            for i, sid in enumerate(["sub-1", "sub-2"])
        ]
        return {
            "taskId": "remote-1",
            "status": "completed",
            "totalTask": len(sub_tasks),
            "subTaskList": sub_tasks,
        }

    from app.services import scheduler

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task_sync", fake_submit)
    monkeypatch.setattr(scheduler.LLMClient, "submit_task_sync", fake_submit)


def test_run_project_skips_extraction_in_molizhishu_mode(monkeypatch):
    """``LLM_MODE=molizhishu`` ⇒ ``extract_brand_mentions`` must NOT run.

    In molizhishu mode the submit response carries empty
    ``answerContent`` (the real answer arrives 5–30 minutes later via
    polling). Running extraction here would burn an LLM pass on every
    brand against an empty string and mark the row ``skipped``
    forever — the polling sync is responsible for re-running
    extraction once the real ``answerContent`` lands.
    """
    from app.config import get_settings
    from app.services import scheduler

    monkeypatch.setenv("LLM_MODE", "molizhishu")
    get_settings.cache_clear()

    project_id = _create_project()
    _patch_submit_with_answers(monkeypatch, answers={"sub-1": "", "sub-2": ""})

    extraction_calls: list[str] = []
    def fake_extract(sid):
        extraction_calls.append(sid)
        from app.services.extraction import ExtractionResult
        return ExtractionResult(sid, 0, 0, 0)
    monkeypatch.setattr(scheduler, "extract_brand_mentions", fake_extract)

    scheduler.run_project(project_id, 1, RunTrigger.CRON)

    assert extraction_calls == [], (
        "extract_brand_mentions must NOT be called in molizhishu mode"
    )


def test_run_project_triggers_extraction_in_llm_mode(monkeypatch):
    """``LLM_MODE=llm`` ⇒ ``extract_brand_mentions`` IS called per subtask.

    LLMClient returns the full payload synchronously, so the
    ``answer_content`` is real and the extraction hook fires
    immediately after the run row is committed.
    """
    from app.config import get_settings
    from app.services import scheduler

    monkeypatch.setenv("LLM_MODE", "llm")
    get_settings.cache_clear()

    project_id = _create_project()
    _patch_submit_with_answers(
        monkeypatch, answers={"sub-1": "answer-1", "sub-2": "answer-2"}
    )

    extraction_calls: list[str] = []
    def fake_extract(sid):
        extraction_calls.append(sid)
        from app.services.extraction import ExtractionResult
        return ExtractionResult(sid, 0, 0, 0)
    monkeypatch.setattr(scheduler, "extract_brand_mentions", fake_extract)

    scheduler.run_project(project_id, 1, RunTrigger.CRON)

    assert sorted(extraction_calls) == ["sub-1", "sub-2"]
