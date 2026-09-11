"""Backfill ``geo_brand_mentions.is_correct`` for one project via the LLM judge.

Run with::

    cd backend && uv run python -m scripts.backfill_is_correct --project-id 38

Why a separate script:
- The live extraction pipeline (``app.services.extraction``) loads the
  full ``Project`` ORM object, but the current ``Project`` model still
  declares the legacy ``slot1_hour`` / ``slot2_hour`` columns that the
  DB no longer has (pre-existing schema drift, see
  ``alembic/versions/20260903_0003_project_weekly_schedule.py``).
  Hitting ``extract_brand_mentions`` against MySQL therefore 1054s on
  the column select. This script bypasses the ORM and talks to MySQL
  via raw SQL.
- We only need to read two things from the DB per subtask:
  ``Subtask.answer_content`` and ``Project.semantic_json``. Both are
  simple text / JSON columns that don't suffer the schema drift.

One LLM call per distinct ``subtask_id`` with at least one
``is_self=true`` row in scope; the verdict is broadcast to every self
row for that subtask in one ``UPDATE``. Competitor (``is_self=false``)
rows are not touched (they stay ``is_correct=NULL`` per the user spec
"仅 self 行,其他行没有意义").

Resumable: skips subtasks whose self rows already have a non-NULL
``is_correct`` so a re-run only does the missing work. Commit per
subtask so a Ctrl-C mid-run keeps the partial progress.

Output: prints progress every subtask and a final summary
(judged / failed / skipped).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.services.llm_client import build_client_from_settings


logger = logging.getLogger("backfill_is_correct")


def _load_project(engine: Engine, project_id: int) -> tuple[str, list[str]]:
    """Return ``(brand, selling_points)`` for the project via raw SQL.

    Bypasses the Project ORM (which has stale column declarations
    — see module docstring).
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT brand, semantic_json FROM geo_projects WHERE id = :pid"),
            {"pid": project_id},
        ).first()
    if row is None:
        raise SystemExit(f"project {project_id} not found")
    brand = (row.brand or "").strip()
    if not brand:
        raise SystemExit(f"project {project_id} has no brand configured")
    sj = row.semantic_json
    if isinstance(sj, str):
        import json
        sj = json.loads(sj) if sj else None
    raw_points = sj.get("selling_points") if isinstance(sj, dict) else None
    selling_points: list[str] = []
    if isinstance(raw_points, list):
        seen: set[str] = set()
        for pt in raw_points:
            if not isinstance(pt, str):
                continue
            cleaned = pt.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            selling_points.append(cleaned)
            if len(selling_points) >= 10:
                break
    return brand, selling_points


def _list_pending_self_subtasks(engine: Engine, project_id: int) -> list[str]:
    """Distinct subtask_ids that still have ``is_correct IS NULL`` self rows.

    Excludes subtasks where every self row is already judged (the
    script is resumable).
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT subtask_id
                FROM geo_brand_mentions
                WHERE project_id = :pid
                  AND is_self = 1
                  AND is_correct IS NULL
                ORDER BY subtask_id
                """
            ),
            {"pid": project_id},
        ).fetchall()
    return [r.subtask_id for r in rows]


def _load_answer(engine: Engine, subtask_id: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT answer_content FROM geo_subtasks WHERE subtask_id = :sid"),
            {"sid": subtask_id},
        ).first()
    if row is None:
        return None
    return row.answer_content or ""


def _apply_verdict(
    engine: Engine, project_id: int, subtask_id: str, verdict: bool | None,
) -> int:
    """Write ``is_correct`` on every self row for this subtask. Returns row count."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE geo_brand_mentions
                SET is_correct = :verdict
                WHERE project_id = :pid
                  AND subtask_id = :sid
                  AND is_self = 1
                """
            ),
            {"verdict": int(verdict) if verdict is not None else None,
             "pid": project_id, "sid": subtask_id},
        )
    return result.rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N subtasks (useful for dry-run on the first few).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)

    brand, selling_points = _load_project(engine, args.project_id)
    logger.info(
        "project %d: brand=%r selling_points=%s",
        args.project_id, brand, selling_points,
    )
    if not selling_points:
        logger.error(
            "project %d has no selling_points in semantic_json — aborting "
            "(without selling_points the spec is to short-circuit is_correct=True, "
            "not run the LLM judge)",
            args.project_id,
        )
        sys.exit(2)

    pending = _list_pending_self_subtasks(engine, args.project_id)
    if args.limit is not None:
        pending = pending[: args.limit]
    logger.info("pending subtasks to judge: %d", len(pending))
    if not pending:
        logger.info("nothing to do; all self rows already have is_correct set")
        return

    client = build_client_from_settings()
    t_start = time.time()
    judged = 0
    failed = 0
    for i, sid in enumerate(pending, 1):
        answer = _load_answer(engine, sid)
        if not answer:
            # Empty answer → no conflict → True per prompt rule; skip LLM.
            logger.info(
                "[%d/%d] %s: empty answer, set True", i, len(pending), sid[:20],
            )
            _apply_verdict(engine, args.project_id, sid, True)
            judged += 1
            continue

        t0 = time.time()
        verdict, reason = client.judge_brand_correctness_sync(
            selling_points=selling_points,
            brand=brand,
            answer=answer,
        )
        elapsed = time.time() - t0
        rows = _apply_verdict(engine, args.project_id, sid, verdict)
        verdict_s = "TRUE" if verdict is True else "FALSE" if verdict is False else "NULL"
        if verdict is None:
            failed += 1
        else:
            judged += 1
        logger.info(
            "[%d/%d] %s: verdict=%s rows=%d elapsed=%.1fs reason=%r",
            i, len(pending), sid[:20], verdict_s, rows, elapsed, reason,
        )

    total = time.time() - t_start
    logger.info(
        "done: judged=%d failed=%d total_time=%dm%.1fs",
        judged, failed, int(total // 60), total % 60,
    )


if __name__ == "__main__":
    main()
