"""Rebuild ``geo_brand_mentions`` from ``geo_subtasks`` against current brand_targets.

Run with::

    cd backend && uv run python -m scripts.backfill_brand_mentions

Destructive. Wipes every row in ``geo_brand_mentions`` and re-creates them
by iterating every ``geo_subtasks`` row for every project, running the
same regex pass the production pipeline uses. The new invariant — every
(subtask × brand_target) gets a row, with ``mention_count=1`` or ``0``
— holds end-to-end after this script runs.

Why destructive: the previous pipeline only wrote a row when the brand
was *mentioned*, so historical data has no rows for "this subtask didn't
mention the brand". Without those rows the per-question "提及率"
denominator is wrong (it counts only matched ones). Re-running the regex
pass against existing ``answer_content`` lets us backfill the missing
zero-rows honestly.

Tradeoffs the script does NOT undo:

- ``rank_position`` / ``sentiment_score`` / ``is_recommended`` /
  ``concern_hits_json`` stay NULL on the backfilled rows. Filling them
  needs the LLM pass, which is deliberately skipped here (would cost
  real tokens and the historical answer content may not match what the
  LLM would see today). Re-running
  ``app.services.extraction.extract_brand_mentions`` on the affected
  subtasks later would populate them; in the meantime the UI shows "—"
  / "待抽取" for those cells, which is honest.
- ``extract_status`` is set to ``PENDING`` for matched rows (signalling
  "regex saw the brand, LLM hasn't run") and ``SKIPPED`` for the rest.
  This mirrors the production pipeline's regex-only state.

Brand_targets are read from the project's *current* ``brand`` /
``aliases`` and *current* confirmed ``ProjectCompetitor`` list. If a
competitor was deleted between then and now, historical subtasks that
mentioned it will have no row in the backfilled data — that's by design,
because the brand is no longer in scope. (Re-adding the competitor and
re-running this script would re-create those rows.)
"""

from __future__ import annotations

import argparse
import re
import sys

from sqlalchemy import delete, func, select

from app.db import get_session_factory
from app.models.enums import ExtractStatus
from app.models.project import (
    BrandMention,
    Project,
    ProjectCompetitor,
)
from app.models.task import Subtask, Task


def _brand_needles(canonical: str, aliases: list[str] | None) -> list[str]:
    needles = [canonical]
    for a in aliases or []:
        if a and a.strip():
            needles.append(a)
    seen: set[str] = set()
    ordered: list[str] = []
    for n in needles:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


def _find_brand(text: str, needles: list[str]) -> bool:
    if not needles or not text.strip():
        return False
    pattern = re.compile("|".join(re.escape(n) for n in needles))
    return bool(pattern.search(text))


def _project_brand_targets(db, project: Project) -> list[tuple[str, list[str], bool]]:
    """Self brand + every confirmed competitor, in stable order.

    Returns ``[(canonical, aliases, is_self), ...]``. Competitors with
    empty / whitespace names are skipped — same guard the production
    pipeline applies.
    """
    out: list[tuple[str, list[str], bool]] = []
    canonical = (project.brand or "").strip()
    if canonical:
        out.append((canonical, list(project.aliases or []), True))
    competitors = db.scalars(
        select(ProjectCompetitor).where(
            ProjectCompetitor.project_id == project.id,
            ProjectCompetitor.status == "confirmed",
        )
    ).all()
    for c in competitors:
        name = (c.name or "").strip()
        if not name:
            continue
        out.append((name, list(c.aliases or []), False))
    return out


def backfill(*, dry_run: bool = False, batch: int = 5000) -> None:
    factory = get_session_factory()
    db = factory()
    try:
        projects = db.scalars(select(Project)).all()

        # task_id -> (project_id, created_local_at); pulled once so the
        # inner loop can attribute brand_mentions.created_at without an
        # N+1 lookup per subtask.
        task_meta: dict[str, tuple[int, "datetime | None"]] = {
            tid: (pid, created)
            for tid, pid, created in db.execute(
                select(Task.task_id, Task.project_id, Task.created_local_at)
            ).all()
        }

        total_existing = db.scalar(
            select(func.count()).select_from(BrandMention)
        ) or 0
        total_subtasks = 0
        total_written = 0

        if not dry_run:
            print(
                f"Wiping existing geo_brand_mentions rows ({total_existing})...",
                flush=True,
            )
            db.execute(delete(BrandMention))
            db.commit()

        for project in projects:
            targets = _project_brand_targets(db, project)
            if not targets:
                print(
                    f"project {project.id} ({project.name}): no brand targets, skipping",
                    flush=True,
                )
                continue

            project_task_ids = [
                tid for tid, (pid, _) in task_meta.items() if pid == project.id
            ]
            subtasks = db.execute(
                select(
                    Subtask.subtask_id,
                    Subtask.task_id,
                    Subtask.prompt,
                    Subtask.platform,
                    Subtask.answer_content,
                ).where(Subtask.task_id.in_(project_task_ids))
            ).all()
            total_subtasks += len(subtasks)

            print(
                f"project {project.id} ({project.name}): {len(targets)} brand target(s) "
                f"× {len(subtasks)} subtask(s)"
                + (" [dry-run]" if dry_run else ""),
                flush=True,
            )

            written_for_project = 0
            for sub_id, task_id, prompt, platform, answer_content in subtasks:
                text = answer_content or ""
                task_pid, task_created_at = task_meta[task_id]
                # Defensive: project_id can drift if Task rows were added
                # mid-script — sanity-check the resolved pid matches.
                assert task_pid == project.id, (
                    f"task {task_id} belongs to project {task_pid}, expected {project.id}"
                )
                created_at = task_created_at  # Task.created_local_at is non-null by spec
                for canonical, aliases, is_self in targets:
                    needles = _brand_needles(canonical, aliases)
                    matched = _find_brand(text, needles)
                    if dry_run:
                        written_for_project += 1
                        total_written += 1
                        continue
                    row = BrandMention(
                        subtask_id=sub_id,
                        task_id=task_id,
                        project_id=project.id,
                        customer_id=project.customer_id,
                        prompt=prompt,
                        platform=platform,
                        brand_canonical=canonical,
                        is_self=is_self,
                        mention_count=1 if matched else 0,
                        extract_status=(
                            ExtractStatus.PENDING
                            if matched
                            else ExtractStatus.SKIPPED
                        ),
                        created_at=created_at,
                    )
                    db.add(row)
                    written_for_project += 1
                    total_written += 1
                if not dry_run and written_for_project % batch == 0:
                    db.commit()
                    print(
                        f"  ... committed at {written_for_project} row(s) for project {project.id}",
                        flush=True,
                    )

            if not dry_run:
                db.commit()

        if dry_run:
            print(
                f"[dry-run] would have written {total_written} row(s) from {total_subtasks} subtask(s)",
                flush=True,
            )
            db.rollback()
        else:
            print(
                f"Done. Wrote {total_written} row(s) from {total_subtasks} subtask(s)."
            )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="walk everything but don't write / delete — useful for previewing scope",
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
    sys.exit(0)


if __name__ == "__main__":
    main()