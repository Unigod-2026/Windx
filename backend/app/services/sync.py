"""Background polling that refreshes in-flight ``geo_tasks`` rows.

The molizhishu API accepts a batch submission and returns
``status=pending`` immediately; the actual subtask execution takes
5–60 minutes (per ``docs/api/get-task-status.md``). Without Callback,
this polling loop is the only path that advances the row from
``pending`` → ``completed`` / ``partial_completed`` and pulls the
heavy ``answerContent`` payload.

Implementation notes:

- The functions are sync; APScheduler's ``AsyncIOScheduler`` invokes
  them via ``run_in_executor`` (see ``app.main.lifespan``). This
  matches the ``run_project`` / ``run_project_async`` pattern.
- Each task refresh runs in its own session and rolls back on
  failure — one bad task can't poison the rest of the batch.
- ``_in_flight`` blocks concurrent refreshes for the same ``task_id``
  so the APScheduler tick never collides with a callback or manual
  sync (``api调用prompt.md`` §六 "同一个 taskId 必须避免并发同步").
- ``_backoff_until`` / ``_backoff_count`` apply per-task exponential
  backoff on transport failures — ``docs/api/errors.md`` §处理建议
  says "不要快速无限重试".
- Every poll writes a ``geo_compensation_events`` row with
  ``source='background-sync:poll'`` and per-task failures write
  ``source='background-sync:refresh'`` (matches the convention in
  ``docs/api/callback.md``).
- Each remote call emits a ``[molizhishu]`` log line in the shape
  required by ``docs/api/errors.md`` §日志建议 so the operator can
  grep the log without consulting the DB. Token never reaches the log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session_factory
from app.models.common import now_local
from app.models.enums import ExtractStatus, RunStatus
from app.models.schedule import ScheduleRun
from app.models.task import CompensationEvent, Subtask, Task
from app.models.project import BrandMention
from app.services.extraction import extract_brand_mentions
from app.services.molizhishu_client import MolizhishuClient, MolizhishuError
from app.services.scheduler import REMOTE_TERMINAL, is_terminal_status

logger = logging.getLogger("app.sync")

SOURCE_POLL = "background-sync:poll"
SOURCE_REFRESH = "background-sync:refresh"
SOURCE_RESULT = "background-sync:result"
_TERMINAL_LOCAL = (RunStatus.SUCCESS, RunStatus.FAILED)
# ``docs/api/get-task-status.md`` line 42 — any of these subtask
# statuses means the remote has produced a final payload worth pulling
# via ``GET /task/result`` even if the main task is still in flight.
_SUBTASK_TERMINAL = frozenset({"completed", "failed", "error", "stopped"})
# Backoff ladder (seconds) applied after successive transport-level
# failures for the same ``task_id``. ``docs/api/errors.md`` §处理建议
# says HTTP 502/503/504 retries 3× exponential — we cap at 5 min so a
# bad token doesn't lock the row out forever.
_BACKOFF_LADDER = (60, 120, 300)
# In-process guards — see the module docstring for the rationale.
_in_flight: set[str] = set()
_backoff_until: dict[str, "object"] = {}
_backoff_count: dict[str, int] = {}


@dataclass(frozen=True)
class SyncResult:
    polled: int
    refreshed: int
    advanced: int
    failed: int
    # ``extracted`` counts subtasks whose ``answer_content`` was newly
    # written this tick and for which we kicked off the brand-mention
    # extraction pipeline (see :func:`_refresh_task`). Each call
    # opens its own session and never raises, so this is purely
    # informational — operators can spot at a glance whether the
    # pipeline is doing useful work on a given tick.
    extracted: int


def sync_pending_tasks(*, limit: int | None = None) -> SyncResult:
    """Refresh every in-flight ``geo_tasks`` row, up to ``limit``.

    For each candidate task_id we call :func:`_refresh_task`, which
    owns its own DB session, Molizhishu client, and structured logging.
    The ``SyncResult`` count distinguishes ``advanced`` (we moved a
    ``ScheduleRun`` from RUNNING to a terminal state) from
    ``refreshed`` (status-only or full-result pull that didn't change
    the run).

    Two selection passes run each tick:

    1. ``_select_in_flight_task_ids`` — anything still in flight from
       molizhishu's perspective (``status`` not in REMOTE_TERMINAL).
       These are the rows that actually need a remote call. ``polled``
       counts this pass only.
    2. ``_select_orphan_terminal_runs`` — main ``Task`` row is already
       terminal but its linked ``ScheduleRun`` is still RUNNING. No
       remote call; the local advance promotes the run. ``advanced``
       counts this pass too.
    """
    settings = get_settings()
    effective_limit = limit if limit is not None else settings.molizhishu_sync_limit

    factory = get_session_factory()
    db = factory()
    try:
        in_flight = _select_in_flight_task_ids(db, effective_limit)
        orphan_runs = _select_orphan_terminal_runs(db, effective_limit)
        # ``polled`` only counts remote polls — orphan advances are
        # purely local, so they don't belong in the "polled" bucket.
        polled = len(in_flight)
        db.commit()
    finally:
        db.close()

    if polled == 0 and not orphan_runs:
        return SyncResult(polled=0, refreshed=0, advanced=0, failed=0, extracted=0)

    refreshed = advanced = failed = extracted = 0
    # Orphan-run pass first — purely local work, no remote calls.
    # We advance directly instead of routing through ``_refresh_task``
    # so this code path can never accidentally hit the remote for a
    # row that's already terminal on our side.
    for task_id in orphan_runs:
        if task_id in _in_flight:
            continue
        if _advance_orphan_run(task_id):
            advanced += 1
        refreshed += 1
    # In-flight pass — these are the rows that may call the remote.
    for task_id in in_flight:
        if _is_in_backoff(task_id):
            # Per ``docs/api/errors.md`` §处理建议 — don't fast-retry
            # a remote that just failed; wait the ladder out.
            continue
        if task_id in _in_flight:
            # Already being refreshed by another path (callback, manual
            # sync, or a previous tick that's running long).
            continue
        outcome, extracted_count = _refresh_task(task_id)
        if outcome == "advanced":
            refreshed += 1
            advanced += 1
        elif outcome == "refreshed":
            refreshed += 1
        else:
            failed += 1
        extracted += extracted_count

    return SyncResult(
        polled=polled,
        refreshed=refreshed,
        advanced=advanced,
        failed=failed,
        extracted=extracted,
    )


def _is_in_backoff(task_id: str) -> bool:
    deadline = _backoff_until.get(task_id)
    if deadline is None:
        return False
    return now_local() < deadline


def _select_in_flight_task_ids(db, limit: int) -> list[str]:
    """Return ``task_id``s that need a remote call.

    Per ``docs/api/get-task-status.md`` §调用约定 only the in-flight
    rows need ``GET /task/status``. Sorted by ``created_local_at``
    ASC so the oldest rows (most likely to be done) are processed
    first.
    """
    stmt = (
        select(Task.task_id)
        .where(
            (Task.status.is_(None))
            | (~Task.status.in_(REMOTE_TERMINAL))
        )
        .order_by(Task.created_local_at.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def _select_orphan_terminal_runs(db, limit: int) -> list[str]:
    """Find tasks whose main row is terminal but the linked run
    hasn't caught up.

    These rows don't need a remote call — the local fast path in
    :func:`_refresh_task` will see ``is_terminal_status(task.status)
    and _local_subtasks_complete(db, task_id)`` and just advance the
    run. The selection exists so that a path which wrote ``Task.status
    = completed`` directly (e.g. LLMClient's synchronous submit, or a
    manual override) eventually cleans up the linked ScheduleRun.
    """
    stmt = (
        select(Task.task_id)
        .join(ScheduleRun, ScheduleRun.id == Task.schedule_run_id)
        .where(Task.status.in_(REMOTE_TERMINAL))
        .where(ScheduleRun.status == RunStatus.RUNNING)
        .order_by(Task.created_local_at.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


# ``REMOTE_TERMINAL`` lives in ``app.services.scheduler`` so the
# "submit" path (``run_project``) and the "refresh" path (``sync``)
# share one source of truth for what's done; redefining it here
# would let the two drift.


def _refresh_task(task_id: str) -> tuple[str, int]:
    """Refresh a single task; return ``(outcome, extracted_count)``.

    ``outcome`` is one of:

    ``advanced``  — the row reached a terminal state (locally or via
                    remote) and we moved the linked ``ScheduleRun`` out
                    of RUNNING.
    ``refreshed`` — we pulled status (and possibly the heavy result
                    payload) but didn't change the run state.
    ``failed``    — the remote call blew up (network / business);
                    backoff + ``compensation_events`` row written.

    ``extracted_count`` reports how many subtasks newly received a
    non-empty ``answer_content`` this tick and for which we kicked
    off :func:`extract_brand_mentions` after commit. The pipeline
    runs **after** the DB commit so the extraction session can read
    the just-written answer; failures are caught per-subtask and
    logged so they never poison the polling tick.

    Two fast paths avoid calling molizhishu at all:

    1. Task is already terminal locally AND every subtask has
       ``answer_content`` — nothing new to pull, just advance the
       run. This is the LLM-mode steady state (LLMClient writes the
       full payload synchronously inside ``submit_task``); the
       extraction hook in ``scheduler.run_project`` is what populates
       ``geo_brand_mentions`` for that mode.
    2. Task is in flight locally — we ``GET /task/status`` first; the
       result pull only fires once ``completedItems > 0`` or any
       subtask has reached a terminal status, per
       ``docs/api/get-task-status.md`` §调用约定 line 42.
    """
    _in_flight.add(task_id)
    factory = get_session_factory()
    db = factory()
    extracted_subtask_ids: list[str] = []
    try:
        task = db.get(Task, task_id)
        if task is None:
            db.rollback()
            _record_compensation(
                task_id=task_id,
                source=SOURCE_REFRESH,
                action="missing",
                success=False,
                error_message="task row vanished",
            )
            return "failed", 0

        # Fast path: local row is terminal and the heavy payload is
        # already on disk. No need to bother the remote.
        if is_terminal_status(task.status) and _local_subtasks_complete(db, task_id):
            advanced = _advance_schedule_run(db, task.schedule_run_id, task.status)
            db.commit()
            _backoff_count.pop(task_id, None)
            _backoff_until.pop(task_id, None)
            if advanced:
                logger.info(
                    "[sync] task_id=%s advanced (local-terminal) status=%s",
                    task_id,
                    task.status,
                )
                return "advanced", 0
            return "refreshed", 0

        # Otherwise we owe the remote a call. Build the client lazily
        # so a network-less test path doesn't need a token.
        client = _build_client()
        status_payload = _fetch_status(client, task_id)
        if status_payload is None:
            # ``_fetch_status`` already recorded compensation + set
            # backoff; nothing more to do this tick.
            return "failed", 0

        _apply_status_payload(db, task, status_payload)

        if _should_fetch_result(db, task_id, status_payload):
            try:
                result_payload = _fetch_result(client, task_id)
            except MolizhishuError as exc:
                _handle_remote_error(task_id, exc, action="result")
                db.rollback()
                return "failed", 0
            subtask_items = result_payload.get("subTaskList") or []
            _apply_full_subtask_payload(db, task_id, subtask_items)
            extracted_subtask_ids = _pending_extraction_ids(db, subtask_items)

        advanced = _advance_schedule_run(db, task.schedule_run_id, task.status)
        db.commit()

        _backoff_count.pop(task_id, None)
        _backoff_until.pop(task_id, None)

        if advanced:
            logger.info(
                "[sync] task_id=%s advanced to terminal status=%s",
                task_id,
                task.status,
            )
            outcome = "advanced"
        else:
            outcome = "refreshed"
            logger.info(
                "[sync] task_id=%s refreshed status=%s",
                task_id,
                task.status,
            )
        # Kick off extraction *after* commit so the per-subtask session
        # inside ``extract_brand_mentions`` can see the answer_content
        # we just wrote. Failures are isolated — a bad LLM call on one
        # subtask must never roll back the polling tick's DB state.
        for sid in extracted_subtask_ids:
            try:
                extract_brand_mentions(sid)
            except Exception as exc:  # noqa: BLE001 - isolation contract
                logger.exception(
                    "[sync] extraction hook failed subtask_id=%s err=%s",
                    sid,
                    exc,
                )
        return outcome, len(extracted_subtask_ids)
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        db.rollback()
        _handle_remote_error(task_id, exc, action="unexpected")
        return "failed", 0
    finally:
        db.close()
        _in_flight.discard(task_id)


def _local_subtasks_complete(db, task_id: str) -> bool:
    """True iff the local ``subTaskList`` rows have everything we need.

    "Complete" means at least one subtask exists AND none of them have
    an empty ``answer_content``. A terminal task with zero subtasks is
    *not* complete — the polling loop must still try to pull the heavy
    payload (otherwise the schedule_run stays RUNNING forever).
    """
    subtasks = list(
        db.scalars(select(Subtask).where(Subtask.task_id == task_id)).all()
    )
    if not subtasks:
        return False
    return all((row.answer_content or "") != "" for row in subtasks)


def _build_client() -> MolizhishuClient:
    """Build the molizhishu client from ``Settings``.

    Imported lazily to avoid a circular dependency with ``scheduler``
    (the same pattern ``run_project`` uses). Reads the same env knobs
    the submit path uses, so a bad token here would also have failed
    at submit time.
    """
    settings = get_settings()
    return MolizhishuClient(
        base_url=settings.molizhishu_base_url,
        token=settings.molizhishu_token,
        timeout=settings.molizhishu_timeout_seconds,
    )


def _fetch_status(client: MolizhishuClient, task_id: str) -> dict | None:
    """GET /task/status/{id} with structured logging + backoff on failure.

    Returns ``None`` if the call was skipped (backoff / 4xx that
    shouldn't be retried) and the parsed payload on success.
    """
    url = f"{client.base_url}/task/status/{task_id}"
    started = _monotonic()
    try:
        data = client.get_task_status_sync(task_id)
    except MolizhishuError as exc:
        _log_molizhishu(SOURCE_POLL, "GET", url, started, exc)
        _handle_remote_error(task_id, exc, action="status")
        return None
    _log_molizhishu(SOURCE_POLL, "GET", url, started, None)
    return data


def _fetch_result(client: MolizhishuClient, task_id: str) -> dict | None:
    """GET /task/result/{id} with structured logging.

    Backoff is owned by the caller (``_refresh_task``) so it can also
    cover the subsequent DB upsert.
    """
    url = f"{client.base_url}/task/result/{task_id}"
    started = _monotonic()
    try:
        data = client.get_task_result_sync(task_id)
    except MolizhishuError as exc:
        _log_molizhishu(SOURCE_RESULT, "GET", url, started, exc)
        raise
    _log_molizhishu(SOURCE_RESULT, "GET", url, started, None)
    return data


def _monotonic() -> float:
    import time

    return time.monotonic()


def _log_molizhishu(
    source: str,
    method: str,
    url: str,
    started: float,
    exc: MolizhishuError | None,
) -> None:
    duration_ms = int((_monotonic() - started) * 1000)
    if exc is None:
        logger.info(
            "[molizhishu] source=%s method=%s url=%s http_status=200 "
            "success=true code=200 message=%r duration=%dms",
            source,
            method,
            url,
            "操作成功",
            duration_ms,
        )
        return
    logger.info(
        "[molizhishu] source=%s method=%s url=%s http_status=%s "
        "success=false code=%s message=%r duration=%dms",
        source,
        method,
        url,
        exc.http_status,
        exc.code,
        exc.message,
        duration_ms,
    )


def _handle_remote_error(task_id: str, exc: Exception, *, action: str) -> None:
    """Record the failure + schedule exponential backoff.

    Per ``docs/api/errors.md`` §处理建议:
    - ``code=500`` (Token invalid) → no backoff (operator must fix
      the token; retrying just spams the remote).
    - ``code=403`` / ``code=404`` → no backoff (the task is gone or
      not ours — there's no point retrying).
    - HTTP 5xx / Timeout → exponential backoff ladder.
    """
    if isinstance(exc, MolizhishuError):
        if exc.code in (500, 403, 404):
            logger.warning(
                "[sync] task_id=%s remote rejected action=%s code=%s "
                "message=%r; not retrying",
                task_id,
                action,
                exc.code,
                exc.message,
            )
            _record_compensation(
                task_id=task_id,
                source=SOURCE_REFRESH,
                action=action,
                success=False,
                http_status=exc.http_status,
                code=exc.code,
                message=exc.message,
            )
            return
    # Otherwise schedule backoff and log a compensation row.
    http_status = exc.http_status if isinstance(exc, MolizhishuError) else None
    code = exc.code if isinstance(exc, MolizhishuError) else None
    _record_compensation(
        task_id=task_id,
        source=SOURCE_REFRESH,
        action=action,
        success=False,
        http_status=http_status,
        code=code,
        message=str(exc)[:500],
    )
    _schedule_backoff(task_id)


def _schedule_backoff(task_id: str) -> None:
    previous = _backoff_count.get(task_id, 0)
    seconds = _BACKOFF_LADDER[min(previous, len(_BACKOFF_LADDER) - 1)]
    _backoff_until[task_id] = now_local() + timedelta(seconds=seconds)
    _backoff_count[task_id] = previous + 1
    logger.info(
        "[sync] task_id=%s backing off %ds (attempt %d)",
        task_id,
        seconds,
        previous + 1,
    )


def _should_fetch_result(db, task_id: str, status_payload: dict[str, Any]) -> bool:
    """Per ``docs/api/get-task-status.md`` line 42 — fetch the heavy
    payload when ``completedItems > 0`` or any subtask in
    ``subTaskList`` has reached a terminal status.
    """
    if (status_payload.get("completedItems") or 0) > 0:
        return True
    sub_statuses = [
        item.get("status") for item in (status_payload.get("subTaskList") or [])
    ]
    return any(s in _SUBTASK_TERMINAL for s in sub_statuses if s)


def _apply_status_payload(db, task: Task, payload: dict[str, Any]) -> None:
    """Update the ``Task`` row plus its child subtasks' status fields.

    Called on every refresh — both the cheap status snapshot and the
    terminal ``result`` payload carry the same ``subTaskList.status``
    field, so we update it here once instead of duplicating logic.
    """
    if payload.get("status") is not None:
        task.status = payload["status"]
    if payload.get("totalItems") is not None:
        task.total_items = payload["totalItems"]
    if payload.get("completedItems") is not None:
        task.completed_items = payload["completedItems"]
    if payload.get("failedItems") is not None:
        task.failed_items = payload["failedItems"]
    if is_terminal_status(payload.get("status")):
        # ``geo_tasks`` has ``completed_at`` (bigint ms-since-epoch) but
        # not ``remote_completed_at`` — keep the existing column name.
        task.completed_at = int(now_local().timestamp() * 1000)
    _apply_subtask_statuses(db, task.task_id, payload.get("subTaskList", []) or [])


def _apply_subtask_statuses(
    db, task_id: str, items: list[dict[str, Any]]
) -> None:
    """Touch only the ``status`` column of each subtask row.

    Called on every refresh so the project-list progress bar reflects
    ``processing`` even when the heavy fields haven't been pulled yet.
    Heavy fields are written by :func:`_apply_full_subtask_payload` on
    the terminal pass.
    """
    if not items:
        return
    subtask_ids = [item["subTaskId"] for item in items if item.get("subTaskId")]
    if not subtask_ids:
        return
    existing = {
        row.subtask_id: row
        for row in db.scalars(
            select(Subtask).where(Subtask.task_id == task_id)
        ).all()
    }
    for item in items:
        sid = item.get("subTaskId")
        if not sid or not item.get("status"):
            continue
        row = existing.get(sid)
        if row is None:
            row = Subtask(task_id=task_id, subtask_id=sid)
            db.add(row)
            existing[sid] = row
        row.status = item["status"]


def _apply_full_subtask_payload(
    db, task_id: str, items: list[dict[str, Any]]
) -> None:
    """Upsert every heavy ``subTaskList`` field (terminal pass only).

    Flushes first so any Subtask rows just inserted by
    :func:`_apply_subtask_statuses` are visible to the SELECT — the
    session has ``autoflush=False`` to avoid mid-tx chatter, but
    ``subtask_id`` is the PK so we must not insert a duplicate row.

    Brand-mention extraction is **not** triggered here; the caller
    asks :func:`_detect_newly_terminal` for the subtask ids whose
    status flipped to a terminal state and runs ``extract_brand_mentions``
    on that list after commit. Using ``status`` as the trigger (not
    ``answer_content`` churn) keeps the LLM cost to one pass per
    subtask and never lets an intermediate write confuse the detector.
    """
    db.flush()
    for item in items:
        subtask_id = item.get("subTaskId")
        if not subtask_id:
            continue
        row = db.scalar(
            select(Subtask).where(
                Subtask.task_id == task_id, Subtask.subtask_id == subtask_id
            )
        )
        if row is None:
            row = Subtask(task_id=task_id, subtask_id=subtask_id)
            db.add(row)
        for src, attr in (
            ("status", "status"),
            ("platform", "platform"),
            ("mode", "mode"),
            ("prompt", "prompt"),
            ("pageScreenshot", "page_screenshot"),
            ("answerContent", "answer_content"),
            ("referenceList", "reference_list_json"),
            ("citationList", "citation_list_json"),
            ("reasoningProcess", "reasoning_process_json"),
            ("recommendedQuestions", "recommended_questions_json"),
            ("mediaContent", "media_content_json"),
            ("errorMessage", "error_message"),
            ("proxyIp", "proxy_ip"),
        ):
            if src in item and item[src] is not None:
                setattr(row, attr, item[src])
        if item.get("time") is not None:
            row.time = str(item["time"])
        row.raw_result_json = item


def _pending_extraction_ids(
    db, items: list[dict[str, Any]]
) -> list[str]:
    """Subtask ids that need brand-mention (re-)extraction.

    Trust the API: if ``subTaskList[].status`` is ``completed`` or
    ``failed``, that subtask is in scope for extraction. We don't
    compare against ``geo_subtasks.status`` — that field can be ahead
    of the API in one tick and behind in the next, and writing it
    before checking it just reads back the same value we just wrote.

    Two situations trigger (re-)extraction:

    1. The subtask has no ``BrandMention`` rows at all — first pass.
    2. The subtask has rows in ``extract_status=PENDING`` (regex
       matched, LLM never completed) or ``extract_status=FAILED`` (LLM
       gave up after 3 attempts) — retry. SKIPPED and SUCCESS rows
       are terminal: SKIPPED means "brand not mentioned, nothing to
       extract"; SUCCESS means "LLM filled the heavy fields, don't
       touch them".

    This guarantees the regex/LLM pipeline always converges to a
    terminal state (SUCCESS / SKIPPED / FAILED) and a transient LLM
    outage doesn't permanently leave rows in PENDING.

    Both ``completed`` and ``failed`` count so the denominator (sum of
    mention rows / total subtasks) is honest — a failed subtask still
    produces BrandMention rows via the failed-subtask fast path, giving
    rate calculations a complete picture.
    """
    candidates: list[str] = []
    for item in items:
        sid = item.get("subTaskId")
        if sid and item.get("status") in ("completed", "failed"):
            candidates.append(sid)
    if not candidates:
        return []
    candidate_set = set(candidates)
    # Subtasks that have NO BrandMention rows — first-pass candidates.
    have_rows = set(
        db.scalars(
            select(BrandMention.subtask_id)
            .where(BrandMention.subtask_id.in_(candidates))
            .distinct()
        ).all()
    )
    missing_rows = candidate_set - have_rows
    # Subtasks with at least one incomplete row (PENDING or FAILED).
    incomplete = set(
        db.scalars(
            select(BrandMention.subtask_id)
            .where(
                BrandMention.subtask_id.in_(candidates),
                BrandMention.extract_status.in_(
                    [ExtractStatus.PENDING, ExtractStatus.FAILED]
                ),
            )
            .distinct()
        ).all()
    )
    needs = missing_rows | incomplete
    # Preserve the original ordering of ``candidates`` so the upstream
    # extraction loop runs in payload order (cosmetic, but keeps log
    # lines stable across ticks).
    return [sid for sid in candidates if sid in needs]


def _advance_orphan_run(task_id: str) -> bool:
    """Promote a ``ScheduleRun`` whose ``Task`` is already terminal.

    This is the local-only path used by the orphan-runs pass in
    :func:`sync_pending_tasks`. It deliberately does NOT call the
    remote — the ``Task`` row already tells us the work is done, so
    the only thing left is bookkeeping on the linked ``ScheduleRun``.

    Returns ``True`` if the linked ``ScheduleRun`` was actually moved
    out of RUNNING; ``False`` if there was nothing to do (no linked
    run, run already terminal, or the Task vanished).
    """
    factory = get_session_factory()
    db = factory()
    try:
        task = db.get(Task, task_id)
        if task is None or not is_terminal_status(task.status):
            return False
        advanced = _advance_schedule_run(db, task.schedule_run_id, task.status)
        db.commit()
        if advanced:
            logger.info(
                "[sync] task_id=%s advanced (orphan) status=%s",
                task_id,
                task.status,
            )
            _backoff_count.pop(task_id, None)
            _backoff_until.pop(task_id, None)
        return advanced
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        db.rollback()
        logger.warning(
            "[sync] task_id=%s orphan advance failed: %s", task_id, exc
        )
        return False
    finally:
        db.close()


def _advance_schedule_run(
    db, run_id: int | None, remote_status: str | None
) -> bool:
    """Promote the linked ``ScheduleRun`` to the terminal state.

    Returns ``True`` if the row was actually changed (caller uses
    this to compute the ``advanced`` count), ``False`` if there was
    no linked run or it was already in a terminal state.
    """
    if run_id is None:
        return False
    run = db.get(ScheduleRun, run_id)
    if run is None or run.status in _TERMINAL_LOCAL:
        return False
    from app.services.scheduler import _remote_to_run_status

    target = _remote_to_run_status(remote_status)
    if target not in _TERMINAL_LOCAL:
        return False
    run.status = target
    run.finished_at = now_local()
    return True


def _record_compensation(
    *,
    task_id: str,
    source: str,
    action: str,
    success: bool,
    http_status: int | None = None,
    code: int | None = None,
    message: str | None = None,
    error_message: str | None = None,
) -> None:
    """Write a ``geo_compensation_events`` row in its own session.

    We don't share the caller's session because we're often called
    AFTER a rollback — opening a fresh session guarantees the log row
    survives even when the per-task upsert failed.
    """
    factory = get_session_factory()
    db = factory()
    try:
        db.add(
            CompensationEvent(
                task_id=task_id,
                source=source,
                action=action,
                http_status=http_status,
                success=success,
                code=code,
                message=(message or "")[:1000] or None,
                error_message=(error_message or "")[:1000] or None,
                finished_at=now_local(),
            )
        )
        db.commit()
    finally:
        db.close()


# Kept as a thin wrapper so the existing test (and any future caller
# expecting the "original session blew up" path) keeps working — it
# just delegates to :func:`_record_compensation` with the same shape.
def _record_failure_standalone(task_id: str, exc: Exception) -> None:
    _record_compensation(
        task_id=task_id,
        source=SOURCE_REFRESH,
        action="unexpected",
        success=False,
        error_message=str(exc)[:1000],
    )