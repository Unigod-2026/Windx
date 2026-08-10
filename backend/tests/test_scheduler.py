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
        if with_prompts:
            project.prompts = [
                ProjectPrompt(prompt="second question", sort=2),
                ProjectPrompt(prompt="first question", sort=1),
            ]
        project.keywords = [
            ProjectKeyword(keyword="beta", sort=2),
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

    async def fake_submit(self, payload):
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

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task", fake_submit)
    monkeypatch.setattr(scheduler, "now_local", lambda: datetime(2026, 8, 10, 9, 4))
    scheduler.get_settings().molizhishu_callback_url = "https://callback.test/hook"

    run_id = scheduler.run_project(project_id, 1, RunTrigger.CRON)

    assert captured["payload"] == {
        "prompts": ["first question", "second question"],
        "platforms": [
            {"platform": "deepseek", "mode": "search", "screenshot": 1}
        ],
        "monitorKeywords": "alpha,beta",
        "callbackUrl": "https://callback.test/hook",
    }
    with TestSessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        task = db.scalar(select(Task).where(Task.schedule_run_id == run_id))
        subtask = db.scalar(select(Subtask).where(Subtask.task_id == task.id))
        assert run.status == RunStatus.SUCCESS
        assert run.task_id == task.id
        assert task.customer_id is not None
        assert task.project_id == project_id
        assert task.task_id == "remote-1"
        assert task.prompts_json == ["first question", "second question"]
        assert task.platforms_json == [
            {"platform": "deepseek", "mode": "search", "screenshot": 1}
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

    async def fake_submit(self, payload):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task", fake_submit)

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

    async def fake_submit(self, payload):
        return {
            "taskId": "remote-1",
            "status": "pending",
            "totalTask": 0,
            "subTaskList": [],
        }

    monkeypatch.setattr(scheduler.MolizhishuClient, "submit_task", fake_submit)

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

    def fake_run_project(project_id, slot_index, trigger_type):
        captured["args"] = (project_id, slot_index, trigger_type)
        return 42

    monkeypatch.setattr(scheduler, "run_project", fake_run_project)

    assert await scheduler.run_project_async(3, 0, RunTrigger.MANUAL) == 42
    assert captured["args"] == (3, 0, RunTrigger.MANUAL)
