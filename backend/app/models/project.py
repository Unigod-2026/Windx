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
    Float,
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
from app.models.common import created_at_column, updated_at_column
from app.models.enums import (
    CompetitorOrigin,
    CompetitorSource,
    CompetitorStatus,
    DeliveryMode,
    ExtractStatus,
    ProjectStatus,
    PromptStatus,
    RegionStrategy,
)

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
    # Plain column (no FK) — see CLAUDE.md "外键约定". Deleting a Customer
    # row leaves Projects intact; the API layer enforces tenancy.
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
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
    # Monitor brand — exactly one per project. Was previously stuffed
    # into ``geo_project_keywords`` at ``sort=0`` by convention; split
    # out into its own column so the edit UI can no longer silently
    # desync the brand from the keyword list. Nullable so existing
    # rows that never set a brand stay valid (``brand=NULL`` is
    # distinct from ``brand=""``).
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Free-form aliases / short-forms of the monitor brand. Persisted as a
    # nullable JSON list so the API can return ``null`` (never populated)
    # distinct from ``[]`` (explicitly empty).
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Project-scoped taxonomy for prompt categories. Order in this list is
    # the order shown on 问题提及分析's subtabs and the order prompts can
    # pick from in 问题管理. ``NULL`` means "no taxonomy configured yet"
    # — the UI falls back to deriving categories from existing prompt
    # rows so the page still renders meaningfully for legacy projects.
    category_taxonomy: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    customer: Mapped["Customer | None"] = relationship(
        "Customer",
        primaryjoin="foreign(Project.customer_id) == Customer.id",
        passive_deletes=True,
    )
    # Parent collection sides: ``viewonly=True`` so deleting a Project row
    # does NOT cascade-NULL the children's project_id / schedule_run_id /
    # etc. — see CLAUDE.md "外键约定". Use ``session.add(Child(...))`` or
    # the dependent-side ``child.parent = parent`` to create children.
    prompts: Mapped[list["ProjectPrompt"]] = relationship(
        "ProjectPrompt",
        primaryjoin="foreign(ProjectPrompt.project_id) == Project.id",
        viewonly=True,
        order_by="ProjectPrompt.sort",
    )
    keywords: Mapped[list["ProjectKeyword"]] = relationship(
        "ProjectKeyword",
        primaryjoin="foreign(ProjectKeyword.project_id) == Project.id",
        viewonly=True,
        order_by="ProjectKeyword.sort",
    )
    platforms: Mapped[list["ProjectPlatform"]] = relationship(
        "ProjectPlatform",
        primaryjoin="foreign(ProjectPlatform.project_id) == Project.id",
        viewonly=True,
        order_by="ProjectPlatform.sort",
    )
    project_competitors: Mapped[list["ProjectCompetitor"]] = relationship(
        "ProjectCompetitor",
        primaryjoin="foreign(ProjectCompetitor.project_id) == Project.id",
        viewonly=True,
        order_by="ProjectCompetitor.sort",
    )
    runs: Mapped[list["ScheduleRun"]] = relationship(
        "ScheduleRun",
        primaryjoin="foreign(ScheduleRun.project_id) == Project.id",
        viewonly=True,
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        primaryjoin="foreign(Task.project_id) == Project.id",
        viewonly=True,
    )

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
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Free-form category (引流感 / 场景类 / ...). Not an Enum because the
    # values are user-extensible in 问题管理 → 标签管理; storing as plain
    # VARCHAR lets the UI add a new tag without a migration.
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[PromptStatus] = mapped_column(
        Enum(
            PromptStatus,
            name="prompt_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=PromptStatus.MONITORING,
    )
    created_at: Mapped[datetime] = created_at_column()

    project: Mapped["Project | None"] = relationship(
        "Project",
        primaryjoin="foreign(ProjectPrompt.project_id) == Project.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectPrompt id={self.id} project_id={self.project_id} "
            f"category={self.category!r} status={self.status!r}>"
        )


class ProjectKeyword(Base):
    __tablename__ = "geo_project_keywords"
    __table_args__ = (Index("ix_project_keywords_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()

    project: Mapped["Project | None"] = relationship(
        "Project",
        primaryjoin="foreign(ProjectKeyword.project_id) == Project.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<ProjectKeyword id={self.id} project_id={self.project_id} sort={self.sort}>"


class ProjectPlatform(Base):
    __tablename__ = "geo_project_platforms"
    __table_args__ = (Index("ix_project_platforms_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
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

    project: Mapped["Project | None"] = relationship(
        "Project",
        primaryjoin="foreign(ProjectPlatform.project_id) == Project.id",
        passive_deletes=True,
    )

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

    ``origin`` + ``status`` together describe the row's lifecycle:

    - ``origin='manual', status='confirmed'`` — user-entered, actively watched.
    - ``origin='auto_discovered', status='pending'`` — surfaced by the
      extraction pass; shown in "Agent 自动发现" until the user confirms.
    - ``origin='auto_discovered', status='dismissed'`` — explicitly
      rejected; the extraction pass keeps ignoring it.
    """

    __tablename__ = "geo_project_competitors"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_competitors_project_name"),
        Index("ix_project_competitors_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Free-form aliases / short-forms of the competitor brand; nullable
    # so the field can be absent for legacy rows.
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    origin: Mapped[CompetitorOrigin] = mapped_column(
        Enum(
            CompetitorOrigin,
            name="competitor_origin",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=CompetitorOrigin.MANUAL,
    )
    status: Mapped[CompetitorStatus] = mapped_column(
        Enum(
            CompetitorStatus,
            name="competitor_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=CompetitorStatus.CONFIRMED,
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    project: Mapped["Project | None"] = relationship(
        "Project",
        primaryjoin="foreign(ProjectCompetitor.project_id) == Project.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectCompetitor id={self.id} project_id={self.project_id} "
            f"name={self.name!r} origin={self.origin!r} status={self.status!r}>"
        )


class BrandMention(Base):
    """One row per (subtask, brand_canonical) the answer mentions.

    Produced by ``app.services.extraction.extract_brand_mentions`` after
    a ``Subtask`` row is upserted. Drives every analysis KPI:

    - ``mention_count`` is binary (0/1) from the API pass; cheap, always
      present after the row is upserted.
    - ``rank_position`` / ``sentiment_score`` / ``is_recommended`` /
      ``concern_hits_json`` are filled by the extraction pipeline from
      ``Subtask.raw_result_json`` (the Molizhishu ``/task/result``
      payload); they may be NULL when the answer body is missing —
      ``extract_status`` tells the UI whether the gap is "still
      pending", "skipped because the brand wasn't mentioned", or
      "gave up".

    ``brand_canonical`` distinguishes *which* brand is being mentioned
    so the same answer talking about both the self brand ("雅培") and a
    competitor ("珂润") lands as two rows. The literal needle the regex
    matched (alias vs canonical) was historically tracked in a
    ``brand_name`` column, but it was redundant with
    ``geo_projects.aliases`` / ``geo_project_competitors.aliases`` and
    got dropped in 20260815_0002 — the canonical+alias lists on the
    parent tables are authoritative.

    ``is_self`` is denormalised off ``brand_canonical`` for the common
    query path ("KPI for the monitored brand only") so the dashboard
    doesn't have to JOIN against ``Project``/``ProjectCompetitor`` for
    every read.
    """

    __tablename__ = "geo_brand_mentions"
    __table_args__ = (
        UniqueConstraint(
            "subtask_id",
            "brand_canonical",
            name="uq_brand_mention_subtask_brand",
        ),
        # Project-wide queries that don't filter on ``is_self`` (admin
        # tooling, exports) — kept for backwards compatibility.
        Index("ix_brand_mentions_project_created", "project_id", "created_at"),
        # Covers Overview / summary window queries — ``is_self`` is the
        # dominant filter (≈ 1/6 of rows for a 6-platform project), so it
        # leads the key after project_id to let the range scan stay tight.
        Index(
            "ix_brand_mentions_proj_self_created",
            "project_id",
            "is_self",
            "created_at",
        ),
        # Covers the brand-mention list endpoint with an ``is_self`` filter
        # (default for the overview list). ``id`` is appended so the same
        # key also satisfies ``ORDER BY id DESC LIMIT N`` without a sort.
        Index("ix_brand_mentions_proj_self_id", "project_id", "is_self", "id"),
        # Covers the brand-mention list endpoint filtered by a single
        # ``brand_canonical`` (competitor-analysis tab).
        Index(
            "ix_brand_mentions_proj_brand_id",
            "project_id",
            "brand_canonical",
            "id",
        ),
        # Covers the 问题提及分析 lazy-load path:
        #   WHERE project_id = ? AND is_self = ? AND prompt = ?
        #   ORDER BY created_at DESC LIMIT N
        # The MySQL prefix-191 on ``prompt`` keeps the key under the 3072-byte
        # InnoDB limit; SQLite ignores ``mysql_length`` and still picks up the
        # same index name from ``Base.metadata.create_all``.
        Index(
            "ix_brand_mentions_proj_self_prompt_created",
            "project_id",
            "is_self",
            "prompt",
            "created_at",
            mysql_length={"prompt": 191},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Remote subTaskId — see CLAUDE.md "外键约定"; do not add a FK here.
    subtask_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    brand_canonical: Mapped[str] = mapped_column(String(255), nullable=False)
    is_self: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 0.0-1.0; Float (not DECIMAL) because we never aggregate over it
    rank_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Discrete label from the Molizhishu /task/result endpoint — one of
    # ``positive`` / ``neutral`` / ``negative``. The aggregation layer
    # translates these to numeric averages for the dashboard's color
    # buckets (>=0.7 green / >=0.5 orange / else red), so the column
    # itself doesn't need a float type.
    sentiment_score: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_recommended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # For the SELF brand row only, the Molizhishu API's ``mentionContext``
    # is wrapped as ``[{"text": mentionContext}]`` so the operator can see
    # the exact snippet where their brand was mentioned. Competitor rows
    # stay NULL (the API doesn't give per-competitor context).
    concern_hits_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extract_status: Mapped[ExtractStatus] = mapped_column(
        Enum(
            ExtractStatus,
            name="extract_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ExtractStatus.PENDING,
    )
    extract_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_extraction: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    def __repr__(self) -> str:
        return (
            f"<BrandMention id={self.id} subtask_id={self.subtask_id!r} "
            f"brand={self.brand_canonical!r} status={self.extract_status!r}>"
        )


class Competitor(Base):
    __tablename__ = "geo_competitors"
    __table_args__ = (Index("ix_competitors_task_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Plain columns: store the remote taskId / subTaskId without a FK, so a
    # competitor row can outlive its source task without cascading away.
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subtask_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

    # Unidirectional navigation back to the source Task / Subtask. The DB
    # FKs are absent, so we use ``viewonly`` to stop the ORM from
    # nulling ``task_id`` / ``subtask_id`` on dependent rows when the
    # referenced Task or Subtask is deleted.
    task: Mapped["Task | None"] = relationship(
        "Task",
        primaryjoin="foreign(Competitor.task_id) == Task.task_id",
        viewonly=True,
    )
    subtask: Mapped["Subtask | None"] = relationship(
        "Subtask",
        primaryjoin="foreign(Competitor.subtask_id) == Subtask.subtask_id",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Competitor id={self.id} name={self.name!r} "
            f"source={self.source!r} task_id={self.task_id}>"
        )
