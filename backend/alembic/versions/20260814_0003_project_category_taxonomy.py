"""project-level category taxonomy for prompts

Revision ID: 20260814_0003
Revises: 20260814_0002
Create Date: 2026-08-14

Adds ``geo_projects.category_taxonomy`` (JSON, nullable). The list is the
authoritative set of category labels available to prompts in this project
and the order in which the 问题提及分析 subtabs render them.

Nullable: legacy projects keep working without a taxonomy — the UI falls
back to deriving categories from ``geo_project_prompts.category`` for
those rows. The taxonomy gets seeded implicitly the first time an admin
saves the project edit modal.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260814_0003"
down_revision = "20260814_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_projects",
        sa.Column("category_taxonomy", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_projects", "category_taxonomy")
