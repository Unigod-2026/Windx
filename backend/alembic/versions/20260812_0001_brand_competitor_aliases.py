"""brand / competitor aliases

Revision ID: 20260812_0001
Revises: 20260810_0002
Create Date: 2026-08-12

Add an ``aliases`` JSON column to both ``geo_projects`` (the monitor
brand) and ``geo_project_competitors`` so the user can record every
spelling / short-form of a brand that should be matched against the
remote AI's answer content.

JSON-typed nullable string lists keep the door open for additional
shapes (typed objects, locale splits) without another migration. The
field is intentionally nullable so the existing rows stay valid with
``aliases=NULL`` rather than ``[]`` — that distinction makes "has the
operator populated aliases yet?" trivially queryable.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260812_0001"
down_revision = "20260810_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_projects") as batch:
        batch.add_column(sa.Column("aliases", sa.JSON(), nullable=True))

    with op.batch_alter_table("geo_project_competitors") as batch:
        batch.add_column(sa.Column("aliases", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("geo_project_competitors") as batch:
        batch.drop_column("aliases")
    with op.batch_alter_table("geo_projects") as batch:
        batch.drop_column("aliases")