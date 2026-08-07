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
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
        UniqueConstraint("task_id", name="uq_tasks_task_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_customer_created", "customer_id", "created_local_at"),
        Index("ix_tasks_project_created", "project_id", "created_local_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Remote taskId (32-char hex), see docs/api/submit-task.md.
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
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
    customer_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("geo_customers.id", name="fk_tasks_customer"),
        nullable=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("geo_projects.id", name="fk_tasks_project"),
        nullable=True,
    )
    schedule_run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("geo_schedule_runs.id", name="fk_tasks_schedule_run"),
        nullable=True,
    )

    subtasks: Mapped[list["Subtask"]] = relationship(
        "Subtask",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Subtask.id",
    )
    competitors: Mapped[list["Competitor"]] = relationship(
        "Competitor", back_populates="task", cascade="all, delete-orphan"
    )
    customer: Mapped["Customer | None"] = relationship("Customer")
    project: Mapped["Project | None"] = relationship("Project", back_populates="tasks")
    schedule_run: Mapped["ScheduleRun | None"] = relationship(
        "ScheduleRun", back_populates="tasks"
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} task_id={self.task_id!r} status={self.status!r}>"


class Subtask(Base):
    __tablename__ = "geo_subtasks"
    __table_args__ = (
        UniqueConstraint("subtask_id", name="uq_subtasks_subtask_id"),
        Index("ix_subtasks_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subtask_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_tasks.id", name="fk_subtasks_task", ondelete="CASCADE"),
        nullable=False,
    )
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

    task: Mapped["Task"] = relationship("Task", back_populates="subtasks")
    competitors: Mapped[list["Competitor"]] = relationship(
        "Competitor", back_populates="subtask"
    )

    def __repr__(self) -> str:
        return (
            f"<Subtask id={self.id} subtask_id={self.subtask_id!r} "
            f"task_id={self.task_id} status={self.status!r}>"
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
