"""ORM model tests.

Two things are verified here:

1. **Schema parity** — ``Base.metadata`` (the models) must describe exactly the
   same schema as the Alembic migration. Both are materialised into throwaway
   SQLite databases and compared column-by-column. This is the guard against
   model/migration drift, which is otherwise only discovered in production.
2. **Behaviour** — enum values, relationship loading/ordering, cascades,
   timestamp defaults and the embedded-schedule helpers.

No MySQL is involved; ``tests/conftest.py`` already forces SQLite.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.db import Base
from app.models import (
    AdminUser,
    CallbackEvent,
    Competitor,
    CompensationEvent,
    Customer,
    Project,
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
    CompetitorSource,
    CustomerStatus,
    ProjectStatus,
    RunStatus,
    RunTrigger,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def session() -> Session:
    """An in-memory SQLite session with FK enforcement switched on.

    SQLite ignores ``ON DELETE CASCADE`` unless ``PRAGMA foreign_keys`` is
    enabled per connection, so the pragma is installed via a connect hook.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):  # pragma: no cover - trivial hook
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    with factory() as s:
        yield s
    engine.dispose()


@pytest.fixture()
def customer(session: Session) -> Customer:
    c = Customer(name="示例客户", code="demo")
    session.add(c)
    session.commit()
    return c


@pytest.fixture()
def project(session: Session, customer: Customer) -> Project:
    p = Project(customer_id=customer.id, name="示例项目", code="proj-a")
    session.add(p)
    session.commit()
    return p


# --------------------------------------------------------------------------
# 1. Schema parity: models vs. migration
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_pair(tmp_path_factory):
    """Reflect the migration-built schema and the model-built schema."""
    tmp = tmp_path_factory.mktemp("parity")

    migrated_db = tmp / "migrated.db"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{migrated_db}")
    command.upgrade(cfg, "head")

    model_db = tmp / "models.db"
    model_engine = create_engine(f"sqlite+pysqlite:///{model_db}", future=True)
    Base.metadata.create_all(model_engine)

    migrated_engine = create_engine(f"sqlite+pysqlite:///{migrated_db}", future=True)
    try:
        yield inspect(migrated_engine), inspect(model_engine)
    finally:
        migrated_engine.dispose()
        model_engine.dispose()


def test_models_declare_the_same_tables_as_the_migration(schema_pair):
    migrated, models = schema_pair
    migrated_tables = set(migrated.get_table_names()) - {"alembic_version"}
    assert set(models.get_table_names()) == migrated_tables


def test_models_declare_the_same_columns_as_the_migration(schema_pair):
    migrated, models = schema_pair
    for table in sorted(set(migrated.get_table_names()) - {"alembic_version"}):
        mig_cols = {c["name"]: c for c in migrated.get_columns(table)}
        mod_cols = {c["name"]: c for c in models.get_columns(table)}
        assert set(mod_cols) == set(mig_cols), f"column drift in {table}"
        for name, mig in mig_cols.items():
            mod = mod_cols[name]
            assert str(mod["type"]) == str(mig["type"]), f"{table}.{name} type"
            assert mod["nullable"] == mig["nullable"], f"{table}.{name} nullable"


def test_models_declare_the_same_indexes_and_unique_constraints(schema_pair):
    migrated, models = schema_pair
    for table in sorted(set(migrated.get_table_names()) - {"alembic_version"}):
        assert {i["name"] for i in models.get_indexes(table)} == {
            i["name"] for i in migrated.get_indexes(table)
        }, f"index drift in {table}"
        assert {
            tuple(u["column_names"]) for u in models.get_unique_constraints(table)
        } == {
            tuple(u["column_names"]) for u in migrated.get_unique_constraints(table)
        }, f"unique constraint drift in {table}"


def test_models_declare_the_same_foreign_keys_as_the_migration(schema_pair):
    migrated, models = schema_pair
    for table in sorted(set(migrated.get_table_names()) - {"alembic_version"}):
        def norm(fks):
            return {
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                )
                for fk in fks
            }

        assert norm(models.get_foreign_keys(table)) == norm(
            migrated.get_foreign_keys(table)
        ), f"foreign key drift in {table}"


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
    ],
)
def test_enum_values_match_the_migration(enum_cls, expected):
    assert {m.value for m in enum_cls} == expected


