"""Verify the Alembic initial schema migration against SQLite.

These tests never touch MySQL: they build a throwaway SQLite file database
per test and drive Alembic programmatically.

The 0002 migration (PK swap + FK removal) is MySQL-only — SQLite stops at
0001 and the test schema is instead assembled by ``Base.metadata.create_all``
which reflects the current SQLAlchemy model definitions. This lets the
SQLAlchemy test suite run fast and portable without re-implementing the
MySQL-specific ALTER TABLE statements.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "geo_admin_users",
    "geo_customers",
    "geo_projects",
    "geo_project_prompts",
    "geo_project_keywords",
    "geo_project_platforms",
    "geo_project_competitors",
    "geo_competitors",
    "geo_schedule_runs",
    "geo_tasks",
    "geo_subtasks",
    "geo_brand_mentions",
    "geo_callback_events",
    "geo_compensation_events",
}

# v2 removed these: schedule config is embedded in geo_projects.
REMOVED_TABLES = {"geo_schedules", "geo_schedule_slots"}


def make_config(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{db_path}")
    return cfg


@pytest.fixture()
def sqlite_db(tmp_path: Path) -> Path:
    return tmp_path / "migration_test.db"


@pytest.fixture()
def upgraded(sqlite_db: Path):
    """SQLite fixture: run migrations up to 0001, then build the rest of the
    schema from ``Base.metadata.create_all``. The 0002 PK swap is MySQL-only.
    """
    cfg = make_config(sqlite_db)
    command.upgrade(cfg, "20260810_0001")

    # Apply the post-0001 model state (PK swap, FK removal, etc.) directly
    # via SQLAlchemy metadata so the SQLite test schema reflects what MySQL
    # looks like after 0002.
    from app.db import Base

    Base.metadata.create_all(create_engine(f"sqlite+pysqlite:///{sqlite_db}"))

    engine = create_engine(f"sqlite+pysqlite:///{sqlite_db}")
    try:
        yield inspect(engine), cfg
    finally:
        engine.dispose()


def test_upgrade_creates_all_expected_tables(upgraded):
    inspector, _ = upgraded
    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES <= tables


def test_upgrade_does_not_create_v1_schedule_tables(upgraded):
    inspector, _ = upgraded
    assert REMOVED_TABLES & set(inspector.get_table_names()) == set()


def test_projects_have_embedded_schedule_columns(upgraded):
    inspector, _ = upgraded
    cols = {c["name"] for c in inspector.get_columns("geo_projects")}
    assert {
        "schedule_enabled",
        "slot1_hour",
        "slot1_minute",
        "slot2_hour",
        "slot2_minute",
        "description",
    } <= cols


def test_projects_unique_customer_code(upgraded):
    inspector, _ = upgraded
    constraints = inspector.get_unique_constraints("geo_projects")
    assert any(
        c["column_names"] == ["customer_id", "code"] for c in constraints
    ), constraints


def test_schedule_runs_keyed_by_project(upgraded):
    inspector, _ = upgraded
    cols = {c["name"] for c in inspector.get_columns("geo_schedule_runs")}
    assert "project_id" in cols
    assert "schedule_id" not in cols

    indexes = inspector.get_indexes("geo_schedule_runs")
    assert any(
        ix["column_names"] == ["project_id", "slot_index", "triggered_at"]
        for ix in indexes
    ), indexes

    uniques = inspector.get_unique_constraints("geo_schedule_runs")
    assert any(u["column_names"] == ["cooldown_key"] for u in uniques), uniques


def test_tasks_extension_columns(upgraded):
    inspector, _ = upgraded
    cols = {c["name"] for c in inspector.get_columns("geo_tasks")}
    assert {"customer_id", "project_id", "schedule_run_id"} <= cols
    assert "schedule_id" not in cols

    indexes = inspector.get_indexes("geo_tasks")
    index_cols = [ix["column_names"] for ix in indexes]
    assert ["project_id", "created_local_at"] in index_cols, index_cols
    assert ["customer_id", "created_local_at"] in index_cols, index_cols


def test_admin_users_have_role_and_customer(upgraded):
    inspector, _ = upgraded
    cols = {c["name"] for c in inspector.get_columns("geo_admin_users")}
    assert {"role", "customer_id"} <= cols


def test_downgrade_base_drops_everything(sqlite_db: Path):
    """0002 is MySQL-only; SQLite rolls back to 0001 → 0000."""
    cfg = make_config(sqlite_db)
    command.upgrade(cfg, "20260810_0001")
    command.downgrade(cfg, "base")
    engine = create_engine(f"sqlite+pysqlite:///{sqlite_db}")
    try:
        remaining = {
            t for t in inspect(engine).get_table_names() if t.startswith("geo_")
        }
    finally:
        engine.dispose()
    assert remaining == set()


def test_mysql_offline_ddl_is_generated(sqlite_db: Path, capsys):
    """Offline mode against a MySQL URL must render valid MySQL DDL for the
    migrations that do ship on MySQL (0000, 0001). 0002's PK swap is checked
    by running it against the live windx_dev DB instead."""
    cfg = make_config(sqlite_db)
    cfg.set_main_option("sqlalchemy.url", "mysql+pymysql://u:p@localhost/windx")
    command.upgrade(cfg, "20260810_0001", sql=True)
    sql = capsys.readouterr().out
    assert "CREATE TABLE geo_projects" in sql
    assert "ENUM" in sql.upper()


def test_question_analytics_indexes_upgrade_and_downgrade(sqlite_db: Path):
    """``20260818_0002`` adds two prefix-191 indexes for the question
    analytics lazy-loading path; this exercises both the upgrade (indexes
    appear) and the downgrade (indexes disappear) on SQLite.

    We can't walk Alembic from <base> through ``20260810_0002`` (the PK swap
    is MySQL-only and breaks SQLite), so we use ``Base.metadata.create_all``
    to materialize the post-MySQL-only schema, then ``stamp`` Alembic to
    ``20260818_0001`` and ``upgrade`` only the new revision. The MySQL
    ``mysql_length`` parameter is dialect-gated inside the migration, so
    SQLite still picks up the same two index names.

    ``Base.metadata.create_all`` will now also emit the two indexes (because
    the SQLAlchemy ``Subtask`` / ``BrandMention`` models declare them), so
    we drop them after ``create_all`` and let the alembic upgrade recreate
    them — that's the path this test is exercising.
    """
    import app.models  # noqa: F401  registers every model on Base.metadata
    from app.db import Base
    from sqlalchemy import text

    engine_url = f"sqlite+pysqlite:///{sqlite_db}"
    setup_engine = create_engine(engine_url)
    Base.metadata.create_all(setup_engine)
    # Drop the indexes the model layer just created so the alembic upgrade
    # below has work to do (and so we exercise the upgrade/downgrade path).
    with setup_engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_subtasks_prompt_updated"))
        conn.execute(
            text(
                "DROP INDEX IF EXISTS ix_brand_mentions_proj_self_prompt_created"
            )
        )
    setup_engine.dispose()

    cfg = make_config(sqlite_db)
    command.stamp(cfg, "20260818_0001")
    command.upgrade(cfg, "20260818_0002")

    insp = inspect(create_engine(engine_url))
    subtask_indexes = {ix["name"] for ix in insp.get_indexes("geo_subtasks")}
    mention_indexes = {ix["name"] for ix in insp.get_indexes("geo_brand_mentions")}
    assert "ix_subtasks_prompt_updated" in subtask_indexes
    assert "ix_brand_mentions_proj_self_prompt_created" in mention_indexes

    command.downgrade(cfg, "20260818_0001")

    insp = inspect(create_engine(engine_url))
    subtask_indexes = {ix["name"] for ix in insp.get_indexes("geo_subtasks")}
    mention_indexes = {ix["name"] for ix in insp.get_indexes("geo_brand_mentions")}
    assert "ix_subtasks_prompt_updated" not in subtask_indexes
    assert "ix_brand_mentions_proj_self_prompt_created" not in mention_indexes
