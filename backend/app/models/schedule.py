"""Per-project schedule execution log.

v2 keeps run history at ``geo_schedule_runs`` (1 row per execution) but the
schedule _configuration_ is embedded on ``geo_projects`` — there is no
``geo_schedules`` or ``geo_schedule_slots`` table.

``slot_index`` is 0 for manual triggers (no slot) and 1 / 2 for cron slots.
The DB-level ``CheckConstraint("slot_index IN (0, 1, 2)")`` is enforced by the
migration; the model relies on the application layer for the same invariant.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import foreign

from app.db import Base
from app.models.enums import RunStatus, RunTrigger

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task


class ScheduleRun(Base):
    __tablename__ = "geo_schedule_runs"
    __table_args__ = (
        UniqueConstraint("cooldown_key", name="uq_schedule_runs_cooldown_key"),
        CheckConstraint("slot_index IN (0, 1, 2)", name="ck_run_slot_index_range"),
        Index(
            "ix_runs_project_slot_triggered",
            "project_id",
            "slot_index",
            "triggered_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Plain column (no FK) — see CLAUDE.md "外键约定".
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1 or 2 for cron slots, 0 for manual triggers.
    slot_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    trigger_type: Mapped[RunTrigger] = mapped_column(
        Enum(
            RunTrigger,
            name="run_trigger",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            name="run_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=RunStatus.QUEUED,
    )
    # Plain column (no FK): breaks the Task<->Run cycle and survives the
    # SQLAlchemy ``after_insert`` ordering for back-references. Stores the
    # remote ``taskId`` (string) rather than a local surrogate.
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ``project-{id}-slot-{idx}-{YYYYMMDDHH}{floor(minute/5)}`` — 5 minute dedupe window.
    cooldown_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped["Project | None"] = relationship(
        "Project",
        primaryjoin="foreign(ScheduleRun.project_id) == Project.id",
        passive_deletes=True,
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        primaryjoin="foreign(Task.schedule_run_id) == ScheduleRun.id",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduleRun id={self.id} project_id={self.project_id} "
            f"slot_index={self.slot_index} status={self.status!r}>"
        )
