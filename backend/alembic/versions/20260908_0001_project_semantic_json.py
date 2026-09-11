"""Add ``semantic_json`` column to ``geo_projects`` for wizard step 6.

Revision ID: 20260908_0001
Revises: 20260903_0003
Create Date: 2026-09-08

The wizard's new step 6 lets the operator declare their brand's official
identity (website / phone / social handles / selling points) so the
downstream analysis pass can score whether AI answers mention them.
We persist the payload as a single JSON column rather than splitting
into N VARCHAR columns because:

- The shape is expected to evolve alongside the frontend's
  ``SEMANTIC_FIELDS`` (see ``docs/风球GEO监控平台UI/js/data.js``); a JSON
  blob keeps that evolution migration-free.
- Approval flow prunes empty fields, so we never store the full 11-key
  shape with explicit ``null``s — only what the operator actually
  filled in. Read-side code should treat ``semantic_json=None`` and
  ``semantic_json={}`` identically.

The migration is additive only — no existing columns are touched, and
``nullable=True`` ensures legacy rows stay valid.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260908_0001"
down_revision = "20260903_0003"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    with op.batch_alter_table("geo_projects") as batch:
        batch.add_column(sa.Column("semantic_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("geo_projects") as batch:
        batch.drop_column("semantic_json")