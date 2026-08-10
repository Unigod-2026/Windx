"""Pydantic schemas for the Project API surface.

The v2 schedule is embedded on the project row, so the schedule schemas
live here too rather than in a ``schedule`` module. Slots are exchanged as
a list (``[{"hour": 9, "minute": 0}, ...]``, at most 2) and mapped onto the
``slot1_*`` / ``slot2_*`` columns by ``Project.set_schedule_slots``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    DeliveryMode,
    ProjectStatus,
    RegionStrategy,
    RunStatus,
    RunTrigger,
)


class SlotIn(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(..., ge=0, le=59)


class SlotOut(BaseModel):
    # 1-based to match the ``slot1_*`` / ``slot2_*`` columns; 0 is reserved
    # for manual triggers on ScheduleRun.
    slot_index: int
    hour: int
    minute: int


class PlatformIn(BaseModel):
    """One AI platform + the multi-dimensional config from the 需求 doc §3.

    ``mode`` is kept for backwards compatibility but is no longer the
    source of truth; new code reads ``delivery_mode`` + ``thinking_mode``.
    """

    platform: str = Field(..., min_length=1, max_length=32)
    mode: str = Field(default="web", min_length=1, max_length=32)
    delivery_mode: DeliveryMode = DeliveryMode.WEB
    thinking_mode: bool = False
    screenshot: int = Field(default=0, ge=0, le=1)


class PlatformOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    mode: str
    delivery_mode: DeliveryMode
    thinking_mode: bool
    screenshot: int


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    schedule_enabled: bool = False
    slots: list[SlotIn] = Field(default_factory=list, max_length=2)
    sentiment_enabled: bool = False
    region_strategy: RegionStrategy = RegionStrategy.FIXED
    region_codes: list[str] | None = None


class ProjectUpdate(BaseModel):
    """``code`` is immutable — it is part of the per-customer unique key."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    status: ProjectStatus | None = None
    sentiment_enabled: bool | None = None
    region_strategy: RegionStrategy | None = None
    region_codes: list[str] | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    name: str
    code: str
    status: ProjectStatus
    description: str | None
    schedule_enabled: bool
    slots: list[SlotOut] = Field(default_factory=list)
    next_run_at: datetime | None = None
    sentiment_enabled: bool
    region_strategy: RegionStrategy
    region_codes: list[str] | None
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    prompts: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    platforms: list[PlatformOut] = Field(default_factory=list)


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    size: int


class PromptsUpdate(BaseModel):
    prompts: list[str]


class KeywordsUpdate(BaseModel):
    keywords: list[str]


class PlatformsUpdate(BaseModel):
    platforms: list[PlatformIn]


# --------------------------------------------------------------------------
# Schedule (embedded on the project)
# --------------------------------------------------------------------------


class ScheduleUpdate(BaseModel):
    schedule_enabled: bool
    slots: list[SlotIn] = Field(default_factory=list, max_length=2)


class ScheduleStatusUpdate(BaseModel):
    status: Literal["enabled", "disabled"]


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: RunStatus
    triggered_at: datetime
    finished_at: datetime | None


class ScheduleOut(BaseModel):
    project_id: int
    schedule_enabled: bool
    slots: list[SlotOut]
    next_run_at: datetime | None
    last_run: RunSummary | None


class TriggerOut(BaseModel):
    run_id: int
    # ``queued`` for a fresh run, ``skipped`` when the cooldown window
    # already holds a run for this project/slot.
    status: Literal["queued", "skipped"]


class ScheduleRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    slot_index: int
    trigger_type: RunTrigger
    status: RunStatus
    triggered_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    task_id: int | None
    error_message: str | None


class ScheduleRunListOut(BaseModel):
    items: list[ScheduleRunOut]
    total: int
    page: int
    size: int


class ProjectTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    status: str
    total_items: int | None
    completed_items: int | None
    failed_items: int | None
    project_id: int | None
    schedule_run_id: int | None
    created_local_at: datetime | None


class ProjectTaskListOut(BaseModel):
    items: list[ProjectTaskOut]
    total: int
    page: int
    size: int


# --------------------------------------------------------------------------
# Competitors (user-defined seed list per project)
# --------------------------------------------------------------------------


class CompetitorIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=255)


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    note: str | None
    sort: int
    created_at: datetime
    updated_at: datetime


class CompetitorListOut(BaseModel):
    items: list[CompetitorOut]
    total: int
