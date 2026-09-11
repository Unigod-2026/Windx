from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from functools import partial

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_session_factory
from app.models.common import now_local
from app.models.enums import CompetitorStatus, RegionStrategy, RunStatus, RunTrigger
from app.models.project import Project
from app.models.schedule import ScheduleRun
from app.models.task import Subtask, Task
from app.services.extraction import extract_brand_mentions
from app.services.llm_client import LLMClient, LLMError
from app.services.molizhishu_client import MolizhishuClient, MolizhishuError
from app.services.schedule_time import cooldown_key as _build_cooldown_key

logger = logging.getLogger("app.scheduler")


def _build_submit_client(settings) -> MolizhishuClient | LLMClient:
    """Pick the submit client based on ``Settings.llm_mode``.

    Two modes:

    - ``molizhishu`` — talk to the real remote API. The 5–30 minute
      per-batch latency still applies, but ``answerContent`` /
      ``referenceList`` / ``citationList`` come straight from molizhishu.
    - ``llm`` (default) — route through :class:`LLMClient` which talks
      to the configured Anthropic-compatible endpoint with the
      ``web_search`` / ``web_fetch`` / ``submit_answer`` tools and
      emits the same envelope shape. Used for local development so
      we don't pay the slow remote round-trip on every batch.

    Anything other than ``"molizhishu"`` is treated as ``"llm"`` so a
    typo in the env var doesn't accidentally hammer the remote.
    """
    mode = (settings.llm_mode or "").strip().lower()
    if mode == "molizhishu":
        return MolizhishuClient(
            base_url=settings.molizhishu_base_url,
            token=settings.molizhishu_token,
            timeout=settings.molizhishu_timeout_seconds,
        )
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_tool_rounds=settings.llm_max_tool_rounds,
        web_fetch_max_bytes=settings.llm_web_fetch_max_bytes,
    )


# Province-level codes used when a project's ``region_strategy`` is
# ``NATIONAL_RANDOM``. Eight major provinces cover the four macro regions;
# the Molizhishu API accepts at most one element so we sample one per run.
NATIONAL_RANDOM_POOL: tuple[str, ...] = (
    "110000",  # 北京
    "310000",  # 上海
    "330000",  # 浙江
    "320000",  # 江苏
    "440000",  # 广东
    "510000",  # 四川
    "420000",  # 湖北
    "370000",  # 山东
)


def cooldown_key(project_id: int, slot_index: int, when: datetime, *, mode: str = "") -> str:
    """Backwards-compatible wrapper around :func:`app.services.schedule_time.cooldown_key`.

    The canonical helper lives in ``schedule_time`` so the API and the
    scheduler can never disagree on the key shape — a mismatch would
    silently break the 5-minute cooldown dedupe between manual and cron
    triggers. We accept ``when`` as a positional arg to match the old
    signature (``cooldown_key(project_id, slot_index, now)``) and forward
    the new ``mode`` kwarg.
    """
    return _build_cooldown_key(project_id, slot_index, when, mode=mode)


def _resolve_region_code(project: Project, *, rand: random.Random | None = None) -> str | None:
    """Pick the region code that ``run_project`` will send to the remote.

    - ``FIXED`` + ``region_codes`` set → first element
    - ``NATIONAL_RANDOM`` → one sampled from the national pool
    - otherwise → ``None`` (the API accepts an unset regionCode)
    """
    if project.region_strategy is RegionStrategy.FIXED:
        if project.region_codes:
            return project.region_codes[0]
        return None
    sampler = rand or random
    return sampler.choice(NATIONAL_RANDOM_POOL)


_REMOTE_IN_FLIGHT = frozenset({"pending", "processing", "assigned"})
_REMOTE_SUCCESS = frozenset({"completed", "partial_completed"})
_REMOTE_FAILED = frozenset({"failed", "stopped", "error"})
REMOTE_TERMINAL: frozenset[str] = _REMOTE_SUCCESS | _REMOTE_FAILED


