"""monitoring project extensions per docs.qq.com 风球监控需求 doc

Revision ID: 20260810_0001
Revises: 20260807_0001
Create Date: 2026-08-10

Three changes:

1. ``geo_projects`` gains three columns from the requirement doc:
   - ``sentiment_enabled`` (BOOL) — whether to score answers for sentiment +
     ranking. Currently we just persist the flag; the analyzer itself is
     out of scope for this migration.
   - ``region_strategy`` (VARCHAR(16)) — ``fixed`` (use ``region_codes``) or
     ``national_random`` (pick a random region per trigger). Stored as a
     plain string, NOT a SQL ENUM, so adding strategies later is a
     model-level change only.
   - ``region_codes`` (JSON, nullable) — list of fixed region codes used
     when ``region_strategy == 'fixed'``.

2. ``geo_project_platforms.mode`` is augmented with two dimensions:
   - ``delivery_mode`` (VARCHAR(16)) — ``web`` / ``mobile``. The existing
     ``mode`` column is left in place for backwards compatibility; new
     code reads ``delivery_mode``.
   - ``thinking_mode`` (BOOL) — whether to enable thinking/reasoning mode.

3. New table ``geo_project_competitors`` — user-defined competitor list per
   project. The existing ``geo_competitors`` table records *auto-extracted*
   competitor mentions from answer content (Task 9 ingestion); this new table
   is the project's *seed list* entered in the UI.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0001"
down_revision = "20260807_0001"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    # 1. geo_projects: sentiment + region
    with op.batch_alter_table("geo_projects") as batch:
        batch.add_column(
            sa.Column(
                "sentiment_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(
            sa.Column(
                "region_strategy",
                sa.Enum(
                    "fixed",
                    "national_random",
                    name="region_strategy",
                ),
                nullable=False,
                server_default="fixed",
            )
        )
        batch.add_column(
            sa.Column("region_codes", sa.JSON(), nullable=True)
        )

    # 2. geo_project_platforms: delivery + thinking
    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.add_column(
            sa.Column(
                "delivery_mode",
                sa.Enum(
                    "web",
                    "mobile",
                    name="delivery_mode",
                ),
                nullable=False,
                server_default="web",
            )
        )
        batch.add_column(
            sa.Column(
                "thinking_mode",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    # 3. geo_project_competitors: user-defined competitor list
    op.create_table(
        "geo_project_competitors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["geo_projects.id"],
            name="fk_project_competitors_project",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_project_competitors_project_name"
        ),
        **MYSQL_OPTS,
    )
    op.create_index(
        "ix_project_competitors_project_id",
        "geo_project_competitors",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_competitors_project_id", table_name="geo_project_competitors"
    )
    op.drop_table("geo_project_competitors")

    with op.batch_alter_table("geo_project_platforms") as batch:
        batch.drop_column("thinking_mode")
        batch.drop_column("delivery_mode")

    with op.batch_alter_table("geo_projects") as batch:
        batch.drop_column("region_codes")
        batch.drop_column("region_strategy")
        batch.drop_column("sentiment_enabled")