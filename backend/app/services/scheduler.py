from __future__ import annotations

import asyncio
from datetime import datetime
from functools import partial

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_session_factory
from app.models.common import now_local
from app.models.enums import RunStatus, RunTrigger
from app.models.project import Project
from app.models.schedule import ScheduleRun
from app.models.task import Subtask, Task
from app.services.molizhishu_client import MolizhishuClient


def cooldown_key(project_id: int, slot_index: int, when: datetime) -> str:
    return (
        f"project-{project_id}-slot-{slot_index}-"
        f"{when.strftime('%Y%m%d%H')}{when.minute // 5}"
    )


def run_project(
    project_id: int, slot_index: int, trigger_type: str | RunTrigger
) -> int | None:
    """Submit one project run and persist its local task summary."""
    db = get_session_factory()()
    now = now_local()
    run = ScheduleRun(
        project_id=project_id,
        slot_index=slot_index,
        trigger_type=trigger_type,
        triggered_at=now,
        started_at=now,
        status=RunStatus.RUNNING,
        cooldown_key=cooldown_key(project_id, slot_index, now),
    )
    db.add(run)
    try:
        db.commit()
        db.refresh(run)
    except IntegrityError:
        db.rollback()
        db.close()
        return None

    try:
        project = (
            db.query(Project)
            .options(
                selectinload(Project.prompts),
                selectinload(Project.keywords),
                selectinload(Project.platforms),
            )
            .filter(Project.id == project_id)
            .one_or_none()
        )
        if project is None:
            raise RuntimeError("project not found")

        prompts = [item.prompt for item in project.prompts]
        if not prompts:
            raise RuntimeError("prompts 为空")
        keywords = [item.keyword for item in project.keywords]
        platforms = [
            {
                "platform": item.platform,
                "mode": item.mode,
                "screenshot": item.screenshot,
            }
            for item in project.platforms
        ]
        if not platforms:
            raise RuntimeError("platforms 为空")

        settings = get_settings()
        payload = {"prompts": prompts, "platforms": platforms}
        if keywords:
            payload["monitorKeywords"] = ",".join(keywords)
        if settings.molizhishu_callback_url:
            payload["callbackUrl"] = settings.molizhishu_callback_url

        client = MolizhishuClient(
            settings.molizhishu_base_url,
            settings.molizhishu_token,
            settings.molizhishu_timeout_seconds,
        )
        data = asyncio.run(client.submit_task(payload))

        task = Task(
            task_id=data["taskId"],
            status=data.get("status", "pending"),
            prompts_json=prompts,
            platforms_json=platforms,
            callback_url=data.get("callbackUrl"),
            total_items=data.get("totalTask"),
            poll_url=data.get("pollUrl"),
            raw_request_json=payload,
            raw_response_json=data,
            customer_id=project.customer_id,
            project_id=project.id,
            schedule_run_id=run.id,
        )
        db.add(task)
        db.flush()
        for item in data.get("subTaskList", []):
            db.add(
                Subtask(
                    task_id=task.id,
                    subtask_id=item["subTaskId"],
                    platform=item.get("platform"),
                    mode=item.get("mode"),
                    prompt=item.get("prompt"),
                    status=item.get("status", "pending"),
                )
            )
        run.task_id = task.id
        run.status = RunStatus.SUCCESS
        run.finished_at = now_local()
        db.commit()
        return run.id
    except Exception as exc:  # noqa: BLE001 - every execution failure must update the run row
        db.rollback()
        run = db.get(ScheduleRun, run.id)
        run.status = RunStatus.FAILED
        run.error_message = str(exc)[:1000]
        run.finished_at = now_local()
        db.commit()
        return run.id
    finally:
        db.close()


async def run_project_async(
    project_id: int, slot_index: int, trigger_type: str | RunTrigger
) -> int | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(run_project, project_id, slot_index, trigger_type)
    )
