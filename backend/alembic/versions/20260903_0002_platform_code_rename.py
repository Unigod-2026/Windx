"""Rename ``geo_project_platforms.mobile_code`` → ``platform_code`` and
backfill web rows so the column holds the resolved API platform string for
EVERY row (web or mobile), not just mobile ones. The scheduler now reads
``platform_code`` unconditionally.

Revision ID: 20260903_0002
Revises: 20260903_0001
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260903_0002"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.alter_column(
            "mobile_code",
            new_column_name="platform_code",
            existing_type=sa.String(32),
            existing_nullable=True,
        )
    # Backfill: previously NULL on web (pc) rows; now those rows should carry
    # the wizard value (the same string the API accepts for the web surface).
    op.execute(
        "UPDATE geo_project_platforms SET platform_code = platform WHERE platform_code IS NULL"
    )
    # Lock the column to NOT NULL — the scheduler reads it verbatim on every
    # row, so a NULL would translate into a missing entry in the submission
    # payload. ORM and the schema parity test both expect NOT NULL.
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.alter_column(
            "platform_code",
            existing_type=sa.String(32),
            nullable=False,
        )


def downgrade() -> None:
    # Undo the NOT NULL constraint, then the backfill, then the rename.
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.alter_column(
            "platform_code",
            existing_type=sa.String(32),
            nullable=True,
        )
    op.execute(
        "UPDATE geo_project_platforms SET platform_code = NULL WHERE platform_code = platform"
    )
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.alter_column(
            "platform_code",
            new_column_name="mobile_code",
            existing_type=sa.String(32),
            existing_nullable=True,
        )