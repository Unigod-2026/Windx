"""Brand mention + sentiment extraction pipeline.

Drives :class:`app.models.project.BrandMention` from a freshly-upserted
``Subtask`` row. Two-stage by design for *successful* subtasks (the
cheapest pass writes a row so counts are honest even if the LLM pass
blows up), plus a deterministic fast path for *failed* ones:

0. **Failed fast path** (``subtask.status == 'failed'``) — skip both
   regex and LLM. Write one ``BrandMention`` row per (subtask ×
   brand_target) with ``mention_count=0``,
   ``extract_status=SKIPPED``, and every LLM-derived field
   (``rank_position`` / ``sentiment_score`` / ``is_recommended`` /
   ``concern_hits_json``) left ``NULL``. There's no answer to score
   and asking the LLM about an ``errorMessage`` would just burn
   tokens. The row still counts toward the "total runs" denominator
   so rate calculations stay honest.
1. **Regex pass** (status != 'failed') — for the project's monitored
   brand (and aliases) and every configured competitor (and aliases),
   write one ``BrandMention`` row per (subtask × brand_target) pair.
   ``mention_count`` is binary (1 if any spelling of the brand appears
   in the answer, 0 otherwise) and ``extract_status`` is ``PENDING``
   for matched rows, ``SKIPPED`` for the rest. This is the invariant
   that lets the UI compute "how many runs mentioned the brand" and
   "how many runs were there total" as plain ``count(*)`` aggregates
   on this table — no JOIN against ``geo_subtasks`` is needed, and
   changing the monitored model set later never breaks historical
   rates because each row was written against the brand_targets in
   force at that moment.
2. **LLM pass** with per-row retry — for each PENDING row, ask the
   configured LLM via the ``record_extraction`` tool to fill
   ``rank_position`` / ``sentiment_score`` / ``is_recommended`` /
   ``concern_hits_json``. Each row gets up to
   ``_LLM_RETRY_ATTEMPTS`` attempts with
   ``_LLM_RETRY_DELAY_SECONDS`` between them; a row that succeeds on
   any attempt is marked ``SUCCESS``, a row that exhausts all attempts
   is marked ``FAILED`` with ``mention_count=0`` (treated as "no
   mention" per the operator policy) and the last error captured in
   ``extract_error``. The row stays in the table so the denominator
   stays honest. The next sync tick will see the FAILED row and retry
   the whole subtask — regex pass promotes FAILED→PENDING if the text
   matches, LLM pass gets a fresh shot at it.

Why both stages for the success path: the regex pass gives the
overview KPI "总提及次数" for free and is robust to LLM outages. The
LLM pass fills in the expensive-but-needed rank / sentiment fields.
The per-row retry + ``sync._pending_extraction_ids`` trigger together
guarantee the pipeline converges to a terminal state (SUCCESS /
SKIPPED / FAILED) — a transient LLM outage no longer leaves rows
stuck in PENDING forever.

Failure isolation: every external call is wrapped — neither the LLM
crashing nor the regex crashing propagates out of
:func:`extract_brand_mentions_async`. The caller (``sync.py``) treats
the row's ``extract_status`` as the source of truth, not the return
value.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session_factory
from app.models.enums import ExtractStatus
from app.models.project import (
    BrandMention,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
)
from app.models.task import Subtask, Task
from app.services.llm_client import LLMClient, LLMError
from app.services.llm_prompts import PROMPT_EXTRACT_BRAND_MENTION

logger = logging.getLogger("app.extraction")

# Cap the LLM pass at a sane number of rows per subtask. ``answer_content``
# is bounded by the remote answer shape, but a project could theoretically
# monitor dozens of competitors at once; we don't want a single subtask to
# spawn an unbounded LLM fanout.
_MAX_LLM_ROWS_PER_SUBTASK = 32

# LLM transient-failure retry. The LLM pass retries each row up to
# ``_LLM_RETRY_ATTEMPTS`` times with ``_LLM_RETRY_DELAY_SECONDS``
# between attempts (3 attempts × 10s = up to ~20s wall clock per row
# on a permanent outage). After exhausting retries the row is marked
# FAILED with ``mention_count=0`` so the UI treats it as "no
# mention"; the row stays in the table so the denominator is
# preserved. Tunable in tests via monkeypatch.
_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_DELAY_SECONDS = 10.0


# --------------------------------------------------------------------------
# Tool schema
# --------------------------------------------------------------------------


# ``record_extraction`` is the only tool exposed to the LLM during this
# pass. The schema mirrors ``BrandMention`` minus the regex-derived
# fields, so a successful tool call maps 1:1 onto the row update below.
EXTRACTION_TOOL: dict = {
    "name": "record_extraction",
    "description": (
        "Submit your structured extraction for one brand mention. Must "
        "be called exactly once when you have enough information."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rank_position": {
                "type": ["integer", "null"],
                "description": (
                    "1-based rank of this brand in the answer's recommendation "
                    "order, or null if not ranked / not recommended."
                ),
            },
            "sentiment_score": {
                "type": ["number", "null"],
                "description": "0.0-1.0 sentiment toward this brand.",
            },
            "is_recommended": {
                "type": ["boolean", "null"],
                "description": (
                    "true if the AI actively recommends this brand, false if it "
                    "mentions the brand without recommending, null if unsure."
                ),
            },
            "concern_hits": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Subset of the project's configured 核心词 that appear in "
                    "this answer alongside the brand mention."
                ),
            },
        },
        "required": [
            "rank_position",
            "sentiment_score",
            "is_recommended",
            "concern_hits",
        ],
    },
}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    subtask_id: str
    rows_upserted: int
    rows_succeeded: int
    rows_failed: int


async def extract_brand_mentions_async(subtask_id: str) -> ExtractionResult:
    """Run both passes for a single subtask. Never raises."""
    factory = get_session_factory()
    db = factory()
    try:
        ctx = _load_context(db, subtask_id)
        if ctx is None:
            return ExtractionResult(subtask_id, 0, 0, 0)

        # Failed-subtask fast path: skip regex + LLM, write one SKIPPED
        # row per brand target so the denominator stays honest without
        # burning tokens on an errorMessage.
        if ctx.subtask_status == "failed":
            upserted = _failed_subtask_pass(db, ctx)
            db.commit()
            logger.info(
                "extract %s: failed-subtask fast path upserted=%s",
                subtask_id,
                upserted,
            )
            return ExtractionResult(subtask_id, upserted, 0, 0)

        upserted = _regex_pass(db, ctx)
        if upserted == 0:
            logger.debug("extract %s: no brand hits, skipping LLM pass", subtask_id)
            return ExtractionResult(subtask_id, 0, 0, 0)

        succeeded, failed = await _llm_pass(db, ctx)
        db.commit()
        logger.info(
            "extract %s: upserted=%s succeeded=%s failed=%s",
            subtask_id,
            upserted,
            succeeded,
            failed,
        )
        return ExtractionResult(subtask_id, upserted, succeeded, failed)
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.exception("extract %s: unexpected failure: %s", subtask_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return ExtractionResult(subtask_id, 0, 0, 0)
    finally:
        db.close()


def extract_brand_mentions(subtask_id: str) -> ExtractionResult:
    """Sync wrapper used by ``sync.py``.

    Mirrors the ``submit_task_sync`` pattern: the LLM client is async,
    so we hop into ``asyncio.run`` here. The event loop is single-shot
    because sync.py runs this on a worker thread (the FastAPI request
    thread or the APScheduler executor).
    """
    return asyncio.run(extract_brand_mentions_async(subtask_id))


# --------------------------------------------------------------------------
# Stage 1: regex pass
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExtractionContext:
    subtask_id: str
    task_id: str
    project_id: int
    customer_id: int
    prompt: str | None
    platform: str | None
    answer_content: str | None
    # ``Subtask.status`` ('completed' / 'failed' / etc.) — when 'failed'
    # we skip both regex and LLM passes and write a deterministic row per
    # brand target instead (no point asking the LLM about an errorMessage).
    subtask_status: str | None
    # List of (canonical, [aliases...]) for both self and competitors.
    brand_targets: list[tuple[str, list[str]]]
    # Active 核心词 list — passed verbatim to the LLM so it can match
    # concern_hits against the project's vocabulary.
    keywords: list[str]


def _load_context(db: Session, subtask_id: str) -> _ExtractionContext | None:
    subtask = db.get(Subtask, subtask_id)
    if subtask is None:
        logger.warning("extract: subtask %s not found", subtask_id)
        return None
    task = db.get(Task, subtask.task_id) if subtask.task_id else None
    if task is None or task.project_id is None:
        # Ad-hoc / legacy tasks have no project; nothing to extract.
        logger.debug(
            "extract %s: task %s has no project_id, skipping",
            subtask_id,
            subtask.task_id,
        )
        return None
    project = db.get(Project, task.project_id)
    if project is None:
        return None

    brand_targets: list[tuple[str, list[str]]] = []
    canonical = (project.brand or "").strip()
    if canonical:
        brand_targets.append((canonical, list(project.aliases or [])))
    competitors = db.scalars(
        select(ProjectCompetitor).where(ProjectCompetitor.project_id == project.id)
    ).all()
    for c in competitors:
        name = (c.name or "").strip()
        if not name:
            continue
        brand_targets.append((name, list(c.aliases or [])))

    keywords = [
        k.keyword
        for k in db.scalars(
            select(ProjectKeyword).where(ProjectKeyword.project_id == project.id)
        ).all()
    ]

    return _ExtractionContext(
        subtask_id=subtask_id,
        task_id=task.task_id,
        project_id=project.id,
        customer_id=project.customer_id,
        prompt=subtask.prompt or task.prompts_json[0] if task.prompts_json else subtask.prompt,
        platform=subtask.platform,
        answer_content=subtask.answer_content,
        subtask_status=subtask.status,
        brand_targets=brand_targets,
        keywords=keywords,
    )


def _regex_pass(db: Session, ctx: _ExtractionContext) -> int:
    """Upsert one ``BrandMention`` per canonical brand in the project.

    Every (subtask × brand_target) gets a row — including brands that
    were *not* mentioned in the answer (``mention_count=0,
    extract_status=SKIPPED``). This invariant (``geo_subtasks`` row in →
    ``geo_brand_mentions`` rows for self + every competitor in scope) is
    what makes the UI denominator ``count(*)`` honest: "how many (prompt ×
    model) runs mentioned the brand?" / "how many runs were there in
    total?" are both answered by simple counts on this table, no JOIN
    against ``geo_subtasks`` needed. Customers changing their monitored
    model set later won't break historical rates because each row was
    written against the brand_targets in force at that moment.

    Returns the number of rows upserted (always ``len(ctx.brand_targets)``
    when brand_targets is non-empty). Matched rows are left in
    ``extract_status=PENDING`` for the LLM pass; unmatched rows go
    straight to ``SKIPPED`` — there's no rank/sentiment to fill when the
    brand never appears in the answer.

    Retry semantics on re-run:
    - SUCCESS is sticky — heavy fields preserved, ``mention_count``
      refreshes to reflect the current text (a brand that later
      disappears from the answer still keeps its rank / sentiment).
    - SKIPPED → PENDING if the text now matches (polling-after-submit
      race fix; lets the LLM pass fill heavy fields).
    - FAILED → PENDING if the text now matches (LLM retry trigger; the
      ``_pending_extraction_ids`` check in sync.py sees the FAILED row
      and re-runs extraction, regex pass picks the row up here).
    """
    text = ctx.answer_content or ""
    if not ctx.brand_targets:
        return 0

    upserted = 0
    for canonical, aliases in ctx.brand_targets:
        matched = bool(text.strip()) and bool(_find_brand(text, canonical, aliases))
        row = db.scalar(
            select(BrandMention).where(
                BrandMention.subtask_id == ctx.subtask_id,
                BrandMention.brand_canonical == canonical,
            )
        )
        if row is None:
            row = BrandMention(
                subtask_id=ctx.subtask_id,
                task_id=ctx.task_id,
                project_id=ctx.project_id,
                customer_id=ctx.customer_id,
                prompt=ctx.prompt,
                platform=ctx.platform,
                brand_canonical=canonical,
                is_self=(
                    bool(ctx.brand_targets)
                    and canonical
                    == (ctx.brand_targets[0][0])
                ),
                mention_count=1 if matched else 0,
                extract_status=(
                    ExtractStatus.PENDING if matched else ExtractStatus.SKIPPED
                ),
            )
            db.add(row)
        else:
            # Re-running extraction. Refresh regex fields and, when the
            # text now matches a brand we previously skipped / gave up on
            # (the typical case is "answer_content landed after the first
            # extraction pass ran against an empty string", or "LLM
            # failed 3x and we want to retry"), bump the row back to
            # PENDING so the LLM pass fills in rank / sentiment /
            # is_recommended. SUCCESS is sticky — once the LLM pass has
            # populated the heavy fields we don't want a later empty-text
            # re-run to downgrade the row.
            row.mention_count = 1 if matched else 0
            if matched and row.extract_status in (
                ExtractStatus.SKIPPED,
                ExtractStatus.FAILED,
            ):
                row.extract_status = ExtractStatus.PENDING
                row.extract_error = None
        upserted += 1
    db.flush()
    return upserted


def _find_brand(
    text: str, canonical: str, aliases: list[str]
) -> str | None:
    """Return the matched brand literal if any spelling appears, else ``None``.

    Iterates canonical first then each alias so the canonical literal is
    preferred when both appear (the canonical is the user-facing brand
    name in the UI). Per the 2026-08-15 spec change, the column that
    used to carry the occurrence count is now binary (0/1) — a row only
    exists at all when the brand was mentioned, so we just return the
    winning literal here and the caller writes ``mention_count = 1``.
    """
    needles = [canonical, *(a for a in aliases if a and a.strip())]
    seen: set[str] = set()
    ordered: list[str] = []
    for n in needles:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    if not ordered:
        return None
    # Escape re metacharacters; whole-match a substring.
    pattern = re.compile("|".join(re.escape(n) for n in ordered))
    if not pattern.search(text):
        return None
    # Prefer the canonical literal when present, otherwise the first alias.
    if pattern.search(canonical):
        return canonical
    return ordered[1] if len(ordered) > 1 else canonical


# --------------------------------------------------------------------------
# Failed-subtask fast path
# --------------------------------------------------------------------------


def _failed_subtask_pass(db: Session, ctx: _ExtractionContext) -> int:
    """Write one SKIPPED row per brand target, no regex, no LLM.

    Called when ``Subtask.status == 'failed'`` — the answer body is an
    ``errorMessage`` or empty, so there is no signal to score and
    running the regex / LLM would just waste tokens. We still write the
    same number of rows the success path would have written so the
    denominator "total (subtask × brand_target) pairs" stays honest and
    UI rate calculations don't silently lose the failed runs.

    Idempotency: re-running on a subtask that already has rows keeps
    them as SKIPPED (does NOT clobber a SUCCESS row — the LLM pass
    has already populated heavy fields and we don't want a failed
    re-classification to wipe them).
    """
    if not ctx.brand_targets:
        return 0
    upserted = 0
    for canonical, aliases in ctx.brand_targets:
        row = db.scalar(
            select(BrandMention).where(
                BrandMention.subtask_id == ctx.subtask_id,
                BrandMention.brand_canonical == canonical,
            )
        )
        if row is None:
            row = BrandMention(
                subtask_id=ctx.subtask_id,
                task_id=ctx.task_id,
                project_id=ctx.project_id,
                customer_id=ctx.customer_id,
                prompt=ctx.prompt,
                platform=ctx.platform,
                brand_canonical=canonical,
                is_self=(
                    bool(ctx.brand_targets)
                    and canonical == ctx.brand_targets[0][0]
                ),
                mention_count=0,
                extract_status=ExtractStatus.SKIPPED,
            )
            db.add(row)
        elif row.extract_status != ExtractStatus.SUCCESS:
            # Failed-subtask classification overrides PENDING/FAILED/SKIPPED
            # but never SUCCESS — once the LLM has filled heavy fields we
            # don't want to wipe them back to NULL on a later failed
            # re-classification.
            row.mention_count = 0
            row.extract_status = ExtractStatus.SKIPPED
            row.extract_error = None
            row.raw_extraction = None
        upserted += 1
    db.flush()
    return upserted


# --------------------------------------------------------------------------
# Stage 2: LLM pass
# --------------------------------------------------------------------------


async def _llm_pass(db: Session, ctx: _ExtractionContext) -> tuple[int, int]:
    """Fill the LLM-derived fields on every PENDING row.

    Returns ``(succeeded, failed)``. Each row is updated in place; the
    caller's ``commit`` persists everything.

    Per-row retry: each row gets up to ``_LLM_RETRY_ATTEMPTS`` LLM
    calls with ``_LLM_RETRY_DELAY_SECONDS`` between attempts (see
    :func:`_extract_one_with_retry`). A row that exhausts retries is
    marked ``FAILED`` with ``mention_count=0`` so the UI treats it as
    "no mention" while the row still counts toward the total-run
    denominator.
    """
    pending_rows = (
        db.scalars(
            select(BrandMention)
            .where(
                BrandMention.subtask_id == ctx.subtask_id,
                BrandMention.extract_status == ExtractStatus.PENDING,
            )
            .limit(_MAX_LLM_ROWS_PER_SUBTASK)
        ).all()
    )
    if not pending_rows:
        return 0, 0

    try:
        client = _build_llm_client()
    except LLMError as exc:
        # LLM not configured (missing API key etc.) — a config error, not
        # a transient outage. Don't retry; mark every row FAILED so the
        # UI shows "抽取失败: LLM 未配置" instead of silently losing
        # rows.
        msg = f"LLM client unavailable: {exc}"[:500]
        for row in pending_rows:
            row.extract_status = ExtractStatus.FAILED
            row.extract_error = msg
            row.mention_count = 0
        return 0, len(pending_rows)

    succeeded = 0
    failed = 0
    for row in pending_rows:
        # ``_extract_one_with_retry`` swallows exceptions and only
        # returns a payload on success; on exhaustion it has already
        # marked the row FAILED + ``mention_count=0`` so the
        # per-row bookkeeping below is just success bookkeeping.
        try:
            payload = await _extract_one_with_retry(client, ctx, row)
        except Exception as exc:  # noqa: BLE001 - per-row isolation (last-resort)
            # Should be unreachable: _extract_one_with_retry catches
            # internally. Kept as a defensive guard so a bug in the
            # retry wrapper can't take down the whole LLM pass.
            row.extract_status = ExtractStatus.FAILED
            row.extract_error = str(exc)[:500]
            row.mention_count = 0
            row.raw_extraction = None
            failed += 1
            continue

        if payload is None:
            # All retries exhausted. Row already marked FAILED by the
            # wrapper.
            failed += 1
            continue

        _apply_payload(row, payload)
        row.extract_status = ExtractStatus.SUCCESS
        row.extract_error = None
        row.raw_extraction = payload
        succeeded += 1
    return succeeded, failed


async def _extract_one_with_retry(
    client: LLMClient,
    ctx: _ExtractionContext,
    row: BrandMention,
) -> dict | None:
    """Try ``_extract_one`` up to ``_LLM_RETRY_ATTEMPTS`` times.

    Treats both exceptions and "LLM returned but didn't call the tool"
    as failures (the model just didn't cooperate this attempt — maybe
    next time). Sleeps ``_LLM_RETRY_DELAY_SECONDS`` between attempts so
    a transient endpoint hiccup has time to clear.

    On success: returns the ``record_extraction`` payload; the caller
    promotes the row to ``SUCCESS``.

    On exhaustion: marks the row ``FAILED`` with the last error
    captured in ``extract_error``, sets ``mention_count=0`` so the UI
    treats this (subtask, brand) pair as "no mention", and clears
    ``raw_extraction``. The row stays in the table so the
    (subtask × brand_target) denominator is preserved.
    """
    last_err: str | None = None
    for attempt in range(1, _LLM_RETRY_ATTEMPTS + 1):
        try:
            payload = await _extract_one(client, ctx, row)
            if payload is not None:
                return payload
            last_err = "LLM did not call record_extraction"
            logger.warning(
                "extract %s brand=%s: attempt %d/%d — %s",
                ctx.subtask_id, row.brand_canonical, attempt,
                _LLM_RETRY_ATTEMPTS, last_err,
            )
        except Exception as exc:  # noqa: BLE001 - retry per row, isolation per row
            last_err = str(exc)
            logger.warning(
                "extract %s brand=%s: attempt %d/%d failed: %s",
                ctx.subtask_id, row.brand_canonical, attempt,
                _LLM_RETRY_ATTEMPTS, exc,
            )
        if attempt < _LLM_RETRY_ATTEMPTS:
            await asyncio.sleep(_LLM_RETRY_DELAY_SECONDS)
    # Exhausted. Per user requirement: treat as "no mention" but keep
    # the row so the denominator stays honest.
    row.extract_status = ExtractStatus.FAILED
    row.extract_error = (
        f"LLM {_LLM_RETRY_ATTEMPTS}次尝试均失败: {last_err or 'unknown'}"
    )[:500]
    row.mention_count = 0
    row.raw_extraction = None
    return None


def _build_llm_client() -> LLMClient:
    settings = get_settings()
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_tool_rounds=settings.llm_max_tool_rounds,
        web_fetch_max_bytes=settings.llm_web_fetch_max_bytes,
    )


async def _extract_one(
    client: LLMClient,
    ctx: _ExtractionContext,
    row: BrandMention,
) -> dict | None:
    """One LLM call to fill one row's structured fields.

    Returns the parsed JSON dict from ``record_extraction``, or ``None``
    if the LLM never invoked the tool.
    """
    user_prompt = _render_user_prompt(ctx, row)
    text, transcript, structured = await client.ask(
        system=PROMPT_EXTRACT_BRAND_MENTION,
        user_prompt=user_prompt,
        tools=[EXTRACTION_TOOL],
        max_tokens=512,
    )
    if structured is not None:
        return structured
    # The LLM might have called the tool mid-conversation without us
    # capturing it via the structured-output channel — fall back to
    # scanning the transcript. ``transcript`` is a list of tool-call
    # dicts that already includes ``record_extraction`` calls when
    # they happen.
    for entry in transcript or []:
        if entry.get("name") == "record_extraction":
            return entry.get("input")
    return None


def _render_user_prompt(ctx: _ExtractionContext, row: BrandMention) -> str:
    keywords_csv = "、".join(ctx.keywords) if ctx.keywords else "（无）"
    answer = ctx.answer_content or ""
    # Cap the answer at 8 KB to keep the LLM prompt small; the LLM
    # only needs to see enough to judge rank/sentiment/recommendation.
    if len(answer) > 8000:
        answer = answer[:8000] + "\n...(截断)"
    return (
        f"项目问题：{ctx.prompt or '（未知）'}\n"
        f"模型：{ctx.platform or '（未知）'}\n"
        f"项目核心词：{keywords_csv}\n"
        f"被监测品牌（含别名）：{row.brand_canonical}"
        f"{('（别名：' + '、'.join(_aliases_for(ctx, row.brand_canonical)) + '）') if _aliases_for(ctx, row.brand_canonical) else ''}\n"
        f"—— AI 回答正文 ——\n{answer}\n"
        f"—— 任务 ——\n"
        f"该回答中是否提到了品牌「{row.brand_canonical}」？"
        f"正则阶段已确认该回答中出现了品牌「{row.brand_canonical}」（mention_count=1：即只要出现即计 1 次,与出现频率无关）。请基于上述回答给出：\n"
        f"1. rank_position：该品牌在回答推荐顺序中的排名（1-based，未明确推荐则为 null）；\n"
        f"2. sentiment_score：0.0-1.0 的情感打分（越高越正面）；\n"
        f"3. is_recommended：AI 是否在答案中明确推荐该品牌；\n"
        f"4. concern_hits：上述核心词中哪些在该回答里与该品牌一同出现。\n"
        f"请调用 record_extraction 工具提交。"
    )


def _aliases_for(ctx: _ExtractionContext, canonical: str) -> list[str]:
    for c, aliases in ctx.brand_targets:
        if c == canonical:
            return [a for a in aliases if a and a.strip()]
    return []


def _apply_payload(row: BrandMention, payload: dict) -> None:
    rank = payload.get("rank_position")
    if isinstance(rank, int) and rank > 0:
        row.rank_position = rank
    sentiment = payload.get("sentiment_score")
    if isinstance(sentiment, (int, float)):
        row.sentiment_score = max(0.0, min(1.0, float(sentiment)))
    recommended = payload.get("is_recommended")
    if isinstance(recommended, bool):
        row.is_recommended = recommended
    concerns = payload.get("concern_hits")
    if isinstance(concerns, list):
        row.concern_hits_json = [str(c) for c in concerns if isinstance(c, (str,))]