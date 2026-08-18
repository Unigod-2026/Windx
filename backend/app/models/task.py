"""Task / Subtask / Callback / Compensation ORM models.

These mirror the existing 模力指数 ingestion tables. Two important v2
additions:

- ``Task`` carries optional ``customer_id`` / ``project_id`` /
  ``schedule_run_id`` columns so ad-hoc (non-scheduled) tasks can still be
  created with ``NULL`` on all of them.
- The remote millisecond epochs are stored on ``BigInteger`` columns
  ``created_at`` / ``completed_at``; the local wall-clock columns are
  ``created_local_at`` / ``updated_at``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import foreign

from app.db import Base
from app.models.common import created_at_column, now_local, updated_at_column
from app.models.enums import CallbackProcessStatus

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.project import Competitor, Project
    from app.models.schedule import ScheduleRun


class Task(Base):
    __tablename__ = "geo_tasks"
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_customer_created", "customer_id", "created_local_at"),
        Index("ix_tasks_project_created", "project_id", "created_local_at"),
        # Lets ``WHERE project_id=? ORDER BY task_id DESC`` use the index for
        # ordering instead of filesorting; ``task_id`` is a 32-char hex PK
        # whose lexical order matches insertion order, so "newest first" =
        # "task_id DESC".
        Index("ix_tasks_project_task", "project_id", "task_id"),
    )

    # Remote taskId (32-char hex) doubles as the PK — see docs/api/submit-task.md.
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    prompts_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    platforms_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    region_code_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    total_items: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_items: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_items: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poll_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Remote millisecond epochs; ``created_local_at`` is the wall-clock version.
    # The Python attributes are renamed to ``remote_created_at`` /
    # ``remote_completed_at`` so they cannot be confused with the local
    # ``created_local_at`` / ``updated_at`` wall-clock columns.
    remote_created_at: Mapped[int | None] = mapped_column(
        "created_at", BigInteger, nullable=True
    )
    remote_completed_at: Mapped[int | None] = mapped_column(
        "completed_at", BigInteger, nullable=True
    )
    raw_request_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_local_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_local
    )
    updated_at: Mapped[datetime] = updated_at_column()

    # Multi-tenant / schedule linkage (all nullable: ad-hoc tasks have none).
    # Plain columns (no FK) — see CLAUDE.md "外键约定".
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # No cascade, no ``back_populates``: deleting a Task row must not
    # cascade-delete its Subtask / Competitor rows and must not null the
    # remote-id columns on dependent rows. The DB FKs were dropped for
    # exactly this reason; the relationships here are unidirectional
    # collections (navigable ``task.subtasks`` / ``task.competitors``)
    # only.
    subtasks: Mapped[list["Subtask"]] = relationship(
        "Subtask",
        primaryjoin="foreign(Subtask.task_id) == Task.task_id",
        viewonly=True,
        order_by="Subtask.subtask_id",
    )
    competitors: Mapped[list["Competitor"]] = relationship(
        "Competitor",
        primaryjoin="foreign(Competitor.task_id) == Task.task_id",
        viewonly=True,
    )
    customer: Mapped["Customer | None"] = relationship(
        "Customer",
        primaryjoin="foreign(Task.customer_id) == Customer.id",
        passive_deletes=True,
    )
    project: Mapped["Project | None"] = relationship(
        "Project",
        primaryjoin="foreign(Task.project_id) == Project.id",
        passive_deletes=True,
    )
    schedule_run: Mapped["ScheduleRun | None"] = relationship(
        "ScheduleRun",
        primaryjoin="foreign(Task.schedule_run_id) == ScheduleRun.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Task task_id={self.task_id!r} status={self.status!r}>"


class Subtask(Base):
    __tablename__ = "geo_subtasks"
    __table_args__ = (
        Index("ix_subtasks_task_id", "task_id"),
        # Covers the 问题提及分析 lazy-load path:
        #   WHERE prompt = ? ORDER BY updated_at DESC LIMIT N
        # The MySQL prefix-191 on ``prompt`` keeps the key under the 3072-byte
        # InnoDB limit; SQLite ignores ``mysql_length`` and still picks up the
        # same index name from ``Base.metadata.create_all``.
        Index(
            "ix_subtasks_prompt_updated",
            "prompt",
            "updated_at",
            mysql_length={"prompt": 191},
        ),
    )

    # Remote subTaskId (32-char hex) is the PK — see docs/api/submit-task.md.
    subtask_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Plain column, no FK: deletes of the parent Task row do not cascade and
    # the value is the remote taskId rather than a local surrogate.
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_screenshot: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Stored verbatim: the backend never sanitises answerContent.
    answer_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_list_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    citation_list_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reasoning_process_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommended_questions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    media_content_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    proxy_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()

    # Unidirectional navigation back to the parent Task.
    task: Mapped["Task | None"] = relationship(
        "Task",
        primaryjoin="foreign(Subtask.task_id) == Task.task_id",
        passive_deletes=True,
    )
    competitors: Mapped[list["Competitor"]] = relationship(
        "Competitor",
        primaryjoin="foreign(Competitor.subtask_id) == Subtask.subtask_id",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Subtask subtask_id={self.subtask_id!r} "
            f"task_id={self.task_id!r} status={self.status!r}>"
        )


class CallbackEvent(Base):
    __tablename__ = "geo_callback_events"
    __table_args__ = (
        UniqueConstraint("task_id", "payload_hash", name="uq_callback_task_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    process_status: Mapped[CallbackProcessStatus] = mapped_column(
        Enum(
            CallbackProcessStatus,
            name="callback_process_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_local
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CallbackEvent id={self.id} task_id={self.task_id!r} "
            f"status={self.process_status!r}>"
        )


class CompensationEvent(Base):
    __tablename__ = "geo_compensation_events"
    __table_args__ = (Index("ix_compensation_task_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    request_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_local
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CompensationEvent id={self.id} task_id={self.task_id!r} "
            f"action={self.action!r}>"
        )
