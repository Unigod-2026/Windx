"""geo_brand_mentions + geo_tasks index tuning

Revision ID: 20260814_0002
Revises: 20260814_0001
Create Date: 2026-08-14

Adds the secondary indexes needed by the Overview / brand-mention list
endpoints and drops one redundant index. The dev EXPLAIN at ~7K rows still
prefers a full table scan (the optimizer's cost model says a seq scan beats
index lookup at this size), so the win on the seeded dev DB is small; on
production-scale rows (100K+) these are the indexes that keep the queries
in the millisecond range.

geo_brand_mentions
==================

Dropped: ``ix_brand_mentions_subtask`` is redundant — the leading column
of the UNIQUE constraint ``uq_brand_mention_subtask_brand`` already
provides an equivalent lookup path.

Added:

- ``ix_brand_mentions_proj_self_created (project_id, is_self, created_at)``
  Covers the Overview KPI window
  (``project_id=? AND is_self=true AND created_at BETWEEN ? AND ?``) and
  the ``/brand-mentions/summary`` endpoint. ``is_self`` leads after
  ``project_id`` because it is the most selective filter for a 6-platform
  project (≈ 1/6 of rows).

- ``ix_brand_mentions_proj_self_id (project_id, is_self, id)``
  Covers the default brand-mention list (filtered by ``is_self``,
  ordered by ``id DESC``). ``id`` is appended so the same key satisfies
  the ORDER BY without a sort.

- ``ix_brand_mentions_proj_brand_id (project_id, brand_canonical, id)``
  Covers the brand-mention list filtered by a single ``brand_canonical``
  (competitor-analysis tab), again appending ``id`` for ORDER BY.

The existing ``ix_brand_mentions_project_created`` is left in place —
it is still useful for project-wide queries that don't filter on
``is_self`` (e.g. admin tooling, export jobs).

geo_tasks
=========

Added: ``ix_tasks_project_task (project_id, task_id)``
Covers ``WHERE project_id=? ORDER BY task_id DESC LIMIT N`` (used by
``GET /tasks`` and the project-detail task list). The existing
``ix_tasks_project_created`` is sorted by ``created_local_at`` and cannot
satisfy this ORDER BY without a filesort; the new index can.
"""
from __future__ import annotations

from alembic import op

revision = "20260814_0002"
down_revision = "20260814_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- geo_brand_mentions ---
    op.drop_index(
        "ix_brand_mentions_subtask",
        table_name="geo_brand_mentions",
    )
    op.create_index(
        "ix_brand_mentions_proj_self_created",
        "geo_brand_mentions",
        ["project_id", "is_self", "created_at"],
    )
    op.create_index(
        "ix_brand_mentions_proj_self_id",
        "geo_brand_mentions",
        ["project_id", "is_self", "id"],
    )
    op.create_index(
        "ix_brand_mentions_proj_brand_id",
        "geo_brand_mentions",
        ["project_id", "brand_canonical", "id"],
    )

    # --- geo_tasks ---
    op.create_index(
        "ix_tasks_project_task",
        "geo_tasks",
        ["project_id", "task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_project_task", table_name="geo_tasks")

    op.drop_index(
        "ix_brand_mentions_proj_brand_id",
        table_name="geo_brand_mentions",
    )
    op.drop_index(
        "ix_brand_mentions_proj_self_id",
        table_name="geo_brand_mentions",
    )
    op.drop_index(
        "ix_brand_mentions_proj_self_created",
        table_name="geo_brand_mentions",
    )
    op.create_index(
        "ix_brand_mentions_subtask",
        "geo_brand_mentions",
        ["subtask_id"],
    )
