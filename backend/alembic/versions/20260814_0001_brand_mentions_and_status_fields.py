"""brand mentions + prompt/competitor status fields

Revision ID: 20260814_0001
Revises: 20260813_0001
Create Date: 2026-08-14

P0 of the analysis-side implementation:

1. New ``geo_brand_mentions`` table — one row per (subtask, brand_canonical)
   capturing everything the analysis UI needs to render KPIs and per-
   question deep-dives:

   - ``brand_canonical`` / ``brand_name``: the canonical form comes from
     ``Project.brand`` (self) or ``ProjectCompetitor.name``; ``brand_name``
     records whichever alias the regex actually matched so the UI can show
     "监控品牌 雅培瞬感" vs "雅培".
   - ``mention_count`` is filled by the regex pass — cheap, gives us
     "总提及次数" for free.
   - ``rank_position`` / ``sentiment_score`` / ``is_recommended`` /
     ``concern_hits_json`` come from the LLM pass and may be NULL if the
     LLM call failed (we still want the regex row so the count is right).
   - ``extract_status`` distinguishes rows the pipeline is still working
     on from rows it gave up on, so the UI can show "待抽取" honestly
     instead of pretending the data isn't there.

2. ``geo_project_prompts.category`` / ``.status`` — category powers the
   引流感 / 场景类 / etc. tabs in 问题提及分析; status lets users pause
   individual prompts without deleting them.

3. ``geo_project_competitors.origin`` / ``.status`` — origin distinguishes
   manual vs Agent-discovered (the existing ``geo_competitors`` table
   only stores per-task mentions); status gates the "Agent 自动发现"
   list (pending / confirmed / dismissed). Named ``origin`` (not
   ``source``) to avoid colliding with the unrelated
   ``Competitor.source`` column on ``geo_competitors``.

Per CLAUDE.md "外键约定": all cross-table columns are plain integers /
strings; ``geo_brand_mentions.subtask_id`` is the remote subTaskId so
deleting the parent Task must not cascade and orphan the rows.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260814_0001"
down_revision = "20260813_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_brand_mentions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("subtask_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("brand_canonical", sa.String(255), nullable=False),
        sa.Column("brand_name", sa.String(255), nullable=False),
        sa.Column("is_self", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("is_recommended", sa.Boolean(), nullable=True),
        sa.Column("concern_hits_json", sa.JSON(), nullable=True),
        sa.Column(
            "extract_status",
            sa.Enum(
                "pending",
                "success",
                "failed",
                "skipped",
                name="extract_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("extract_error", sa.Text(), nullable=True),
        sa.Column("raw_extraction", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "subtask_id",
            "brand_canonical",
            name="uq_brand_mention_subtask_brand",
        ),
    )
    op.create_index(
        "ix_brand_mentions_project_created",
        "geo_brand_mentions",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_brand_mentions_subtask",
        "geo_brand_mentions",
        ["subtask_id"],
    )

    with op.batch_alter_table("geo_project_prompts") as batch:
        batch.add_column(sa.Column("category", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column(
                "status",
                sa.Enum(
                    "monitoring",
                    "paused",
                    "archived",
                    name="prompt_status",
                ),
                nullable=False,
                server_default="monitoring",
            )
        )

    with op.batch_alter_table("geo_project_competitors") as batch:
        batch.add_column(
            sa.Column(
                "origin",
                sa.Enum(
                    "manual",
                    "auto_discovered",
                    name="competitor_origin",
                ),
                nullable=False,
                server_default="manual",
            )
        )
        batch.add_column(
            sa.Column(
                "status",
                sa.Enum(
                    "confirmed",
                    "pending",
                    "dismissed",
                    name="competitor_status",
                ),
                nullable=False,
                server_default="confirmed",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("geo_project_competitors") as batch:
        batch.drop_column("status")
        batch.drop_column("origin")

    with op.batch_alter_table("geo_project_prompts") as batch:
        batch.drop_column("status")
        batch.drop_column("category")

    op.drop_index("ix_brand_mentions_subtask", table_name="geo_brand_mentions")
    op.drop_index(
        "ix_brand_mentions_project_created", table_name="geo_brand_mentions"
    )
    op.drop_table("geo_brand_mentions")