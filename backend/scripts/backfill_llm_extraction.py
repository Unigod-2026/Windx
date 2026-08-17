"""Run the LLM extraction pass against every pending ``geo_brand_mentions`` row.

Run with::

    cd backend && uv run python -m scripts.backfill_llm_extraction

The dev ``.env`` sets ``LLM_MAX_CONCURRENCY=4`` (minimax plan limit);
the script honors ``--concurrency`` so the operator can dial it.

What it does:

- Selects every distinct ``subtask_id`` whose brand_mention rows are
  in ``extract_status=PENDING``. Each such subtask needs the LLM pass.
- For each subtask, calls ``extract_brand_mentions_async(subtask_id)``
  under an ``asyncio.Semaphore`` to bound concurrent API calls.
- The existing extraction pipeline handles per-row success / failure,
  status transitions (``PENDING → SUCCESS / FAILED``), and the
  commit boundary — this script is just a driver.

What it does NOT do:

- It does not re-run the regex pass. ``mention_count`` was filled by
  ``backfill_brand_mentions.py`` (or the live pipeline); re-running
  ``extract_brand_mentions_async`` keeps those values intact.
- It does not touch rows with ``extract_status`` other than
  ``PENDING``. ``SUCCESS`` rows already have LLM data, ``SKIPPED``
  rows had no brand mention so the LLM was never needed, and
  ``FAILED`` rows are the LLM pass's terminal verdict on a previous
  attempt — re-running would just retry-and-overwrite those, which is
  surprising; if you want to retry failures, flip them back to
  ``PENDING`` manually.

Tradeoffs:

- Real LLM calls. With 7686 PENDING rows × ~4s per call / 4-way
  concurrency, expect ~1.5h wall-clock for a full sweep on dev.
- Use ``--limit`` / ``--dry-run`` to preview scope before committing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from sqlalchemy import distinct, func, select

from app.db import get_session_factory
from app.models.enums import ExtractStatus
from app.models.project import BrandMention
from app.services.extraction import extract_brand_mentions_async


async def _run_one(
    sem: asyncio.Semaphore,
    subtask_id: str,
    *,
    completed: dict[str, int],
    failed_ids: list[str],
    lock: asyncio.Lock,
) -> None:
    """One subtask under the shared concurrency semaphore."""
    async with sem:
        # Per-subtask the pipeline owns its own session + commit. We
        # only count the outcome for the progress line.
        result = await extract_brand_mentions_async(subtask_id)
        async with lock:
            completed[subtask_id] = result.rows_succeeded
            if result.rows_failed:
                failed_ids.append(subtask_id)


async def _backfill(
    *,
    subtask_ids: list[str],
    concurrency: int,
    progress_every: int,
) -> None:
    sem = asyncio.Semaphore(concurrency)
    completed: dict[str, int] = {}
    failed_ids: list[str] = []
    lock = asyncio.Lock()
    started = time.monotonic()
    total = len(subtask_ids)

    async def _wrapped(i: int, sid: str) -> None:
        await _run_one(sem, sid, completed=completed, failed_ids=failed_ids, lock=lock)
        if (i + 1) % progress_every == 0 or i + 1 == total:
            elapsed = time.monotonic() - started
            rate = (i + 1) / elapsed if elapsed else 0.0
            print(
                f"[{i + 1}/{total}] {rate:.2f} subtask/s, "
                f"elapsed {elapsed / 60:.1f}min, "
                f"failed_subtasks={len(failed_ids)}",
                flush=True,
            )

    await asyncio.gather(*(_wrapped(i, sid) for i, sid in enumerate(subtask_ids)))

    elapsed = time.monotonic() - started
    total_rows = sum(completed.values())
    print(
        f"Done in {elapsed / 60:.1f}min. "
        f"rows_succeeded={total_rows}, "
        f"subtasks_with_failures={len(failed_ids)}"
    )
    if failed_ids:
        sample = failed_ids[:5]
        print(f"  first few failed: {sample}", flush=True)


def _select_pending_subtask_ids(limit: int | None) -> list[str]:
    """All distinct subtask_ids that have at least one PENDING row.

    Sorted by ``min(id)`` (oldest PENDING first) so a partial run
    always works the earliest missing data; this matters because the
    scheduler may be writing new PENDING rows concurrently and we want
    the visible KPI improvements to show up early.
    """
    factory = get_session_factory()
    db = factory()
    try:
        # Find one PENDING row id per subtask, ordered by the oldest.
        # ``subtask_id`` is a 32-char hex string — sort lexicographically
        # by it for a stable, deterministic order.
        stmt = (
            select(BrandMention.subtask_id, func.min(BrandMention.id))
            .where(BrandMention.extract_status == ExtractStatus.PENDING)
            .group_by(BrandMention.subtask_id)
            .order_by(BrandMention.subtask_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [sid for sid, _ in db.execute(stmt).all()]
    finally:
        db.close()


def backfill(
    *,
    limit: int | None = None,
    concurrency: int = 4,
    dry_run: bool = False,
    progress_every: int = 10,
) -> None:
    subtask_ids = _select_pending_subtask_ids(limit)
    n_pending_rows = _count_pending_rows(subtask_ids) if subtask_ids else 0
    print(
        f"Plan: subtasks={len(subtask_ids)}, pending_rows={n_pending_rows}, "
        f"concurrency={concurrency}, "
        + ("[dry-run]" if dry_run else ""),
        flush=True,
    )
    if dry_run or not subtask_ids:
        return
    asyncio.run(
        _backfill(
            subtask_ids=subtask_ids,
            concurrency=concurrency,
            progress_every=progress_every,
        )
    )


def _count_pending_rows(subtask_ids: list[str]) -> int:
    if not subtask_ids:
        return 0
    factory = get_session_factory()
    db = factory()
    try:
        return (
            db.scalar(
                select(func.count())
                .select_from(BrandMention)
                .where(
                    BrandMention.subtask_id.in_(subtask_ids),
                    BrandMention.extract_status == ExtractStatus.PENDING,
                )
            )
            or 0
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only process the first N subtasks (sorted oldest-first)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="max concurrent LLM subtasks (default 4 to match minimax plan)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan but don't call the LLM",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="print a status line every N subtasks (default 10)",
    )
    args = parser.parse_args()
    backfill(
        limit=args.limit,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()