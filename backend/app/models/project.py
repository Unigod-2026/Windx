"""Project configuration ORM models.

A project belongs to one customer and carries the full set of inputs that
``MolizhishuClient.submit_task`` consumes: prompts, keywords, platforms. In
v2 the per-day schedule (0, 1 or 2 slots) is embedded directly on the project
row instead of living in separate ``geo_schedules`` / ``geo_schedule_slots``
tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.common import created_at_column, updated_at_column
from app.models.enums import CompetitorSource, DeliveryMode, ProjectStatus, RegionStrategy

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.schedule import ScheduleRun
    from app.models.task import Subtask, Task


class Project(Base):
    __tablename__ = "geo_projects"
    __table_args__ = (
        UniqueConstraint("customer_id", "code", name="uq_project_customer_code"),
        Index("ix_projects_customer_id", "customer_id"),
        Index("ix_projects_schedule_enabled", "schedule_enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_customers.id", name="fk_projects_customer"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ProjectStatus.ACTIVE,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Embedded schedule (v2): 1:1 with the project, 1-2 daily slots.
    schedule_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    slot1_hour: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    slot1_minute: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    slot2_hour: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    slot2_minute: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Monitoring extensions (需求文档 §3 / §4): sentiment + region strategy.
    sentiment_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    region_strategy: Mapped[RegionStrategy] = mapped_column(
        Enum(
            RegionStrategy,
            name="region_strategy",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=RegionStrategy.FIXED,
    )
    region_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    customer: Mapped["Customer"] = relationship("Customer", back_populates="projects")
    prompts: Mapped[list["ProjectPrompt"]] = relationship(
        "ProjectPrompt",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectPrompt.sort",
    )
    keywords: Mapped[list["ProjectKeyword"]] = relationship(
        "ProjectKeyword",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectKeyword.sort",
    )
    platforms: Mapped[list["ProjectPlatform"]] = relationship(
        "ProjectPlatform",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectPlatform.sort",
    )
    project_competitors: Mapped[list["ProjectCompetitor"]] = relationship(
        "ProjectCompetitor",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectCompetitor.sort",
    )
    runs: Mapped[list["ScheduleRun"]] = relationship(
        "ScheduleRun", back_populates="project"
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="project")

    # ------------------------------------------------------------------
    # Embedded-slot helpers
    # ------------------------------------------------------------------

    @property
    def schedule_slots(self) -> list[dict]:
        """Configured slots (0, 1 or 2) as ``[{"hour": ..., "minute": ...}, ...]``."""
        slots: list[dict] = []
        if self.slot1_hour is not None and self.slot1_minute is not None:
            slots.append({"hour": self.slot1_hour, "minute": self.slot1_minute})
        if self.slot2_hour is not None and self.slot2_minute is not None:
            slots.append({"hour": self.slot2_hour, "minute": self.slot2_minute})
        return slots

    def set_schedule_slots(self, slots: list[dict]) -> None:
        """Write up to 2 slots into the embedded columns.

        Raises ``ValueError`` if more than 2 slots are supplied; this matches
        the v2 spec (1-2 daily slots per project).
        """
        if len(slots) > 2:
            raise ValueError("a project may have at most 2 schedule slots")
        slot1 = slots[0] if len(slots) >= 1 else None
        slot2 = slots[1] if len(slots) >= 2 else None
        if slot1 is None:
            self.slot1_hour = None
            self.slot1_minute = None
        else:
            self.slot1_hour = int(slot1["hour"])
            self.slot1_minute = int(slot1["minute"])
        if slot2 is None:
            self.slot2_hour = None
            self.slot2_minute = None
        else:
            self.slot2_hour = int(slot2["hour"])
            self.slot2_minute = int(slot2["minute"])

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id} code={self.code!r} "
            f"customer_id={self.customer_id} status={self.status!r}>"
        )


class ProjectPrompt(Base):
    __tablename__ = "geo_project_prompts"
    __table_args__ = (Index("ix_project_prompts_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_projects.id", name="fk_project_prompts_project", ondelete="CASCADE"),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()

    project: Mapped["Project"] = relationship("Project", back_populates="prompts")

    def __repr__(self) -> str:
        return f"<ProjectPrompt id={self.id} project_id={self.project_id} sort={self.sort}>"


class ProjectKeyword(Base):
    __tablename__ = "geo_project_keywords"
    __table_args__ = (Index("ix_project_keywords_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_projects.id", name="fk_project_keywords_project", ondelete="CASCADE"),
        nullable=False,
    )
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()

    project: Mapped["Project"] = relationship("Project", back_populates="keywords")

    def __repr__(self) -> str:
        return f"<ProjectKeyword id={self.id} project_id={self.project_id} sort={self.sort}>"


class ProjectPlatform(Base):
    __tablename__ = "geo_project_platforms"
    __table_args__ = (Index("ix_project_platforms_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_projects.id", name="fk_project_platforms_project", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    # Legacy single-axis mode (kept for backwards compatibility with rows
    # written before the multi-dimensional split).
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    # New multi-dimensional fields (需求文档 §3):
    #   delivery_mode: web / mobile — which surface to ask from
    #   thinking_mode: enable reasoning/thinking mode on the remote
    delivery_mode: Mapped[DeliveryMode] = mapped_column(
        Enum(
            DeliveryMode,
            name="delivery_mode",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=DeliveryMode.WEB,
    )
    thinking_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    screenshot: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped["Project"] = relationship("Project", back_populates="platforms")

    def __repr__(self) -> str:
        return (
            f"<ProjectPlatform id={self.id} platform={self.platform!r} "
            f"delivery={self.delivery_mode.value!r} sort={self.sort}>"
        )


class ProjectCompetitor(Base):
    """User-defined competitor seed list for a monitoring project.

    Distinct from the existing ``geo_competitors`` table (Task 9 ingestion):
    those rows are *auto-extracted* competitor mentions recorded against
    individual ``geo_tasks``. This table is the project's curated watchlist
    that the user enters in the UI and that the answer-comparison pipeline
    will eventually be scored against.
    """

    __tablename__ = "geo_project_competitors"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_competitors_project_name"),
        Index("ix_project_competitors_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_projects.id", name="fk_project_competitors_project", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    project: Mapped["Project"] = relationship("Project", back_populates="project_competitors")

    def __repr__(self) -> str:
        return f"<ProjectCompetitor id={self.id} project_id={self.project_id} name={self.name!r}>"


class Competitor(Base):
    __tablename__ = "geo_competitors"
    __table_args__ = (Index("ix_competitors_task_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("geo_tasks.id", name="fk_competitors_task", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL on subtask delete: a competitor may outlive the individual subtask
    # that produced the brand mention (the task it belongs to is sufficient context).
    subtask_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("geo_subtasks.id", name="fk_competitors_subtask", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[CompetitorSource] = mapped_column(
        Enum(
            CompetitorSource,
            name="competitor_source",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    task: Mapped["Task"] = relationship("Task", back_populates="competitors")
    subtask: Mapped["Subtask | None"] = relationship("Subtask", back_populates="competitors")

    def __repr__(self) -> str:
        return (
            f"<Competitor id={self.id} name={self.name!r} "
            f"source={self.source!r} task_id={self.task_id}>"
        )
