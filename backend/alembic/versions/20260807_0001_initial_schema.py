"""initial schema: molizhishu ingestion + customer/project/schedule management

Revision ID: 20260807_0001
Revises:
Create Date: 2026-08-07

This is the initial schema for the whole backend. It creates both the
"模力指数 API 接入" tables (geo_tasks / geo_subtasks / geo_callback_events /
geo_compensation_events / geo_admin_users) and the schedule-management tables
described in docs/superpowers/specs/2026-08-07-schedule-management-design.md §1.

v2 note: there are no `geo_schedules` / `geo_schedule_slots` tables. Schedule
configuration is embedded 1:1 into `geo_projects` and executions are recorded
per project in `geo_schedule_runs`.

All DATETIME columns are naive local time; the container and MySQL session both
run in Asia/Shanghai (see CLAUDE.md). Remote millisecond epochs are stored as
BIGINT to stay lossless.

No foreign keys
---------------
This migration (and every subsequent one) intentionally declares zero
``ForeignKeyConstraint`` blocks. Every relationship between rows is
expressed as a plain indexed column plus a SQLAlchemy ``relationship`` on
the ORM side. See CLAUDE.md "外键约定" for the rationale.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260807_0001"
down_revision = None
branch_labels = None
depends_on = None

# Applied to every table; ignored by SQLite, required by MySQL for FK support
# and 4-byte UTF-8 (AI answers routinely contain emoji).
MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    op.create_table(
        "geo_customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("logo_path", sa.String(255), nullable=True),
        sa.Column("contact", sa.String(128), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", name="customer_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_customers_code"),
        **MYSQL_OPTS,
    )

    op.create_table(
        "geo_admin_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column(
            "role",
            sa.Enum("super_admin", "customer_admin", name="admin_role"),
            nullable=False,
            server_default="super_admin",
        ),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", name="admin_status"),
            nullable=False,
            server_default="active",
        ),
        # NULL for super_admin, required for customer_admin (enforced in the API layer).
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username", name="uq_admin_users_username"),
        **MYSQL_OPTS,
    )

    op.create_table(
        "geo_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "disabled", name="project_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        # Embedded schedule (v2): 1:1 with the project, 1-2 daily slots.
        sa.Column(
            "schedule_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("slot1_hour", sa.SmallInteger(), nullable=True),
        sa.Column("slot1_minute", sa.SmallInteger(), nullable=True),
        sa.Column("slot2_hour", sa.SmallInteger(), nullable=True),
        sa.Column("slot2_minute", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("customer_id", "code", name="uq_project_customer_code"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_projects_customer_id", "geo_projects", ["customer_id"])
    op.create_index("ix_projects_schedule_enabled", "geo_projects", ["schedule_enabled"])

    op.create_table(
        "geo_project_prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL_OPTS,
    )
    op.create_index("ix_project_prompts_project_id", "geo_project_prompts", ["project_id"])

    op.create_table(
        "geo_project_keywords",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL_OPTS,
    )
    op.create_index("ix_project_keywords_project_id", "geo_project_keywords", ["project_id"])

    op.create_table(
        "geo_project_platforms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("screenshot", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_project_platforms_project_id", "geo_project_platforms", ["project_id"])

    # Created before geo_tasks so the ScheduleRun row can be reserved
    # before the Task row exists. Both directions of the run↔task link
    # (geo_tasks.schedule_run_id and geo_schedule_runs.task_id) are plain
    # indexed columns — no FK on either side (see module docstring).
    op.create_table(
        "geo_schedule_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        # 1 or 2 for cron slots, 0 for manual triggers.
        sa.Column("slot_index", sa.SmallInteger(), nullable=False),
        sa.Column(
            "trigger_type",
            sa.Enum("cron", "manual", name="run_trigger"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "success", "failed", "skipped", name="run_status"
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # project-{id}-slot-{idx}-{YYYYMMDDHH}{floor(minute/5)} — 5 minute dedupe window.
        sa.Column("cooldown_key", sa.String(64), nullable=True),
        sa.UniqueConstraint("cooldown_key", name="uq_schedule_runs_cooldown_key"),
        sa.CheckConstraint("slot_index IN (0, 1, 2)", name="ck_run_slot_index_range"),
        **MYSQL_OPTS,
    )
    op.create_index(
        "ix_runs_project_slot_triggered",
        "geo_schedule_runs",
        ["project_id", "slot_index", "triggered_at"],
    )

    op.create_table(
        "geo_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Remote taskId (32-char hex), see docs/api/submit-task.md.
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("prompts_json", sa.JSON(), nullable=True),
        sa.Column("platforms_json", sa.JSON(), nullable=True),
        sa.Column("region_code_json", sa.JSON(), nullable=True),
        sa.Column("callback_url", sa.String(512), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("completed_items", sa.Integer(), nullable=True),
        sa.Column("failed_items", sa.Integer(), nullable=True),
        sa.Column("poll_url", sa.String(512), nullable=True),
        # Remote epoch milliseconds, stored verbatim.
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("completed_at", sa.BigInteger(), nullable=True),
        sa.Column("raw_request_json", sa.JSON(), nullable=True),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_local_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # Multi-tenant / schedule linkage (all nullable: ad-hoc tasks have none).
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("task_id", name="uq_tasks_task_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_tasks_status", "geo_tasks", ["status"])
    op.create_index(
        "ix_tasks_customer_created", "geo_tasks", ["customer_id", "created_local_at"]
    )
    op.create_index(
        "ix_tasks_project_created", "geo_tasks", ["project_id", "created_local_at"]
    )

    op.create_table(
        "geo_subtasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("subtask_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("mode", sa.String(32), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("time", sa.String(64), nullable=True),
        sa.Column("page_screenshot", sa.String(1024), nullable=True),
        # Stored verbatim: the backend never sanitises answerContent.
        sa.Column("answer_content", sa.Text(), nullable=True),
        sa.Column("reference_list_json", sa.JSON(), nullable=True),
        sa.Column("citation_list_json", sa.JSON(), nullable=True),
        sa.Column("reasoning_process_json", sa.JSON(), nullable=True),
        sa.Column("recommended_questions_json", sa.JSON(), nullable=True),
        sa.Column("media_content_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("proxy_ip", sa.String(64), nullable=True),
        sa.Column("raw_result_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subtask_id", name="uq_subtasks_subtask_id"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_subtasks_task_id", "geo_subtasks", ["task_id"])

    op.create_table(
        "geo_competitors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("subtask_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "source",
            sa.Enum("answer_content", "reference_list", name="competitor_source"),
            nullable=False,
        ),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL_OPTS,
    )
    op.create_index("ix_competitors_task_id", "geo_competitors", ["task_id"])

    # Callbacks may arrive before the task row exists, so task_id holds the raw
    # remote taskId with no FK — see docs/api/callback.md (idempotent upsert).
    op.create_table(
        "geo_callback_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "process_status",
            sa.Enum("processed", "duplicate", "failed", name="callback_process_status"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("task_id", "payload_hash", name="uq_callback_task_hash"),
        **MYSQL_OPTS,
    )

    op.create_table(
        "geo_compensation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("request_url", sa.String(512), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("code", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        **MYSQL_OPTS,
    )
    op.create_index("ix_compensation_task_id", "geo_compensation_events", ["task_id"])


def downgrade() -> None:
    op.drop_table("geo_compensation_events")
    op.drop_table("geo_callback_events")
    op.drop_table("geo_competitors")
    op.drop_table("geo_subtasks")
    op.drop_table("geo_tasks")
    op.drop_table("geo_schedule_runs")
    op.drop_table("geo_project_platforms")
    op.drop_table("geo_project_keywords")
    op.drop_table("geo_project_prompts")
    op.drop_table("geo_projects")
    op.drop_table("geo_admin_users")
    op.drop_table("geo_customers")