def test_enums_compare_equal_to_their_string_value():
    # deps.py and the API layer compare against plain strings.
    assert AdminRole.SUPER_ADMIN == "super_admin"


def test_enum_columns_persist_the_value_not_the_member_name(session: Session):
    session.add(Customer(name="c", code="c1"))
    session.commit()
    stored = session.execute(
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


def test_customer_gets_status_and_timestamps_by_default(session: Session):
    c = Customer(name="客户 A", code="cust-a")
    session.add(c)
    session.commit()
    assert c.status is CustomerStatus.ACTIVE
    assert isinstance(c.created_at, datetime)
    assert c.updated_at is not None
    assert c.logo_path is None


def test_project_schedule_defaults_to_disabled_with_no_slots(project: Project):
    assert project.schedule_enabled is False
    assert project.slot1_hour is None
    assert project.schedule_slots == []


def test_admin_user_defaults_to_active_super_admin(session: Session):
    u = AdminUser(username="root", password_hash="x")
    session.add(u)
    session.commit()
    assert u.role is AdminRole.SUPER_ADMIN
    assert u.status is AdminStatus.ACTIVE
    assert u.customer_id is None


# --------------------------------------------------------------------------
# 4. Embedded schedule helpers (v2)
# --------------------------------------------------------------------------


def test_schedule_slots_lists_both_configured_slots(session: Session, project: Project):
    project.schedule_enabled = True
    project.slot1_hour, project.slot1_minute = 9, 0
    project.slot2_hour, project.slot2_minute = 18, 30
    session.commit()
    assert project.schedule_slots == [
        {"hour": 9, "minute": 0},
        {"hour": 18, "minute": 30},
    ]


def test_schedule_slots_omits_the_unset_second_slot(session: Session, project: Project):
    project.slot1_hour, project.slot1_minute = 7, 5
    session.commit()
    assert project.schedule_slots == [{"hour": 7, "minute": 5}]


def test_set_schedule_slots_writes_and_clears_the_embedded_columns(
    session: Session, project: Project
):
    project.set_schedule_slots([{"hour": 1, "minute": 2}, {"hour": 3, "minute": 4}])
    session.commit()
    assert (project.slot2_hour, project.slot2_minute) == (3, 4)

    project.set_schedule_slots([{"hour": 5, "minute": 6}])
    session.commit()
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
    session: Session, customer: Customer, project: Project
):
    session.refresh(customer)
    assert [p.id for p in customer.projects] == [project.id]
    assert project.customer.code == "demo"


