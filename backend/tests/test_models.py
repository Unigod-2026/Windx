"""ORM model tests.

Two things are verified here:

1. **Schema parity** — ``Base.metadata`` (the models) must describe exactly the
   same schema as the Alembic migration. We point the migrated and the
   model-built schemas at the same MySQL ``windx_parity_<pid>`` database
   and compare them column-by-column. This is the guard against
   model/migration drift, which is otherwise only discovered in production.
   The throwaway MySQL DB is self-contained inside the ``schema_pair``
   fixture.
2. **Behaviour** — enum values, relationship loading/ordering, cascades,
   timestamp defaults and the embedded-schedule helpers. SQLite in-memory
   is enough for these (no MySQL-specific features exercised).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command
from app.db import Base
from app.models import (
    AdminUser,
    BrandMention,
    CallbackEvent,
    Competitor,
    CompensationEvent,
    Customer,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
    ScheduleRun,
    Subtask,
    Task,
)
from app.models.common import SHANGHAI, now_local
from app.models.enums import (
    AdminRole,
    AdminStatus,
    CallbackProcessStatus,
    CompetitorOrigin,
    CompetitorSource,
    CompetitorStatus,
    CustomerStatus,
    ExtractStatus,
    ProjectStatus,
    PromptStatus,
    RunStatus,
    RunTrigger,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(
    bind=test_engine, autoflush=False, autocommit=False, future=True
)


@pytest.fixture(autouse=True)
def _setup_db():
    """Rebuild the SQLite schema per test so each starts from a clean slate."""
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture()
def db_session():
    with TestSessionLocal() as session:
        yield session


@pytest.fixture()
def customer(db_session: Session):
    c = Customer(name="示例客户", code="demo")
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture()
def project(db_session: Session, customer: Customer):
    p = Project(customer_id=customer.id, name="示例项目", code="proj-a")
    db_session.add(p)
    db_session.commit()
    return p


# --------------------------------------------------------------------------
# 1. Schema parity: models vs. migration
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_pair():
    """Reflect the migration-built schema and the model-built schema.

    Runs against a throwaway MySQL database (``windx_parity_<pid>``) so the
    snapshot doesn't conflict with the SQLite in-memory engine used by the
    behaviour tests. The database is created on entry and dropped on exit.
    """
    import os as _os
    import pymysql as _pm
    import re as _re
    from pathlib import Path as _Path
    from sqlalchemy import text as _text

    # The behaviour tests don't need a real MySQL — only the parity test does.
    # ``DATABASE_URL`` lives in the repo-root ``.env`` (not in ``backend/``).
    if "DATABASE_URL" not in _os.environ:
        env_path = _Path(__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            for _line in env_path.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _os.environ.setdefault(_k.strip(), _v.strip())

    dev_url = _os.environ["DATABASE_URL"]
    parts = _re.match(
        r"mysql\+pymysql://([^:]+):([^@]+)@([^:]+):(\d+)/(\w+)(\?.*)?", dev_url
    ).groups()
    user, pwd, host, port, _, qs = parts
    parity_db = f"windx_parity_{_os.getpid()}"
    parity_url = (
        f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{parity_db}"
        + (qs or "")
    )

    # Create the parity database.
    bootstrap = _pm.connect(host=host, port=int(port), user=user, password=pwd)
    try:
        with bootstrap.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{parity_db}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        bootstrap.commit()
    finally:
        bootstrap.close()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", parity_url)

    parity_engine = create_engine(parity_url, future=True)

    def _drop_all() -> None:
        with parity_engine.begin() as conn:
            conn.execute(_text("SET FOREIGN_KEY_CHECKS=0"))
            for tbl in conn.execute(_text("SHOW TABLES")).fetchall():
                conn.execute(_text(f"DROP TABLE IF EXISTS `{tbl[0]}`"))
            conn.execute(_text("SET FOREIGN_KEY_CHECKS=1"))

    try:
        # 1. Migrated schema.
        _drop_all()
        command.upgrade(cfg, "head")

        migrated_inspect = inspect(parity_engine)
        migrated_snapshot = {
            t: {
                "columns": {c["name"]: c for c in migrated_inspect.get_columns(t)},
                "indexes": migrated_inspect.get_indexes(t),
                "uniques": migrated_inspect.get_unique_constraints(t),
                "fks": migrated_inspect.get_foreign_keys(t),
            }
            for t in migrated_inspect.get_table_names()
            if t != "alembic_version"
        }

        # 2. Model-built schema.
        _drop_all()
        Base.metadata.create_all(parity_engine)

        model_inspect = inspect(parity_engine)
        model_snapshot = {
            t: {
                "columns": {c["name"]: c for c in model_inspect.get_columns(t)},
                "indexes": model_inspect.get_indexes(t),
                "uniques": model_inspect.get_unique_constraints(t),
                "fks": model_inspect.get_foreign_keys(t),
            }
            for t in model_inspect.get_table_names()
            if t != "alembic_version"
        }

        yield migrated_snapshot, model_snapshot
    finally:
        parity_engine.dispose()
        try:
            teardown = _pm.connect(host=host, port=int(port), user=user, password=pwd)
            try:
                with teardown.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{parity_db}`")
                teardown.commit()
            finally:
                teardown.close()
        except Exception:
            pass


def test_models_declare_the_same_tables_as_the_migration(schema_pair):
    migrated, models = schema_pair
    assert set(models) == set(migrated), (
        f"table set drift: only-migrated={set(migrated) - set(models)}, "
        f"only-model={set(models) - set(migrated)}"
    )


def test_models_declare_the_same_columns_as_the_migration(schema_pair):
    """Compare columns ignoring dialect-specific noise (CHARSET / COLLATE).

    The migration specifies ``mysql_charset="utf8mb4"`` which adds an explicit
    ``COLLATE`` clause at the column level; the ORM doesn't, so the inspector
    reports the same VARCHAR differently. We compare the normalised type
    (length, kind) and the nullable flag instead of the raw string.
    """
    import re

    def norm_type(type_str: str) -> str:
        s = str(type_str)
        # Strip dialect-specific clauses that the ORM doesn't emit.
        s = re.sub(r'\s+COLLATE\s+"?[^"\s]+"?', "", s)
        s = re.sub(r'\s+CHARACTER\s+SET\s+\w+', "", s)
        return s.strip()

    migrated, models = schema_pair
    for table in sorted(migrated):
        mig_cols = migrated[table]["columns"]
        mod_cols = models[table]["columns"]
        assert set(mod_cols) == set(mig_cols), f"column drift in {table}"
        for name, mig in mig_cols.items():
            mod = mod_cols[name]
            assert norm_type(str(mod["type"])) == norm_type(str(mig["type"])), (
                f"{table}.{name} type: {mod['type']!r} vs {mig['type']!r}"
            )
            assert mod["nullable"] == mig["nullable"], f"{table}.{name} nullable"


def test_models_declare_the_same_indexes_and_unique_constraints(schema_pair):
    migrated, models = schema_pair
    for table in sorted(migrated):
        assert {i["name"] for i in models[table]["indexes"]} == {
            i["name"] for i in migrated[table]["indexes"]
        }, f"index drift in {table}"
        assert {
            tuple(u["column_names"]) for u in models[table]["uniques"]
        } == {
            tuple(u["column_names"]) for u in migrated[table]["uniques"]
        }, f"unique constraint drift in {table}"


def test_models_declare_the_same_foreign_keys_as_the_migration(schema_pair):
    migrated, models = schema_pair
    for table in sorted(migrated):
        def norm(fks):
            return {
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                )
                for fk in fks
            }

        assert norm(models[table]["fks"]) == norm(migrated[table]["fks"]), (
            f"foreign key drift in {table}"
        )


def test_v1_schedule_tables_are_absent_from_the_models():
    # v2: schedule config is embedded in geo_projects (plan appendix A.1).
    assert "geo_schedules" not in Base.metadata.tables
    assert "geo_schedule_slots" not in Base.metadata.tables


# --------------------------------------------------------------------------
# 2. Enums
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "enum_cls, expected",
    [
        (CustomerStatus, {"active", "disabled"}),
        (AdminRole, {"super_admin", "customer_admin"}),
        (AdminStatus, {"active", "disabled"}),
        (ProjectStatus, {"active", "disabled"}),
        (RunTrigger, {"cron", "manual"}),
        (RunStatus, {"queued", "running", "success", "failed", "skipped"}),
        (CompetitorSource, {"answer_content", "reference_list"}),
        (CallbackProcessStatus, {"processed", "duplicate", "failed"}),
        (PromptStatus, {"monitoring", "paused", "archived"}),
        (CompetitorOrigin, {"manual", "auto_discovered"}),
        (CompetitorStatus, {"confirmed", "pending", "dismissed"}),
        (ExtractStatus, {"pending", "success", "failed", "skipped"}),
    ],
)
def test_enum_values_match_the_migration(enum_cls, expected):
    assert {m.value for m in enum_cls} == expected


def test_enums_compare_equal_to_their_string_value():
    # deps.py and the API layer compare against plain strings.
    assert AdminRole.SUPER_ADMIN == "super_admin"


def test_enum_columns_persist_the_value_not_the_member_name(db_session: Session):
    db_session.add(Customer(name="c", code="c1"))
    db_session.commit()
    stored = db_session.execute(
        Customer.__table__.select().with_only_columns(Customer.__table__.c.status)
    ).scalar_one()
    assert stored == "active"


# --------------------------------------------------------------------------
# 3. Defaults and timestamps
# --------------------------------------------------------------------------


def test_now_local_is_shanghai_wall_time_without_tzinfo():
    # Columns are naive DATETIME; the container/MySQL session run Asia/Shanghai.
    value = now_local()
    assert value.tzinfo is None
    reference = datetime.now(SHANGHAI).replace(tzinfo=None)
    assert abs((reference - value).total_seconds()) < 5


def test_customer_gets_status_and_timestamps_by_default(db_session: Session):
    c = Customer(name="客户 A", code="cust-a")
    db_session.add(c)
    db_session.commit()
    assert c.status is CustomerStatus.ACTIVE
    assert isinstance(c.created_at, datetime)
    assert c.updated_at is not None
    assert c.logo_path is None


def test_project_schedule_defaults_to_disabled_with_no_slots(project: Project):
    assert project.schedule_enabled is False
    assert project.slot1_hour is None
    assert project.schedule_slots == []


def test_admin_user_defaults_to_active_super_admin(db_session: Session):
    u = AdminUser(username="root", password_hash="x")
    db_session.add(u)
    db_session.commit()
    assert u.role is AdminRole.SUPER_ADMIN
    assert u.status is AdminStatus.ACTIVE
    assert u.customer_id is None


# --------------------------------------------------------------------------
# 4. Embedded schedule helpers (v2)
# --------------------------------------------------------------------------


def test_schedule_slots_lists_both_configured_slots(db_session: Session, project: Project):
    project.schedule_enabled = True
    project.slot1_hour, project.slot1_minute = 9, 0
    project.slot2_hour, project.slot2_minute = 18, 30
    db_session.commit()
    assert project.schedule_slots == [
        {"hour": 9, "minute": 0},
        {"hour": 18, "minute": 30},
    ]


def test_schedule_slots_omits_the_unset_second_slot(db_session: Session, project: Project):
    project.slot1_hour, project.slot1_minute = 7, 5
    db_session.commit()
    assert project.schedule_slots == [{"hour": 7, "minute": 5}]


def test_set_schedule_slots_writes_and_clears_the_embedded_columns(
    db_session: Session, project: Project
):
    project.set_schedule_slots([{"hour": 1, "minute": 2}, {"hour": 3, "minute": 4}])
    db_session.commit()
    assert (project.slot2_hour, project.slot2_minute) == (3, 4)

    project.set_schedule_slots([{"hour": 5, "minute": 6}])
    db_session.commit()
    assert (project.slot1_hour, project.slot1_minute) == (5, 6)
    assert project.slot2_hour is None and project.slot2_minute is None


def test_set_schedule_slots_rejects_more_than_two_slots(project: Project):
    with pytest.raises(ValueError):
        project.set_schedule_slots(
            [{"hour": 1, "minute": 0}, {"hour": 2, "minute": 0}, {"hour": 3, "minute": 0}]
        )


# --------------------------------------------------------------------------
# 5. Relationships and cascades
# --------------------------------------------------------------------------


def test_customer_projects_relationship_is_bidirectional(
    db_session: Session, customer: Customer, project: Project
):
    db_session.refresh(customer)
    assert [p.id for p in customer.projects] == [project.id]
    assert project.customer.code == "demo"


def test_project_children_load_ordered_by_sort(db_session: Session, project: Project):
    db_session.add_all(
        [
            ProjectPrompt(project_id=project.id, prompt="second", sort=2),
            ProjectPrompt(project_id=project.id, prompt="first", sort=1),
            ProjectKeyword(project_id=project.id, keyword="k2", sort=2),
            ProjectKeyword(project_id=project.id, keyword="k1", sort=1),
            ProjectPlatform(project_id=project.id, platform="kimi", mode="web", sort=2),
            ProjectPlatform(
                project_id=project.id, platform="deepseek", mode="web", sort=1
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(project)
    assert [p.prompt for p in project.prompts] == ["first", "second"]
    assert [k.keyword for k in project.keywords] == ["k1", "k2"]
    assert [p.platform for p in project.platforms] == ["deepseek", "kimi"]


def test_deleting_a_project_leaves_its_configuration_rows_intact(
    db_session: Session, project: Project
):
    """Project deletion must not cascade to its prompts/keywords/platforms;
    the FK was removed and the ORM cascade was dropped, so child rows
    survive the parent delete (see CLAUDE.md "外键约定")."""
    db_session.add(ProjectPrompt(project_id=project.id, prompt="p"))
    db_session.commit()
    db_session.refresh(project)

    db_session.delete(project)
    db_session.commit()
    assert db_session.query(ProjectPrompt).count() == 1


def test_schedule_run_links_back_to_its_project(db_session: Session, project: Project):
    run = ScheduleRun(
        project_id=project.id,
        slot_index=1,
        trigger_type=RunTrigger.CRON,
        triggered_at=now_local(),
        cooldown_key="project-1-slot-1-202608070",
    )
    db_session.add(run)
    db_session.commit()
    assert run.status is RunStatus.QUEUED
    assert run.project.id == project.id
    db_session.refresh(project)
    assert [r.id for r in project.runs] == [run.id]


def test_task_subtask_relationship_does_not_cascade(db_session: Session):
    """Subtasks are write-once logs: deleting the parent Task row must NOT
    delete its Subtask rows. The SQL FK was removed for this reason."""
    task = Task(task_id="a" * 32, status="processing")
    db_session.add(task)
    db_session.commit()
    db_session.add(Subtask(subtask_id="b" * 32, task_id=task.task_id, platform="kimi"))
    db_session.commit()
    db_session.refresh(task)
    assert len(task.subtasks) == 1

    db_session.delete(task)
    db_session.commit()
    assert db_session.query(Subtask).count() == 1


def test_task_carries_the_v2_tenancy_columns_but_no_schedule_id(
    db_session: Session, project: Project
):
    run = ScheduleRun(
        project_id=project.id,
        slot_index=0,
        trigger_type=RunTrigger.MANUAL,
        triggered_at=now_local(),
    )
    db_session.add(run)
    db_session.commit()

    task = Task(
        task_id="c" * 32,
        status="pending",
        customer_id=project.customer_id,
        project_id=project.id,
        schedule_run_id=run.id,
    )
    db_session.add(task)
    db_session.commit()
    assert task.schedule_run_id == run.id
    assert not hasattr(Task, "schedule_id")


def test_task_remote_epoch_columns_are_mapped_to_explicit_attribute_names(
    db_session: Session,
):
    task = Task(task_id="d" * 32, status="completed", remote_created_at=1754500000000)
    db_session.add(task)
    db_session.commit()
    assert task.remote_created_at == 1754500000000
    assert isinstance(task.created_local_at, datetime)
    assert "created_at" in Task.__table__.c


def test_competitor_survives_subtask_deletion_independently(db_session: Session):
    """Competitor.task_id / subtask_id are plain columns (no FK), so deleting
    a Subtask row leaves the Competitor row untouched with its stored
    subTaskId intact."""
    task = Task(task_id="e" * 32, status="completed")
    db_session.add(task)
    db_session.commit()
    sub = Subtask(subtask_id="f" * 32, task_id=task.task_id)
    db_session.add(sub)
    db_session.commit()

    comp = Competitor(
        task_id=task.task_id,
        subtask_id=sub.subtask_id,
        name="竞品 A",
        source=CompetitorSource.ANSWER_CONTENT,
    )
    db_session.add(comp)
    db_session.commit()

    db_session.delete(sub)
    db_session.commit()
    db_session.refresh(comp)
    assert comp.subtask_id == "f" * 32


def test_answer_content_is_stored_verbatim(db_session: Session):
    # CLAUDE.md: the backend never sanitises answerContent.
    raw = "# 标题\n\n<b>bold</b> & 表情 🎉"
    task = Task(task_id="g" * 32, status="completed")
    db_session.add(task)
    db_session.commit()
    db_session.add(Subtask(subtask_id="h" * 32, task_id=task.task_id, answer_content=raw))
    db_session.commit()
    assert db_session.query(Subtask).one().answer_content == raw


def test_json_columns_round_trip(db_session: Session):
    task = Task(
        task_id="i" * 32,
        status="pending",
        prompts_json=["问题1", "问题2"],
        raw_request_json={"platformList": [{"platform": "kimi"}]},
    )
    db_session.add(task)
    db_session.commit()
    db_session.expire_all()
    loaded = db_session.get(Task, task.task_id)
    assert loaded.prompts_json == ["问题1", "问题2"]
    assert loaded.raw_request_json["platformList"][0]["platform"] == "kimi"


def test_callback_and_compensation_events_persist(db_session: Session):
    db_session.add(
        CallbackEvent(
            task_id="j" * 32,
            payload_json={"taskId": "j" * 32},
            payload_hash="0" * 64,
            process_status=CallbackProcessStatus.PROCESSED,
        )
    )
    db_session.add(
        CompensationEvent(task_id="j" * 32, source="background-sync:result", action="result")
    )
    db_session.commit()
    assert db_session.query(CallbackEvent).one().process_status is (
        CallbackProcessStatus.PROCESSED
    )
    assert db_session.query(CompensationEvent).one().started_at is not None


# --------------------------------------------------------------------------
# 6. repr
# --------------------------------------------------------------------------


def test_every_model_defines_a_useful_repr(db_session: Session, project: Project):
    run = ScheduleRun(
        project_id=project.id,
        slot_index=1,
        trigger_type=RunTrigger.CRON,
        triggered_at=now_local(),
    )
    db_session.add(run)
    db_session.commit()

    for obj in (project, project.customer, run):
        text = repr(obj)
        assert text.startswith(f"<{type(obj).__name__} ")
        assert "object at 0x" not in text