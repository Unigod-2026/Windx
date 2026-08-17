"""split monitor brand out of geo_project_keywords

Revision ID: 20260813_0001
Revises: 20260812_0001
Create Date: 2026-08-13

Two distinct concepts were being conflated into ``geo_project_keywords``:

- 「监控品牌」: exactly one per project, owns the ``aliases`` list. Must
  live on ``geo_projects`` so it can't be silently shadowed by extra
  keyword rows or reordered.
- 「核心词」: many per project, no aliases. Stays in
  ``geo_project_keywords``.

Earlier code shoved the brand into ``geo_project_keywords`` at
``sort=0`` by convention; that turned out to be fragile because the
edit-UI sent the brand to ``put_keywords`` and any drift between the
two rendered rows as either "lost the brand" or "brand treated as a
core keyword".

The migration:

1. Adds a nullable ``brand`` VARCHAR(255) to ``geo_projects``.
2. Backfills ``brand`` from each project's ``sort=0`` keyword row, so
   existing data keeps its meaning.
3. Deletes the ``sort=0`` rows so ``geo_project_keywords`` truly holds
   only core keywords going forward.
4. Leaves ``aliases`` (already on ``geo_projects``) untouched — it's
   already the correct home for the brand's alias list.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260813_0001"
down_revision = "20260812_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_projects") as batch:
        batch.add_column(sa.Column("brand", sa.String(255), nullable=True))

    # Backfill: pick the lexicographically-first sort=0 keyword per
    # project so projects with duplicate sort=0 rows still get exactly
    # one ``brand`` value. (The sort=0 invariant was maintained by the
    # ``_replace`` helper that always assigns ``sort=i`` on reinsert.)
    op.execute(
        sa.text(
            """
            UPDATE geo_projects p
            JOIN (
                SELECT project_id, MIN(id) AS min_id
                FROM geo_project_keywords
                WHERE sort = 0
                GROUP BY project_id
            ) first ON first.project_id = p.id
            JOIN geo_project_keywords k
                ON k.id = first.min_id
            SET p.brand = k.keyword
            """
        )
    )

    # Drop the rows we just consumed so the table only holds core
    # keywords. ``sort=0`` rows beyond the first (if any) also go away
    # so the table reaches the "1 brand on geo_projects, 0..N core
    # keywords on geo_project_keywords" invariant.
    op.execute(
        sa.text("DELETE FROM geo_project_keywords WHERE sort = 0")
    )


def downgrade() -> None:
    # Best-effort rollback: reinsert each project's brand back at
    # ``sort=0`` so the legacy read path (``keywords[0]``) keeps
    # working after the downgrade.
    op.execute(
        sa.text(
            """
            INSERT INTO geo_project_keywords (project_id, keyword, sort, created_at)
            SELECT id, brand, 0, NOW(6)
            FROM geo_projects
            WHERE brand IS NOT NULL AND brand <> ''
            """
        )
    )

    with op.batch_alter_table("geo_projects") as batch:
        batch.drop_column("brand")