def test_project_children_load_ordered_by_sort(session: Session, project: Project):
    session.add_all(
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
    session.commit()
    session.refresh(project)
    assert [p.prompt for p in project.prompts] == ["first", "second"]
    assert [k.keyword for k in project.keywords] == ["k1", "k2"]
    assert [p.platform for p in project.platforms] == ["deepseek", "kimi"]


def test_deleting_a_project_deletes_its_configuration_rows(
    session: Session, project: Project
):
    session.add(ProjectPrompt(project_id=project.id, prompt="p"))
    session.commit()
    session.refresh(project)

    session.delete(project)
    session.commit()
    assert session.query(ProjectPrompt).count() == 0


def test_schedule_run_links_back_to_its_project(session: Session, project: Project):
    run = ScheduleRun(
        project_id=project.id,
        slot_index=1,
        trigger_type=RunTrigger.CRON,
        triggered_at=now_local(),
        cooldown_key="project-1-slot-1-202608070",
    )
    session.add(run)
    session.commit()
    assert run.status is RunStatus.QUEUED
    assert run.project.id == project.id
    session.refresh(project)
    assert [r.id for r in project.runs] == [run.id]


def test_task_subtask_relationship_and_cascade(session: Session):
    task = Task(task_id="a" * 32, status="processing")
    session.add(task)
    session.commit()
    session.add(Subtask(subtask_id="b" * 32, task_id=task.id, platform="kimi"))
    session.commit()
    session.refresh(task)
    assert len(task.subtasks) == 1

    session.delete(task)
    session.commit()
    assert session.query(Subtask).count() == 0


def test_task_carries_the_v2_tenancy_columns_but_no_schedule_id(
    session: Session, project: Project
):
    run = ScheduleRun(
        project_id=project.id,
        slot_index=0,
        trigger_type=RunTrigger.MANUAL,
        triggered_at=now_local(),
    )
    session.add(run)
    session.commit()

    task = Task(
        task_id="c" * 32,
        status="pending",
        customer_id=project.customer_id,
        project_id=project.id,
        schedule_run_id=run.id,
    )
    session.add(task)
    session.commit()
    assert task.schedule_run_id == run.id
    assert not hasattr(Task, "schedule_id")


def test_task_remote_epoch_columns_are_mapped_to_explicit_attribute_names(
    session: Session,
):
    task = Task(task_id="d" * 32, status="completed", remote_created_at=1754500000000)
    session.add(task)
    session.commit()
    assert task.remote_created_at == 1754500000000
    assert isinstance(task.created_local_at, datetime)
    assert "created_at" in Task.__table__.c


def test_competitor_survives_subtask_deletion_via_set_null(session: Session):
    task = Task(task_id="e" * 32, status="completed")
    session.add(task)
    session.commit()
    sub = Subtask(subtask_id="f" * 32, task_id=task.id)
    session.add(sub)
    session.commit()

    comp = Competitor(
        task_id=task.id,
        subtask_id=sub.id,
        name="竞品 A",
        source=CompetitorSource.ANSWER_CONTENT,
    )
    session.add(comp)
    session.commit()

    session.delete(sub)
    session.commit()
    session.refresh(comp)
    assert comp.subtask_id is None


def test_answer_content_is_stored_verbatim(session: Session):
    # CLAUDE.md: the backend never sanitises answerContent.
    raw = "# 标题\n\n<b>bold</b> & 表情 🎉"
    task = Task(task_id="g" * 32, status="completed")
    session.add(task)
    session.commit()
    session.add(Subtask(subtask_id="h" * 32, task_id=task.id, answer_content=raw))
    session.commit()
    assert session.query(Subtask).one().answer_content == raw


def test_json_columns_round_trip(session: Session):
    task = Task(
        task_id="i" * 32,
        status="pending",
        prompts_json=["问题1", "问题2"],
        raw_request_json={"platformList": [{"platform": "kimi"}]},
    )
    session.add(task)
    session.commit()
    session.expire_all()
    loaded = session.get(Task, task.id)
    assert loaded.prompts_json == ["问题1", "问题2"]
    assert loaded.raw_request_json["platformList"][0]["platform"] == "kimi"


def test_callback_and_compensation_events_persist(session: Session):
    session.add(
        CallbackEvent(
            task_id="j" * 32,
            payload_json={"taskId": "j" * 32},
            payload_hash="0" * 64,
            process_status=CallbackProcessStatus.PROCESSED,
        )
    )
    session.add(
        CompensationEvent(task_id="j" * 32, source="background-sync:result", action="result")
    )
    session.commit()
    assert session.query(CallbackEvent).one().process_status is (
        CallbackProcessStatus.PROCESSED
    )
    assert session.query(CompensationEvent).one().started_at is not None


# --------------------------------------------------------------------------
# 6. repr
# --------------------------------------------------------------------------


def test_every_model_defines_a_useful_repr(session: Session, project: Project):
    run = ScheduleRun(
        project_id=project.id,
        slot_index=1,
        trigger_type=RunTrigger.CRON,
        triggered_at=now_local(),
    )
    session.add(run)
    session.commit()

    for obj in (project, project.customer, run):
        text = repr(obj)
        assert text.startswith(f"<{type(obj).__name__} ")
        assert "object at 0x" not in text
