"""geo_brand_mentions.sentiment_score: FLOAT -> VARCHAR(16)

Revision ID: 20260818_0001
Revises: 20260815_0002
Create Date: 2026-08-18

Rationale
---------
The Molizhishu ``/task/result/{taskId}/{subTaskId}`` endpoint returns
``sentiment`` as one of three discrete labels: ``positive`` / ``neutral``
/ ``negative``. The downstream extraction pipeline now reads this field
directly (no LLM extraction) and writes one of those three labels to
``geo_brand_mentions.sentiment_score``. The 0.0-1.0 float the previous
LLM-based pipeline wrote is no longer the natural type.

API consumers (dashboard KPIs in
``GET /projects/{id}/question-analytics`` and
``GET /projects/{id}/brand-mentions/summary``) still want a numeric
average for the existing UI color buckets (>=0.7 green / >=0.5 orange /
else red), so the aggregation layer translates the strings on the fly:
``positive -> 1.0``, ``neutral -> 0.5``, ``negative -> 0.0``. The DB
column type just needs to hold the labels.

Migration semantics
-------------------
Existing rows have float values written by the old LLM pipeline. None
of those values map cleanly to the new label set (a stale ``0.45`` was
never observed as a string), so we drop them in the upgrade. The next
sync tick will repopulate the column from ``Subtask.raw_result_json``
once the new extraction logic is in place. Downgrade is best-effort
(stringifies floats, which loses the LLM's nuance but lets the schema
revert cleanly).

The ``is_self`` index introduced by 20260814_0002 stays intact — it
covers the analytics queries' hot path.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260818_0001"
down_revision = "20260815_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clear the float values first — they were written by the LLM pipeline
    # and don't map to the new label vocabulary. The next sync tick will
    # refill them.
    op.execute("UPDATE geo_brand_mentions SET sentiment_score = NULL")
    with op.batch_alter_table("geo_brand_mentions") as batch:
        batch.alter_column(
            "sentiment_score",
            existing_type=sa.Float(),
            type_=sa.String(length=16),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Best-effort: keep the new VARCHAR data as strings so the float
    # column can be recreated. The previous LLM float values are lost.
    with op.batch_alter_table("geo_brand_mentions") as batch:
        batch.alter_column(
            "sentiment_score",
            existing_type=sa.String(length=16),
            type_=sa.Float(),
            existing_nullable=True,
        )