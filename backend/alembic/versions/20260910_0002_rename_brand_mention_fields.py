"""geo_brand_mentions: rename brand_canonical / mention_count / sentiment_score.

The old names were misleading:

- ``mention_count`` was 0/1 binary (regex pre-check, see CLAUDE.md
  §"品牌提及抽取状态"), not a real count; renamed to ``is_mention``
  for clarity. Aggregation code goes from ``WHERE mention_count > 0``
  to ``WHERE is_mention > 0`` (same row-set, just a semantic flip).
- ``brand_canonical`` had a redundant ``_canonical`` suffix — the
  ``brand_name`` column was dropped in 20260815_0002 and the
  canonical+alias lists on the parent tables are now the source of
  truth, so the per-mention row just needs ``brand``.
- ``sentiment_score`` held a discrete label (``positive`` /
  ``neutral`` / ``negative``), not a 0.0-1.0 numeric score (the
  aggregation layer translates to numbers). Renamed to ``sentiment``.

The UNIQUE constraint ``uq_brand_mention_subtask_brand`` and the index
``ix_brand_mentions_proj_brand_id`` already use ``brand`` in their
NAMES — they auto-track the column rename on MySQL, so no explicit
``RENAME INDEX`` is needed.

Alembic's MySQL dialect requires an explicit ``existing_type`` on
``alter_column(new_column_name=...)``; SQLite ignores it. The types
below mirror :class:`app.models.project.BrandMention`.

Revision ID: 20260910_0002
Revises: 20260910_0001
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260910_0002"
down_revision = "20260910_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "geo_brand_mentions",
        "brand_canonical",
        new_column_name="brand",
        existing_type=sa.String(255),
        existing_nullable=False,
    )
    op.alter_column(
        "geo_brand_mentions",
        "mention_count",
        new_column_name="is_mention",
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "geo_brand_mentions",
        "sentiment_score",
        new_column_name="sentiment",
        existing_type=sa.String(16),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "geo_brand_mentions",
        "sentiment",
        new_column_name="sentiment_score",
        existing_type=sa.String(16),
        existing_nullable=True,
    )
    op.alter_column(
        "geo_brand_mentions",
        "is_mention",
        new_column_name="mention_count",
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "geo_brand_mentions",
        "brand",
        new_column_name="brand_canonical",
        existing_type=sa.String(255),
        existing_nullable=False,
    )