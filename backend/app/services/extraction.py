"""Brand mention extraction pipeline.

Drives :class:`app.models.project.BrandMention` from a freshly-upserted
``Subtask`` row. Reads Molizhishu API output directly from
``Subtask.raw_result_json`` — **no LLM pass, no LLM retry, no LLM at all**.
The previous two-stage design (regex → LLM judge) was retired once the
upgraded ``GET /task/result/{taskId}`` endpoint started returning the
brand-mention fields inline (``mentionPosition`` / ``sentiment`` /
``mentionContext`` / ``allRankings``).

Two stages for *successful* subtasks (status != 'failed'):

1. **Ensure rows** — for every ``brand_target`` (self brand + every
   configured competitor), write one ``BrandMention`` row if none
   exists yet. New rows land in ``extract_status=SKIPPED`` with
   ``is_mention=0``. The (subtask × brand_target) invariant is what
   lets the UI compute "how many (prompt × model) runs mentioned the
   brand?" / "how many runs were there in total?" as plain ``count(*)``
   aggregates on this table — no JOIN against ``geo_subtasks`` needed.
   Customers changing their monitored brand / competitor set later
   won't break historical rates because each row was written against
   the ``brand_targets`` in force at that moment.

2. **Populate from API** — for every non-SUCCESS row, read the matching
   fields from ``subtask.raw_result_json`` (the full Molizhishu
   subtask item, written verbatim by :mod:`app.services.sync`):

   - SELF brand row (``is_self=true``):
     - ``rank_position``      ← ``raw.mentionPosition`` (int, nullable)
     - ``sentiment``    ← ``raw.sentiment`` (``positive`` /
       ``neutral`` / ``negative``)
     - ``concern_hits_json``  ← ``[{"text": raw.mentionContext}]``
     - ``is_mention``      ← ``1`` if ``rank_position`` is set,
       else ``0`` (API is authoritative for "was the brand mentioned")
     - ``is_recommended``     ← derived from ``rank_position``
   - Competitor row (``is_self=false``):
     - ``rank_position``      ← lookup of ``brand`` in
       ``raw.allRankings`` (preferred) then
       ``raw.competitorRankings``
     - ``sentiment``    ← ``NULL`` (the API doesn't give
       per-competitor sentiment)
     - ``concern_hits_json``  ← ``NULL``
     - ``is_mention``      ← ``1`` if found in rankings, else ``0``
     - ``is_recommended``     ← derived from ``rank_position``

   Per-row outcomes:
   - If ``raw_result_json`` is missing or empty: row → ``FAILED`` with
     ``is_mention=0``, ``extract_error="raw_result_json missing or
     empty"``. The next sync tick re-runs against a fresh payload.
   - If the API ranks this brand: row → ``SUCCESS``, heavy fields
     filled, ``is_mention=1``.
   - If the API does NOT rank this brand: row → ``SKIPPED`` with
     ``is_mention=0``. Crucially, **competitors the regex missed
     but the API ranked** are now upgraded to ``SUCCESS`` here — the
     regex no longer gates populate eligibility.

``is_recommended`` is **derived**: ``rank_position is not None and
rank_position <= 5`` → ``True``. Aligns with the typical "rank 1-5
= recommended" reading; see project memory
``project_is_recommended_semantics``.

Failed-subtask fast path (``subtask.status == 'failed'``): skip both
stages, write one ``SKIPPED`` row per brand_target with all derived
fields NULL. There's no answer to score and the row still counts
toward the total-run denominator.

Idempotency: SUCCESS is sticky — populate never overwrites a SUCCESS
row. The ensure pass never overwrites existing rows at all. A re-run
after ``raw_result_json`` lands upgrades ``PENDING`` / ``SKIPPED`` /
``FAILED`` rows in-place.

Failure isolation: every external read is local (raw JSON dict access)
so there's nothing to crash; even so, the outer wrapper catches and
logs any exception per row so one bad subtask can't take down the
batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models.enums import ExtractStatus
from app.models.project import (
    BrandMention,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
)
from app.models.task import Subtask, Task
from app.services.llm_client import build_client_from_settings

logger = logging.getLogger("app.extraction")

# Molizhishu ``GET /task/result/{taskId}/{subTaskId}`` returns ``sentiment``
# as one of these three lowercase labels. Stored verbatim in
# ``geo_brand_mentions.sentiment`` (VARCHAR(16)); the API layer
# translates to numeric buckets for dashboard colors.
_VALID_SENTIMENT_LABELS = frozenset({"positive", "neutral", "negative"})


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    subtask_id: str
    rows_upserted: int
    rows_succeeded: int
    rows_failed: int


def extract_brand_mentions(subtask_id: str) -> ExtractionResult:
    """Run all three passes for a single subtask. Never raises.

    Sync wrapper — the LLM client is async, but
    :meth:`LLMClient.judge_brand_correctness_sync` already calls it via
    ``asyncio.run`` + 5s/10s retry, so this whole pipeline stays sync.
    ``scheduler.py`` and ``sync.py`` both call this on a worker thread
    (APScheduler executor / FastAPI background task).
    """
    factory = get_session_factory()
    db = factory()
    try:
        ctx = _load_context(db, subtask_id)
        if ctx is None:
            return ExtractionResult(subtask_id, 0, 0, 0)

        # Failed-subtask fast path: skip regex + populate, write one SKIPPED
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

        upserted = _ensure_target_rows(db, ctx)
        if upserted == 0:
            logger.debug("extract %s: no brand targets, skipping", subtask_id)
            return ExtractionResult(subtask_id, 0, 0, 0)

        succeeded, failed = _populate_from_raw_pass(db, ctx)
        # Correctness pass is independent of populate: it only writes
        # ``is_correct`` and never mutates ``extract_status`` / heavy
        # fields, so a failing LLM call doesn't undo a successful
        # rank/sentiment population. It runs last so the rows it touches
        # are the freshly-populated ones (is_self / brand stable for
        # this subtask).
        correctness = _populate_correctness_pass(db, ctx)
        db.commit()
        logger.info(
            "extract %s: upserted=%s succeeded=%s failed=%s correctness=%s",
            subtask_id,
            upserted,
            succeeded,
            failed,
            correctness,
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


# --------------------------------------------------------------------------
# Context
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
    # we skip both regex and populate passes and write a deterministic
    # row per brand target instead (no signal to score).
    subtask_status: str | None
    # ``thinking_mode`` 分桶,供 UI 「全局工具栏 → 模式」筛选:
    #   True  = Subtask.mode IN ('reasoning', 'reasoning_search')
    #   False = Subtask.mode IN ('standard', 'search', 'web')
    # None if Subtask.mode is missing.
    thinking_mode: bool | None
    # ``delivery_mode`` 分桶,供 UI 「全局工具栏 → 终端」筛选:
    #   'web'    = Subtask.platform 不含 '_mobile' 后缀
    #   'mobile' = Subtask.platform 以 '_mobile' 结尾
    # None if Subtask.platform is missing.
    delivery_mode: str | None
    # List of (canonical, [aliases...]) for both self and competitors.
    brand_targets: list[tuple[str, list[str]]]
    # Active 核心词 list — kept for backward compatibility with downstream
    # code that reads ``ctx.keywords``; not used by the populate pass.
    keywords: list[str]
    # 用户在向导 step 6 填的「核心卖点」(从 ``Project.semantic_json``
    # 读出,list[str],最多 10 行)。``correctness_pass`` 拿这一段 +
    # ``answer_content`` 调 LLM 判断回答是否正确。空 list 走短路:
    # 所有行 ``is_correct=True``(没卖点就谈不上答错)。
    selling_points: list[str]
    # Full Molizhishu subtask payload, written verbatim by sync.py. All
    # brand-mention fields we care about live here once the new API
    # shape lands (``mentionPosition`` / ``sentiment`` /
    # ``mentionContext`` / ``allRankings``). Default ``None`` so the
    # existing ``_make_ctx`` test fixture (which builds the context
    # directly without the payload) keeps compiling; the production
    # ``_load_context`` path always populates this.
    raw_result_json: dict | None = None


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

    # 核心卖点 — wizard step 6 写入 ``Project.semantic_json["selling_points"]``。
    # list[str],最多 10 行(前端 wizard 截断;后端也再保险一次 [:10])。
    # 空 list 触发 ``correctness_pass`` 的短路分支(所有行 is_correct=True)。
    sem = project.semantic_json or {}
    raw_points = sem.get("selling_points") if isinstance(sem, dict) else None
    if not isinstance(raw_points, list):
        selling_points: list[str] = []
    else:
        selling_points = [str(p).strip() for p in raw_points if p and str(p).strip()][:10]

    return _ExtractionContext(
        subtask_id=subtask_id,
        task_id=task.task_id,
        project_id=project.id,
        customer_id=project.customer_id,
        prompt=subtask.prompt or task.prompts_json[0] if task.prompts_json else subtask.prompt,
        platform=subtask.platform,
        answer_content=subtask.answer_content,
        subtask_status=subtask.status,
        raw_result_json=subtask.raw_result_json,
        thinking_mode=_derive_thinking_mode(subtask.mode),
        delivery_mode=_derive_delivery_mode(subtask.platform),
        brand_targets=brand_targets,
        keywords=keywords,
        selling_points=selling_points,
    )


def _derive_thinking_mode(mode: str | None) -> bool | None:
    """``Subtask.mode`` → UI 「模式」分桶。

    fast  = ``standard`` / ``search``
    think = ``reasoning`` / ``reasoning_search``
    历史的 ``mode='web'`` (2026-08 前枚举拆分前的默认值)归到 fast
    —— 与 spec 「fast: standard 或 search; think: 其他两类」一致,
    'web' 即旧的「非思考」桶。
    """
    if not mode:
        return None
    if mode in ("reasoning", "reasoning_search"):
        return True
    if mode in ("standard", "search", "web"):
        return False
    return None


def _derive_delivery_mode(platform: str | None) -> str | None:
    """``Subtask.platform`` → UI 「终端」分桶。

    - ``*_mobile`` → ``'mobile'``
    - 其他       → ``'web'``
    """
    if not platform:
        return None
    return "mobile" if platform.endswith("_mobile") else "web"


# --------------------------------------------------------------------------
# Stage 1: ensure rows
# --------------------------------------------------------------------------


def _ensure_target_rows(db: Session, ctx: _ExtractionContext) -> int:
    """Upsert one ``BrandMention`` per brand_target, all in SKIPPED state.

    Replaces the old regex pass — ``is_mention`` and
    ``extract_status`` are now derived from ``raw_result_json`` by the
    populate pass (the API is authoritative for "was the brand
    mentioned"). This function's only job is the denominator invariant:
    every (subtask × brand_target) pair gets exactly one row, so the
    UI can compute "how many runs were there" with a plain ``count(*)``
    on this table — no JOIN against ``geo_subtasks`` needed.

    Returns the number of rows upserted (always ``len(ctx.brand_targets)``
    when brand_targets is non-empty). Existing rows are NOT touched —
    the populate pass owns all status / heavy-field transitions, and
    SUCCESS rows stay sticky.
    """
    if not ctx.brand_targets:
        return 0

    upserted = 0
    self_canonical = ctx.brand_targets[0][0]
    for canonical, _aliases in ctx.brand_targets:
        row = db.scalar(
            select(BrandMention).where(
                BrandMention.subtask_id == ctx.subtask_id,
                BrandMention.brand == canonical,
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
                thinking_mode=ctx.thinking_mode,
                delivery_mode=ctx.delivery_mode,
                brand=canonical,
                is_self=(canonical == self_canonical),
                is_mention=0,
                extract_status=ExtractStatus.SKIPPED,
            )
            db.add(row)
        upserted += 1
    db.flush()
    return upserted


# --------------------------------------------------------------------------
# Failed-subtask fast path
# --------------------------------------------------------------------------


def _failed_subtask_pass(db: Session, ctx: _ExtractionContext) -> int:
    """Write one SKIPPED row per brand target, no regex, no populate.

    Called when ``Subtask.status == 'failed'`` — the answer body is an
    ``errorMessage`` or empty, so there is no signal to score and
    running the regex / populate would just waste effort. We still write
    the same number of rows the success path would have written so the
    denominator "total (subtask × brand_target) pairs" stays honest and
    UI rate calculations don't silently lose the failed runs.

    Idempotency: re-running on a subtask that already has rows keeps
    them as SKIPPED (does NOT clobber a SUCCESS row — the populate pass
    has already populated heavy fields and we don't want a failed
    re-classification to wipe them).
    """
    if not ctx.brand_targets:
        return 0
    upserted = 0
    self_canonical = ctx.brand_targets[0][0]
    for canonical, _aliases in ctx.brand_targets:
        row = db.scalar(
            select(BrandMention).where(
                BrandMention.subtask_id == ctx.subtask_id,
                BrandMention.brand == canonical,
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
                thinking_mode=ctx.thinking_mode,
                delivery_mode=ctx.delivery_mode,
                brand=canonical,
                is_self=(canonical == self_canonical),
                is_mention=0,
                extract_status=ExtractStatus.SKIPPED,
            )
            db.add(row)
        elif row.extract_status != ExtractStatus.SUCCESS:
            # Failed-subtask classification overrides PENDING/FAILED/SKIPPED
            # but never SUCCESS — once populate has filled heavy fields we
            # don't want to wipe them back to NULL on a later failed
            # re-classification. Clear every field populate would have
            # written so a subsequent re-classification (e.g. status
            # flipping back to 'completed') starts from a known-empty
            # state instead of inheriting stale heavy fields.
            row.is_mention = 0
            row.rank_position = None
            row.sentiment = None
            row.is_recommended = None
            row.concern_hits_json = None
            row.extract_status = ExtractStatus.SKIPPED
            row.extract_error = None
            row.raw_extraction = None
        upserted += 1
    db.flush()
    return upserted


# --------------------------------------------------------------------------
# Stage 2: populate from raw_result_json (no LLM)
# --------------------------------------------------------------------------


def _populate_from_raw_pass(
    db: Session, ctx: _ExtractionContext
) -> tuple[int, int]:
    """Fill derived fields on every non-SUCCESS row by reading ``raw_result_json``.

    Returns ``(succeeded, failed)``. Each row is updated in place; the
    caller's ``commit`` persists everything.

    Eligible rows: every row with ``extract_status != SUCCESS``. The old
    regex pass used to gate eligibility on a text match, but the API is
    authoritative — if ``raw.mentionPosition`` (SELF) or
    ``raw.allRankings`` (competitor) names the brand, we count it as
    mentioned and promote to ``SUCCESS`` even when the regex missed the
    name. ``SUCCESS`` rows are never re-touched (sticky contract).

    Outcomes:
    - ``raw_result_json`` missing / empty / wrong type: every eligible
      row → ``FAILED``, ``is_mention=0``. Next sync tick retries
      once the payload is available.
    - API ranks the brand: row → ``SUCCESS``, ``is_mention=1``,
      heavy fields populated.
    - API does NOT rank the brand: row → ``SKIPPED``, ``is_mention=0``.
    """
    eligible_rows = db.scalars(
        select(BrandMention).where(
            BrandMention.subtask_id == ctx.subtask_id,
            BrandMention.extract_status != ExtractStatus.SUCCESS,
        )
    ).all()
    if not eligible_rows:
        return 0, 0

    raw = ctx.raw_result_json
    # Defence-in-depth: ``raw_result_json`` is typed as dict but sync may
    # write a corrupt value if the upstream payload was malformed JSON.
    # Treat anything that isn't a non-empty dict as "missing".
    if not isinstance(raw, dict) or not raw:
        msg = "raw_result_json missing or empty"
        for row in eligible_rows:
            row.extract_status = ExtractStatus.FAILED
            row.extract_error = msg
            row.is_mention = 0
            row.rank_position = None
            row.sentiment = None
            row.is_recommended = None
            row.concern_hits_json = None
            row.raw_extraction = None
        return 0, len(eligible_rows)

    succeeded = 0
    failed = 0
    for row in eligible_rows:
        try:
            payload = _build_payload_from_raw(raw, row)
        except Exception as exc:  # noqa: BLE001 - per-row isolation
            row.extract_status = ExtractStatus.FAILED
            row.extract_error = f"payload build failed: {exc}"[:500]
            row.is_mention = 0
            row.rank_position = None
            row.sentiment = None
            row.is_recommended = None
            row.concern_hits_json = None
            row.raw_extraction = None
            logger.warning(
                "extract %s brand=%s: payload build failed: %s",
                ctx.subtask_id, row.brand, exc,
            )
            failed += 1
            continue

        _apply_payload(row, payload)
        if payload.get("rank_position") is not None:
            # API ranked this brand → SUCCESS, is_mention=1.
            row.extract_status = ExtractStatus.SUCCESS
            row.extract_error = None
            row.raw_extraction = payload
            succeeded += 1
        else:
            # API did not rank this brand → SKIPPED, is_mention=0.
            row.extract_status = ExtractStatus.SKIPPED
            row.extract_error = None
            row.raw_extraction = None
    return succeeded, failed


def _build_payload_from_raw(raw: dict, row: BrandMention) -> dict:
    """Build the row update payload from ``raw_result_json`` and the row.

    SELF brand (``row.is_self == True``):
      - ``rank_position``     ← ``raw.mentionPosition`` (int, nullable)
      - ``sentiment``   ← ``raw.sentiment`` (string label, validated)
      - ``concern_hits_json`` ← ``[{"text": raw.mentionContext}]``
      - ``is_recommended``    ← derived

    Competitor (``row.is_self == False``):
      - ``rank_position``     ← lookup of ``row.brand`` in
        ``raw.allRankings`` (preferred) then ``raw.competitorRankings``
      - ``sentiment``   ← NULL (API doesn't give per-competitor)
      - ``concern_hits_json`` ← NULL
      - ``is_recommended``    ← derived

    ``is_recommended`` derivation: ``rank_position is not None and
    rank_position <= 5`` → ``True``, else ``False``. See project memory
    ``project_is_recommended_semantics``.
    """
    payload: dict = {}

    if row.is_self:
        rank = raw.get("mentionPosition")
        if isinstance(rank, int) and rank > 0:
            payload["rank_position"] = rank

        sentiment = raw.get("sentiment")
        if isinstance(sentiment, str) and sentiment in _VALID_SENTIMENT_LABELS:
            payload["sentiment"] = sentiment

        ctx_text = raw.get("mentionContext")
        if isinstance(ctx_text, str) and ctx_text.strip():
            payload["concern_hits_json"] = [{"text": ctx_text}]
    else:
        rank = _find_competitor_rank(raw, row.brand)
        if isinstance(rank, int) and rank > 0:
            payload["rank_position"] = rank

    rank_val = payload.get("rank_position")
    payload["is_recommended"] = bool(rank_val is not None and rank_val <= 5)

    return payload


def _find_competitor_rank(raw: dict, brand_name: str) -> int | None:
    """Find a competitor's rank in ``raw_result_json`` rankings.

    Walks ``allRankings`` first (the canonical full ranking list) then
    ``competitorRankings`` (the project-configured competitor subset).
    Returns the first positive int rank that matches ``brand_name``;
    ``None`` if the brand isn't listed or any payload field is the
    wrong shape.
    """
    for source in (raw.get("allRankings"), raw.get("competitorRankings")):
        if not isinstance(source, list):
            continue
        for entry in source:
            if not isinstance(entry, dict):
                continue
            if entry.get("name") == brand_name:
                rank = entry.get("rank")
                if isinstance(rank, int) and rank > 0:
                    return rank
    return None


def _apply_payload(row: BrandMention, payload: dict) -> None:
    """Apply the derived payload to a row.

    Writes only fields the payload actually carries — a row may
    legitimately end up with some fields NULL (e.g. competitor with no
    ``sentiment`` from upstream). ``is_mention`` is derived from
    ``rank_position``: API ranked the brand → ``1``, else ``0``. The
    API is authoritative for "was the brand mentioned"; the old
    regex-based derivation is gone.

    ``extract_status`` / ``extract_error`` / ``raw_extraction`` are
    owned by the caller (populate pass) — this function does not touch
    them, so SUCCESS stays sticky.
    """
    if "rank_position" in payload:
        rank = payload["rank_position"]
        row.rank_position = rank
        row.is_mention = 1 if rank is not None else 0
    if "sentiment" in payload:
        row.sentiment = payload["sentiment"]
    if "is_recommended" in payload:
        row.is_recommended = payload["is_recommended"]
    if "concern_hits_json" in payload:
        row.concern_hits_json = payload["concern_hits_json"]


# --------------------------------------------------------------------------
# Stage 3: LLM-judged correctness (self rows only)
# --------------------------------------------------------------------------


def _populate_correctness_pass(
    db: Session, ctx: _ExtractionContext
) -> tuple[int, int, int]:
    """Fill ``is_correct`` on every row for this subtask.

    Returns ``(judged_true, judged_false, judged_none)`` — counters for
    logging / debugging. The function never raises: the LLM call goes
    through :meth:`LLMClient.judge_brand_correctness_sync` which already
    implements 5s/10s retry, so transient infra failures resolve
    transparently; persistent failures land as ``is_correct=None``.

    Rules:

    - **Project has no ``selling_points``** (user didn't fill the
      semantic field) → short-circuit, every row's ``is_correct = True``
      without an LLM call. The "no criteria to judge against" reading
      matches user intent: 答对答错要有基准,没基准就谈不上错。

    - **Project has ``selling_points``** → only ``is_self=true`` rows
      are eligible. Competitor (``is_self=false``) rows stay
      ``is_correct=None`` — semantically the judgment is "is this
      answer about MY brand correct per MY selling points", which
      doesn't apply to competitor mentions.

    - **One LLM call per subtask** (not per row) covers every self row
      simultaneously. The judge is asked once about "the answer" + the
      brand + the selling points; the verdict is broadcast to all self
      rows of this subtask.

    - **Empty ``answer_content``** → LLM still gets the call (it can
      return its own "answer is empty, can't judge" verdict, or fall
      back to None on parse failure). Skipping locally would skip the
      judge entirely and lose the chance for the model to flag a
      missing body as a separate failure mode.

    - **Existing non-null ``is_correct`` is overwritten** — this stage
      is idempotent and we want the latest LLM verdict if we ever
      re-run the pipeline on the same subtask.
    """
    # Touch every row for this subtask (one batched UPDATE later if we
    # want to optimize; for now a row-by-row walk keeps the logic clear
    # and the row count is small — brand_targets is one self + a few
    # competitors).
    all_rows = db.scalars(
        select(BrandMention).where(BrandMention.subtask_id == ctx.subtask_id)
    ).all()
    if not all_rows:
        return (0, 0, 0)

    # Short-circuit: no selling points → everything True.
    if not ctx.selling_points:
        for row in all_rows:
            row.is_correct = True
        return (len(all_rows), 0, 0)

    self_rows = [r for r in all_rows if r.is_self]
    if not self_rows:
        # Selling points exist but no self row to judge (shouldn't
        # happen — ``_ensure_target_rows`` always writes the self row
        # when ``project.brand`` is set). Defensive: leave comp rows
        # untouched, count as None.
        return (0, 0, 0)

    brand = self_rows[0].brand
    answer = (ctx.answer_content or "").strip()
    try:
        client = build_client_from_settings()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "extract %s: LLM client build failed (%s); is_correct stays None",
            ctx.subtask_id, exc,
        )
        for row in self_rows:
            row.is_correct = None
        return (0, 0, len(self_rows))

    verdict, reason = client.judge_brand_correctness_sync(
        selling_points=ctx.selling_points,
        brand=brand,
        answer=answer,
    )
    if reason:
        logger.info(
            "extract %s brand=%s correctness=%s reason=%s",
            ctx.subtask_id, brand, verdict, reason,
        )
    for row in self_rows:
        row.is_correct = verdict

    if verdict is True:
        return (len(self_rows), 0, 0)
    if verdict is False:
        return (0, len(self_rows), 0)
    return (0, 0, len(self_rows))