def is_terminal_status(remote: str | None) -> bool:
    """Whether the remote has reached a documented terminal state.

    A task in a terminal state no longer needs cheap ``get_task_status``
    polling; the sync layer should pull ``get_task_result`` once and then
    leave the row alone. Shared with ``app.services.sync`` so the
    polling loop and the scheduler never disagree on what's "done".
    """
    return remote in REMOTE_TERMINAL


def _remote_to_run_status(remote: str | None) -> RunStatus:
    """Map a remote task status string onto the closest local ``RunStatus``.

    The submit endpoint always returns ``pending`` (the task has been
    accepted but its subtasks haven't been executed yet) — callers that
    trust this mapping know to leave the run row in ``RUNNING`` until a
    polling/callback path flips it to a terminal value. Unknown values
    fall through to ``RUNNING`` rather than ``SUCCESS`` so the list view
    can't lie about progress we haven't actually observed.
    """
    if not remote:
        return RunStatus.RUNNING
    if remote in _REMOTE_SUCCESS:
        return RunStatus.SUCCESS
    if remote in _REMOTE_FAILED:
        return RunStatus.FAILED
    if remote in _REMOTE_IN_FLIGHT:
        return RunStatus.RUNNING
    return RunStatus.RUNNING


def run_project(
    project_id: int,
    slot_index: int,
    trigger_type: str | RunTrigger,
    *,
    mode: str = "",
    rand: random.Random | None = None,
    run_id: int | None = None,
) -> int | None:
    """Submit one project run and persist its local task summary.

    ``mode`` (``"fast"`` / ``"think"`` / ``""``) selects which half of
    the project's platforms to submit. Cron-triggered runs pass the mode
    that registered the firing job; manual triggers and the API's
    ``trigger_schedule`` endpoint pass ``""`` so every platform ships
    in one batch — operator-driven runs want the full picture, not
    half a project.

    ``rand`` is injectable so tests can pin the "national random" pick.

    When ``run_id`` is provided the caller has already inserted a
    ``ScheduleRun`` row (e.g. the manual-trigger API wants to return
    ``run_id`` synchronously) and this function picks it up instead of
    inserting a fresh one. Cron-triggered runs omit the argument.

    Status semantics: the remote API accepts the batch immediately and
    returns the freshly-minted ``taskId`` plus subtasks in
    ``status=pending``. The task itself is not done — the remote may
    still need 5-30 minutes to process the 33+ subtasks — so we map the
    remote status to a local ``RunStatus`` instead of unconditionally
    flipping the row to ``SUCCESS``. Only the documented terminal
    statuses (``completed`` / ``partial_completed``) become
    ``SUCCESS``; everything in-flight stays ``RUNNING`` and any
    failure-mode status becomes ``FAILED``. Until a polling/callback
    path actually advances the row, ``RUNNING`` is the truthful state.
    """
    db = get_session_factory()()
    now = now_local()
    run: ScheduleRun | None = None
    if run_id is not None:
        run = db.get(ScheduleRun, run_id)
        if run is None:
            db.close()
            raise RuntimeError(f"schedule run {run_id} not found")
        run.started_at = now
        run.status = RunStatus.RUNNING
        if mode:
            run.mode = mode
        db.commit()
        db.refresh(run)
    else:
        run = ScheduleRun(
            project_id=project_id,
            slot_index=slot_index,
            trigger_type=trigger_type,
            mode=mode,
            triggered_at=now,
            started_at=now,
            status=RunStatus.RUNNING,
            cooldown_key=cooldown_key(project_id, slot_index, now, mode=mode),
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
                selectinload(Project.platforms),
                selectinload(Project.project_competitors),
            )
            .filter(Project.id == project_id)
            .one_or_none()
        )
        if project is None:
            raise RuntimeError("project not found")

        prompts = [item.prompt for item in project.prompts]
        if not prompts:
            raise RuntimeError("prompts 为空")
        # The remote expects ``mode`` to be the LLM mode
        # (standard/reasoning/search/reasoning_search — see
        # https://github.com/molizhishu/molizhishu-api-pub/blob/main/docs/api/submit-task.md).
        # Earlier revisions mistakenly forwarded ``delivery_mode.value``
        # ("web"/"mobile") into ``mode``; that ships a value the live endpoint
        # silently drops or rejects. ``delivery_mode`` (web/mobile surface)
        # is intentionally NOT forwarded — the live remote has no surface
        # field and the legacy docs example doesn't include one.
        #
        # ``mode`` (the schedule mode kwarg) selects which platform rows
        # ship: ``"fast"`` keeps rows with ``thinking_mode=False``,
        # ``"think"`` keeps ``thinking_mode=True``, ``""`` keeps both —
        # matches the cron job's split vs the manual trigger's "all at
        # once" semantics. The platform list is intentionally derived
        # here rather than at job-registration time so a fast/think row
        # that's added between two cron fires lands on the next fire
        # without needing a reload.
        want_thinking = mode == "think"
        platform_rows = [
            item
            for item in project.platforms
            if mode == "" or bool(item.thinking_mode) == want_thinking
        ]
        platforms = [
            {
                # ``platform_code`` is the resolved API platform string for
                # both web and mobile rows (web: ``doubao``, mobile:
                # ``doubao_mobile`` / ``baidu_mobile``); always forward it.
                "platform": item.platform_code,
                "mode": item.mode,
                "screenshot": item.screenshot,
                "thinkingMode": item.thinking_mode,
            }
            for item in platform_rows
        ]
        if not platforms:
            raise RuntimeError("platforms 为空")

        settings = get_settings()
        # Validate before submit so the admin sees the exact problem
        # (which row has which bad value) instead of a generic prod-side
        # rejection. Only meaningful for the molizhishu backend; the local
        # LLM client accepts arbitrary platform/mode strings.
        if (settings.llm_mode or "").strip().lower() == "molizhishu":
            from app.services.molizhishu_client import validate_platforms

            validate_platforms(platforms)
        payload: dict = {"prompts": prompts, "platforms": platforms}
        # Brand hint for the remote's brand-mention extraction
        # (``mentionPosition`` / ``sentiment`` / ``mentionContext`` /
        # ``allRankings`` / ``competitorRankings``). Per the official
        # ``POST /task/batch/shared`` schema, ``monitorKeywords`` is the
        # single monitor brand string and ``monitorKeywordAliases`` is a
        # flat list of its short-forms; ``competitors`` is a structured
        # list of ``{name, aliases}`` objects. Without these the remote
        # leaves every brand field empty. ``brand`` is non-empty in
        # practice (project memory ``project_brand_nonempty``) but the
        # ``if brand`` guard stays so a brandless project never sends a
        # confusing half-payload.
        brand = (project.brand or "").strip()
        aliases = [a for a in (project.aliases or []) if a and a.strip()]
        if brand:
            payload["monitorKeywords"] = brand
            payload["monitorKeywordAliases"] = aliases
        competitor_pairs: list[tuple[str, list[str]]] = [
            ((c.name or "").strip(), [a for a in (c.aliases or []) if a and a.strip()])
            for c in project.project_competitors
            if c.status == CompetitorStatus.CONFIRMED
        ]
        if competitor_pairs:
            payload["competitors"] = [
                {"name": name, "aliases": als}
                for name, als in competitor_pairs
                if name
            ]
        # Callback URL is intentionally not forwarded: this build runs the
        # LLM backend synchronously so there's no async result to push.
        region = _resolve_region_code(project, rand=rand)
        if region:
            payload["regionCode"] = [region]

        # The LLM client also wants the monitor brand + its aliases so it
        # can render them into the prompt itself (a separate concern
        # from the API-side brand hint above). The remote molizhishu
        # client accepts and ignores these kwargs; the local LLM client
        # uses them to build the system prompt per
        # ``render_monitor_prompt``.
        client = _build_submit_client(settings)
        data = client.submit_task_sync(payload, brand=brand, aliases=aliases)

        task = Task(
            task_id=data["taskId"],
            status=data.get("status", "pending"),
            prompts_json=prompts,
            platforms_json=platforms,
            region_code_json=[region] if region else None,
            callback_url=None,
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
        subtask_ids: list[str] = []
        for item in data.get("subTaskList", []):
            sid = item["subTaskId"]
            subtask_ids.append(sid)
            db.add(
                Subtask(
                    task_id=task.task_id,
                    subtask_id=sid,
                    platform=item.get("platform"),
                    mode=item.get("mode"),
                    prompt=item.get("prompt"),
                    status=item.get("status", "pending"),
                    time=item.get("time"),
                    page_screenshot=item.get("pageScreenshot"),
                    answer_content=item.get("answerContent"),
                    reference_list_json=item.get("referenceList") or None,
                    citation_list_json=item.get("citationList") or None,
                    error_message=item.get("errorMessage"),
                    raw_result_json=item,
                )
            )
        run.task_id = task.task_id
        # Reflect the remote state: if the remote only just accepted the
        # submission (``status=pending``), the run is still in flight and
        # must stay RUNNING — otherwise the project list would lie and
        # show "成功" while 0/33 subtasks are still unprocessed. Only a
        # genuine terminal status from the API (``completed`` /
        # ``partial_completed``) marks the run SUCCESS.
        remote_status = data.get("status")
        mapped = _remote_to_run_status(remote_status)
        run.status = mapped
        # ``finished_at`` only makes sense once the run is actually done;
        # for in-flight runs we leave it None so the UI can render "—".
        if mapped in (RunStatus.SUCCESS, RunStatus.FAILED):
            run.finished_at = now_local()
        db.commit()
        logger.info(
            "run_project ok project_id=%s run_id=%s task_id=%s status=%s subtasks=%s",
            project_id,
            run.id,
            task.task_id,
            remote_status,
            len(subtask_ids),
        )
        # Kick off the brand-mention extraction pipeline for every subtask
        # we just landed. Each call writes ``geo_brand_mentions`` rows in
        # its own session and never raises — a failing extraction is
        # recorded as ``extract_status='failed'`` on the row so the UI
        # can show "抽取失败" honestly instead of pretending the data is
        # missing. The local session above is closed by the ``finally``
        # block before we get here.
        #
        # Molizhishu mode is gated out: its submit endpoint returns
        # ``answer_content=None`` (the real answer arrives 5–30 minutes
        # later via the polling sync). Running extraction here would
        # burn an LLM pass on every brand against an empty string and
        # mark the row ``skipped`` forever — the polling sync is
        # responsible for re-running extraction once the real
        # ``answerContent`` lands (see ``sync._apply_full_subtask_payload``).
        mode = (settings.llm_mode or "").strip().lower()
        if mode != "molizhishu":
            for sid in subtask_ids:
                try:
                    extract_brand_mentions(sid)
                except Exception as exc:  # noqa: BLE001 - isolation contract
                    logger.exception(
                        "extract hook failed project_id=%s subtask_id=%s err=%s",
                        project_id,
                        sid,
                        exc,
                    )
        return run.id
    except Exception as exc:  # noqa: BLE001 - every execution failure must update the run row
        logger.exception(
            "run_project failed project_id=%s run_id=%s err=%s",
            project_id,
            run.id if run else None,
            exc,
        )
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
    project_id: int,
    slot_index: int,
    trigger_type: str | RunTrigger,
    mode: str = "",
    *,
    run_id: int | None = None,
) -> int | None:
    # ``mode`` is positional (not kwarg-only) so APScheduler's
    # ``check_callable_args`` accepts the 4-arg ``args`` list built by
    # ``scheduler_runtime.reload_jobs``. Manual / API callers that don't
    # care about the mode pass the empty string by default.
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(
            run_project,
            project_id,
            slot_index,
            trigger_type,
            mode=mode,
            run_id=run_id,
        ),
    )
