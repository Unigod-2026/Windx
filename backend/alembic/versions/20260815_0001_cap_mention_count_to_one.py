"""cap mention_count to 1

Revision ID: 20260815_0001
Revises: 20260814_0003
Create Date: 2026-08-15

Problem statement (from the operator): the 问题提及分析 page surfaces
"整体提及次数" as ``SUM(mention_count)`` and "提及率" as ``top3 / rows``.
The regex pass had been writing the literal hit count (e.g. 5 times in
one answer → ``mention_count = 5``), which inflated both metrics: a
single (question × model) answer that mentioned the brand 5 times would
be counted as 5 instead of 1.

Per the 2026-08-15 spec change:

- A row only exists in ``geo_brand_mentions`` when the brand appears in
  the answer at all (the regex pass skips otherwise), so the count is
  binary by definition.
- Cap any historical ``mention_count > 1`` to 1 so the
  ``SUM(mention_count) == COUNT(rows)`` invariant holds for the
  overview / summary endpoints and the QuestionTab UI.

Per-row max is 1, not 0, because the regex pass guarantees a row was
created only when the brand matched — capping to 0 would silently zero
out mentions the regex had already detected. Existing rows where
``mention_count = 0`` are a separate legacy artefact (manual insert
with no match) and are left alone here; the runtime extraction no
longer produces them.

This migration only updates data; it does not change the column type
(smallest correct shape is still ``Integer`` even when the runtime
always writes 0 or 1).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0001"
down_revision = "20260814_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain UPDATE with a literal — portable across MySQL 8 and SQLite
    # (the test DB) without depending on the ``LEAST`` / ``min`` dialect
    # difference. We know we want to land on exactly 1, so no CASE is
    # needed.
    op.execute(
        sa.text(
            "UPDATE geo_brand_mentions "
            "SET mention_count = 1 "
            "WHERE mention_count > 1"
        )
    )


def downgrade() -> None:
    # No-op: we don't have the original counts stored anywhere. The
    # downgrade path therefore is information-losing — same shape the
    # rest of the migration history follows (we don't drop columns we
    # can't recreate from data either).
    pass