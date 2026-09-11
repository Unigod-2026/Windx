"""Pydantic schemas for the Project API surface.

The v4 schedule is embedded on the project row and is **per-mode**:
``monitor_schedule`` is a ``{fast: {freq, days}, think: {freq, days}}``
map so a project can monitor its fast / think platforms on independent
weekly cadences. Time-of-day is not per-project: the scheduler reads it
from the ``MONITOR_DEFAULT_HOUR`` / ``MONITOR_DEFAULT_MINUTE`` env vars.

``MonitorScheduleEntry`` is the inner shape used both on the wizard
(wizard side writes both keys) and on the project row (storage
round-trips through the same shape). An entry whose ``days`` is empty
is treated as "this mode is not scheduled" — ``schedule_enabled`` still
flips on if the other mode is configured.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    CompetitorOrigin,
    CompetitorStatus,
    DeliveryMode,
    ExtractStatus,
    ProjectStatus,
    PromptStatus,
    RegionStrategy,
    RunStatus,
    RunTrigger,
)


MonitorMode = Literal["fast", "think"]
MonitorFreq = Literal["w1", "w2", "wn"]
MonitorDay = Literal["1", "2", "3", "4", "5", "6", "7"]
MonitorDevice = Literal["pc", "mobile"]


class PlatformIn(BaseModel):
    """One AI platform + the multi-dimensional config from the 需求 doc §3.

    ``mode`` is kept for backwards compatibility but is no longer the
    source of truth; new code reads ``delivery_mode`` + ``thinking_mode``.
    """

    platform: str = Field(..., min_length=1, max_length=32)
    mode: str = Field(default="web", min_length=1, max_length=32)
    delivery_mode: DeliveryMode = DeliveryMode.WEB
    thinking_mode: bool = False
    screenshot: int = Field(default=0, ge=0, le=2)


class PlatformOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    # Resolved API platform string (web or mobile) that the scheduler forwards
    # verbatim. Always set — for web rows this equals ``platform`` (e.g.
    # ``doubao``); for mobile rows it's the mapped variant (e.g.
    # ``doubao_mobile`` / ``baidu_mobile``).
    platform_code: str
    mode: str
    delivery_mode: DeliveryMode
    thinking_mode: bool
    screenshot: int


class MonitorScheduleEntry(BaseModel):
    """One mode's weekly plan.

    ``days`` is the source of truth for cadence — ``freq`` is a UI hint
    that follows ``len(days)`` at render time. Empty ``days`` means
    "this mode is not scheduled"; the wizard never submits an entry with
    a freq hint but zero days, but the storage column can hold one if
    a PENDING row gets edited through the schedule API.
    """

    freq: MonitorFreq = "w1"
    days: list[MonitorDay] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    schedule_enabled: bool = False
    monitor_schedule: dict[MonitorMode, MonitorScheduleEntry | None] | None = None
    sentiment_enabled: bool = False
    region_strategy: RegionStrategy = RegionStrategy.FIXED
    region_codes: list[str] | None = None
    brand: str | None = Field(default=None, max_length=255)
    aliases: list[str] | None = None
    category_taxonomy: list[str] | None = None


class ProjectUpdate(BaseModel):
    """``code`` is immutable — it is part of the per-customer unique key."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    status: ProjectStatus | None = None
    sentiment_enabled: bool | None = None
    region_strategy: RegionStrategy | None = None
    region_codes: list[str] | None = None
    brand: str | None = Field(default=None, max_length=255)
    aliases: list[str] | None = None
    category_taxonomy: list[str] | None = None
    # Maps old category names to new ones. Server applies these BEFORE
    # diffing the new taxonomy against the old one so renames preserve
    # prompt.category references instead of cascading to NULL.
    category_renames: dict[str, str] | None = None
    # 「语义监控」卡片的核心卖点 / 官网 / 微信 / 自定义等键值对。
    # 写入 ``geo_projects.semantic_json`` JSON 列。前端 active/disabled
    # modal 直接保存(不再走 wizard draft 通道);Pending 仍走 wizard
    # payload,语义也在里面。
    semantic_json: dict | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    name: str
    code: str
    status: ProjectStatus
    description: str | None
    schedule_enabled: bool
    # Per-mode schedule map. Each value is either a ``MonitorScheduleEntry``
    # or ``None`` (mode not scheduled). Stored verbatim on
    # ``geo_projects.monitor_schedule`` so the wizard / project-edit / list
    # views share one shape.
    monitor_schedule: dict[str, MonitorScheduleEntry] = Field(default_factory=dict)
    # Earliest upcoming fire across BOTH modes — single-value for the
    # project list row's 「下一次执行」 column. Mode-aware "next" lives
    # in the dashboard upcoming list and the schedule detail endpoint.
    next_run_at: datetime | None = None
    sentiment_enabled: bool
    region_strategy: RegionStrategy
    region_codes: list[str] | None
    brand: str | None = None
    aliases: list[str] | None = None
    category_taxonomy: list[str] | None = None
    # Wizard step 6 payload — empty fields are pruned at approval time,
    # so ``None`` and ``{}`` are interchangeable on the read side.
    semantic_json: dict | None = None

    # ===== Review / approval metadata =====
    # All nullable: pre-20260908 rows are ACTIVE / DISABLED without this
    # metadata, and the UI must keep rendering them correctly.
    review_note: str | None = None
    submitted_by: int | None = None
    submitted_at: datetime | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    # The raw wizard submission JSON kept for audit / re-edit; UI uses it
    # to prefill BatchQuestionModal on the 待审核 page. NOT shown on the
    # active project page once status leaves PENDING.
    wizard_payload_json: str | None = None

    @field_validator("monitor_schedule", mode="before")
    @classmethod
    def _coerce_monitor_schedule(cls, v):
        # ``monitor_schedule`` is nullable on the ORM side; projects
        # without a weekly plan round-trip through this endpoint as
        # ``None``. Normalise to ``{}`` so the UI can ``.fast`` / ``.think``
        # without a null guard.
        if v is None:
            return {}
        return v
    # Number of prompts in this project — kept on the list endpoint so the
    # sidebar's 问题提及分析 badge can render the real count without a
    # second round-trip. Detail endpoint returns the same value
    # (``len(prompts)``) for consistency.
    prompts_count: int = 0
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Wizard submission payload
#
# Multi-step 新建项目 wizard writes a single ``WizardPayload`` to the
# project row's ``wizard_payload_json`` column. ``POST /api/projects`` and
# ``PUT /api/projects/{id}/draft`` both validate against this; the API
# materialises prompts / competitors / platforms from it at submit time
# and again at approval time so the project is fully queryable on the
# 待审核 page without a separate "draft" surface.
# --------------------------------------------------------------------------


class WizardQuestion(BaseModel):
    text: str = Field(..., min_length=1)
    category: str = Field(default="引流类", min_length=1, max_length=32)
    tag: str | None = None


class WizardBrand(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    product: str | None = Field(default=None, max_length=255)
    aliases: list[str] = Field(default_factory=list)


class WizardCompetitor(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    product: str | None = Field(default=None, max_length=255)
    aliases: list[str] = Field(default_factory=list)


class WizardMonitor(BaseModel):
    """Wizard's step-5 monitor configuration.

    ``devices`` / ``modes`` control which ``ProjectPlatform`` rows the
    wizard expands on submit (web vs mobile surface × thinking-mode
    flag). ``schedules`` is keyed by ``fast`` / ``think`` and controls
    which mode fires on which weekday at the cron layer; an entry whose
    ``days`` is empty (or a missing key entirely) means "this mode is
    not scheduled".

    The two axes are independent on purpose: a project can pick a
    platform in 思考 mode but only schedule 快速 mode so the slower
    reasoning call doesn't run every day. The submitted wizard payload
    is what gets materialised onto ``Project.monitor_schedule`` at
    approval time.
    """

    devices: list[MonitorDevice] = Field(default_factory=list)
    modes: list[Literal["fast", "think"]] = Field(default_factory=lambda: ["fast"])
    schedules: dict[MonitorMode, MonitorScheduleEntry | None] = Field(
        default_factory=lambda: {"fast": None, "think": None}
    )


class WizardGeo(BaseModel):
    mode: Literal["national_random", "fixed"] = "national_random"
    region_code: str | None = None


class WizardSemantic(BaseModel):
    selling_points: list[str] = Field(default_factory=list)
    website: str | None = None
    phone: str | None = None
    address: str | None = None
    email: str | None = None
    wechat_service: str | None = None
    wechat_official: str | None = None
    xiaohongshu: str | None = None
    douyin: str | None = None
    weibo: str | None = None
    custom: str | None = None


class WizardModelConfig(BaseModel):
    """Per-model-card config from the 待审核 modal.

    ``code`` is a web (``doubao``) or mobile (``doubao_mobile``)
    modelCode picked explicitly on its own card, so each surface gets
    its own 快速 / 思考 / 截图 choice. ``modes`` maps to
    ``ProjectPlatform.thinking_mode`` (one row per mode).
    """

    code: str = Field(..., min_length=1, max_length=32)
    modes: list[Literal["fast", "think"]] = Field(default_factory=lambda: ["fast"])
    screenshot: bool = False


class WizardPayload(BaseModel):
    """Multi-step wizard output; see ``frontend/.../api/pendingProjects.ts``
    for the TypeScript twin. Field set is locked: do NOT add or remove
    fields without coordinating with the frontend.
    """

    questions: list[WizardQuestion] = Field(default_factory=list)
    brand: WizardBrand
    competitors: list[WizardCompetitor] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    # Present only for submissions from the 待审核 modal, where every
    # surface is its own card. When non-empty it REPLACES the
    # ``models × monitor.devices`` cross-product (see
    # ``_expand_wizard_platforms``) — the codes are already explicit.
    models_config: list[WizardModelConfig] = Field(default_factory=list)
    monitor: WizardMonitor = Field(default_factory=WizardMonitor)
    categories: list[str] = Field(default_factory=lambda: ["引流类", "品牌类"])
    geo: WizardGeo = Field(default_factory=WizardGeo)
    sentiment: Literal["on", "off"] = "on"
    semantic: WizardSemantic = Field(default_factory=WizardSemantic)


class WizardSubmissionIn(BaseModel):
    """Body of ``POST /api/projects`` and ``PUT /api/projects/{id}/draft``.

    ``customer_id`` is required for super_admin (must pick the target
    tenant) and IGNORED for customer_admin (always forced to their own
    tenant). The validation lives in the API handler.

    ``preserve_schedule_enabled`` defaults to ``False``: PENDING
    submissions compute ``schedule_enabled`` from ``monitor.days``
    (``bool(days)``). When ``True`` (active/disabled edit through the
    wizard draft endpoint) ``_materialise_wizard_payload`` keeps the
    project's existing ``schedule_enabled`` value — that flag lives on
    the list-page Switch and the modal isn't allowed to flip it as a
    side-effect of editing other wizard fields.
    """

    customer_id: int | None = None
    payload: WizardPayload
    preserve_schedule_enabled: bool = False
    # 项目行字段,跟 wizard payload 平行。PENDING 的 "监控名称" 走这条
    # 路径(``update_project`` 对 PENDING 业务字段拒收,见
    # ``app/api/projects.py`` update_project 的 lifecycle rule);空时
    # 不动 ``project.name``。
    name: str | None = None


class ReviewDecisionIn(BaseModel):
    """Body of ``POST /api/projects/{id}/reject``.

    Super_admin only. ``review_note`` is the only field today; the schema
    is shaped this way so future fields (e.g. re-route to another admin)
    can land without breaking older clients.
    """

    review_note: str = Field(..., min_length=1, max_length=2000)


class ProjectDetailOut(ProjectOut):
    prompts: list[PromptOut] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    platforms: list[PlatformOut] = Field(default_factory=list)


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    size: int


class PromptIn(BaseModel):
    """One prompt in the project. ``category`` is free-form text so the UI
    can add a new tag in 问题管理 → 标签管理 without a code change."""

    prompt: str = Field(..., min_length=1)
    category: str | None = Field(default=None, max_length=32)
    status: PromptStatus = PromptStatus.MONITORING


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt: str
    category: str | None
    status: PromptStatus
    sort: int


class PromptsUpdate(BaseModel):
    prompts: list[PromptIn]


class KeywordsUpdate(BaseModel):
    keywords: list[str]


class PlatformsUpdate(BaseModel):
    platforms: list[PlatformIn]


# --------------------------------------------------------------------------
# Schedule (embedded on the project)
# --------------------------------------------------------------------------


class ScheduleUpdate(BaseModel):
    schedule_enabled: bool
    # Per-mode schedule map. Same shape as ``Project.monitor_schedule``.
    # Optional so callers can flip only the master switch without
    # rewriting the schedule.
    monitor_schedule: dict[MonitorMode, MonitorScheduleEntry | None] | None = None


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
    monitor_schedule: dict[str, MonitorScheduleEntry] = Field(default_factory=dict)
    # Single next-run across both modes — earliest of fast/think. Mode-aware
    # "next" lives in the dashboard upcoming list.
    next_run_at: datetime | None
    last_run: RunSummary | None


class TriggerOut(BaseModel):
    run_id: int
    # 当项目同时存在 fast 和 think 平台行时,手动触发会拆成两个
    # ``ScheduleRun``(``mode=fast`` + ``mode=think``)。``think_run_id`` 是
    # 第二个 run 的 id;单模式项目下为 ``None``。``run_id`` 始终是 fast 那个,
    # 没有 fast 时与 ``think_run_id`` 等价(目前仅出现在 fast + think
    # 都存在的拆分路径里)。
    think_run_id: int | None = None
    # ``queued`` for a fresh run, ``skipped`` when the cooldown window
    # already holds a run for this project/slot. 拆分场景下至少一个
    # ``queued`` 就算 ``queued``,只有两个都因 cooldown 命中才 ``skipped``。
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
    # Remote taskId once the run's Task row is created; null while still queued.
    task_id: str | None
    error_message: str | None
    # ``"fast"`` / ``"think"`` for cron-driven runs, ``""`` for manual
    # triggers. The list endpoint splits runs by mode in the UI; the
    # scheduler uses it to compute mode-aware cooldown keys.
    mode: str = ""
    # Subtask breakdown for multi-model runs. Aggregated from
    # geo_subtasks via Task.schedule_run_id; 0 when the run has not
    # yet produced a Task (queued/manual triggers before submit).
    success_count: int = 0
    failed_count: int = 0
    partial_count: int = 0
    total_count: int = 0


class ScheduleRunListOut(BaseModel):
    items: list[ScheduleRunOut]
    total: int
    page: int
    size: int


class ProjectTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    status: str
    total_items: int | None
    completed_items: int | None
    failed_items: int | None
    project_id: int | None
    schedule_run_id: int | None
    created_local_at: datetime | None
    remote_completed_at: datetime | None


class ProjectTaskListOut(BaseModel):
    items: list[ProjectTaskOut]
    total: int
    page: int
    size: int


class SubtaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subtask_id: str
    task_id: str
    platform: str | None
    mode: str | None
    prompt: str | None
    status: str | None
    error_message: str | None
    page_screenshot: str | None


class SubtaskListOut(BaseModel):
    items: list[SubtaskOut]
    total: int


class PromptAnswerOut(BaseModel):
    """List-row schema for the 问题提及分析 → 查看原文 list modal.

    Each row carries just enough to render the per-answer preview card:
    identity, status, timestamp, error message, and a truncated slice of
    ``answer_content`` plus its full length so the UI can show
    "展开全部 (N 字)". Heavy fields (full text, page screenshot, all
    structured-payload JSON) live behind :class:`PromptAnswerDetailOut`
    and are only fetched when the operator opens 展开全部 — that keeps
    the list response small enough that a 60-row month window stays
    well under 100 KB regardless of how long each answer is.
    """

    model_config = ConfigDict(from_attributes=True)

    subtask_id: str
    task_id: str
    platform: str | None
    mode: str | None
    status: str | None
    error_message: str | None
    created_local_at: datetime | None
    # ``answer_content`` is the verbatim text the AI returned — the
    # backend never sanitises it (Markdown/HTML stored as-is per
    # CLAUDE.md §"数据落库"). The list endpoint slices it down to
    # ``preview_chars`` characters; the detail endpoint returns it whole.
    answer_content: str | None = None
    answer_length: int = 0
    truncated: bool = False


class PromptAnswerDetailOut(PromptAnswerOut):
    """Single-subtask detail, fetched on demand when the operator opens
    "展开全部" on a list-row card.

    Adds the heavy fields the list intentionally omits:
      - ``answer_content`` (full text, not the truncated preview slice)
      - ``page_screenshot`` — base64 PNG; can be tens of KB on its own
      - ``reference_list`` / ``citation_list`` — citation URLs the model
        attached (most platforms return plain URL strings; yuanbao
        returns structured {url, title, site, icon, ...} dicts — both
        shapes are accepted as ``Any``)
      - ``reasoning_process`` — thinking trace; raw JSON because the
        schema is per-platform
      - ``media_content`` — images / videos the AI embedded
      - ``recommended_questions`` — follow-up suggestions; platforms
        differ on whether these are strings or {question: ...} objects
    """

    page_screenshot: str | None = None
    reference_list: list[Any] | None = None
    citation_list: list[Any] | None = None
    reasoning_process: Any | None = None
    media_content: list[Any] | None = None
    recommended_questions: list[Any] | None = None


class PromptAnswerListOut(BaseModel):
    items: list[PromptAnswerOut]
    total: int


# --------------------------------------------------------------------------
# Competitors (user-defined seed list per project)
# --------------------------------------------------------------------------


class CompetitorIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=255)
    aliases: list[str] | None = None
    origin: CompetitorOrigin = CompetitorOrigin.MANUAL
    status: CompetitorStatus = CompetitorStatus.CONFIRMED


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    note: str | None
    aliases: list[str] | None = None
    sort: int
    origin: CompetitorOrigin
    status: CompetitorStatus
    created_at: datetime
    updated_at: datetime


class CompetitorListOut(BaseModel):
    items: list[CompetitorOut]
    total: int


# --------------------------------------------------------------------------
# Brand mentions (extraction pipeline output)
# --------------------------------------------------------------------------


class BrandMentionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subtask_id: str
    project_id: int
    customer_id: int
    prompt: str | None
    platform: str | None
    brand: str
    is_self: bool
    is_mention: int
    rank_position: int | None
    # Discrete label from the Molizhishu API: positive / neutral / negative.
    sentiment: str | None
    is_recommended: bool | None
    # For self brand rows only: ``[{"text": mentionContext}]`` so the UI
    # can show the snippet where the brand was mentioned. Competitor rows
    # stay null (the API doesn't expose per-competitor context).
    concern_hits_json: list | None
    extract_status: ExtractStatus
    extract_error: str | None
    created_at: datetime


class BrandMentionListOut(BaseModel):
    items: list[BrandMentionOut]
    total: int


class BrandMentionSummary(BaseModel):
    """Aggregate KPIs for the overview tab."""

    project_id: int
    # Total mentions (regex) for the monitored brand across the window.
    total_mentions: int
    # Top1/Top3 rates for the monitored brand across the window.
    top1_rate: float
    top3_rate: float
    # Coverage: how many distinct (prompt, platform) pairs produced an answer.
    coverage: int
    # Sentiment average across SUCCESS rows.
    avg_sentiment: float | None
    # How many mentions are still pending vs done.
    pending_count: int
    failed_count: int


# --------------------------------------------------------------------------
# Questions analytics (问题提及分析 tab)
# --------------------------------------------------------------------------


class QuestionSummaryItem(BaseModel):
    prompt_id: int
    prompt: str
    category: str | None = None
    status: str
    total: int
    matched: int
    mention_rate: float
    top1_rate: float
    top3_rate: float
    rank_avg: float | None = None
    coverage: int


class QuestionSummaryOut(BaseModel):
    project_id: int
    start: datetime
    end: datetime
    items: list[QuestionSummaryItem]
    category_summary: list[CategoryStat]


class QuestionPlatformStat(BaseModel):
    """Per-(prompt × platform) row used by the 模型对比 table.

    Every metric is aggregated from the self-brand rows in
    ``geo_brand_mentions`` directly — the backend ``GROUP BY``s on
    ``(prompt, platform)`` so the client doesn't need to pull a
    paginated detail list and roll up counts on its own (which used
    to drift when the page size capped at 100).
    """

    platform: str
    # Number of (prompt × platform × run) rows where the brand appeared.
    matched: int
    # Total number of (prompt × platform × run) rows in the window —
    # i.e. the "X / Y" denominator. Equals how many times this model
    # was asked this question in the window.
    total: int
    # Best (smallest) rank observed; null when no run produced a rank.
    best_rank: int | None
    # Average sentiment across runs that the LLM pass filled. None
    # when no run has a sentiment yet (all PENDING).
    avg_sentiment: float | None
    # True iff at least one run in the window has ``is_recommended=true``.
    recommend_yes: bool
    # Only filled when ``view=competitor``: which competitor brand
    # drove the aggregation. ``None`` for self-view rows.
    brand: str | None = None


class PlatformExcerpt(BaseModel):
    """One platform's latest AI answer excerpt for the selected prompt.

    Used by the 「AI 回答原文摘录」 section. ``excerpt`` is truncated to
    200 chars on the server (no markdown stripping, no word boundary —
    matches the design mockup). ``run_id`` is the latest matching
    ``Subtask.subtask_id`` so the client can open the full answer
    modal. ``rank`` is the best rank observed in the window for this
    (prompt, platform) pair.
    """

    excerpt: str | None
    rank: int | None
    run_id: str | None


class QuestionPrevStat(BaseModel):
    """Same KPI shape as the current window, for the prev-period delta row."""

    total: int
    matched: int
    top1_rate: float
    top3_rate: float
    mention_rate: float
    rank_avg: float | None


class CategoryStat(BaseModel):
    """One category's roll-up, used by the 「下钻分析」 chip strip.

    Aggregated at the project level (not per-question) over the same
    window as the rest of the analytics response. The category is the
    raw ``ProjectPrompt.category`` value; the UI joins it against
    ``category_taxonomy`` for ordered display and falls back to
    「未分类」 when null.
    """

    category: str | None
    prompt_count: int
    mention_rate: float
    top1_rate: float
    top3_rate: float


class DropEvent(BaseModel):
    """One (prompt × platform) drop event for the 稳定与掉落 pane.

    Emitted when a prompt was mentioned in the prev window but the
    current window's latest run is either missing or has dropped out
    of the Top-3. ``from_rank`` / ``to_rank`` come from
    ``BrandMention.rank_position`` (best observed rank per window).
    """

    prompt_id: int
    prompt: str
    category: str | None
    platform: str
    dropped_day: str
    from_rank: int | None
    to_rank: int | None
    reason: str | None


class QuestionStatusChangesOut(BaseModel):
    """Top-level response for ``GET /projects/{id}/questions/status-changes``.

    Four independent sets (NOT a 2x2 cross-tab). Each list is
    pre-sorted by the server so the 2x2 grid can render straight
    from the JSON without re-sorting on the client.
    """

    project_id: int
    start: str
    end: str
    # Questions mentioned in BOTH the prev and current window.
    stable: list["QuestionStableItem"]
    # Drop events: per (prompt, platform) loss-of-mention in current.
    drops: list[DropEvent]
    # Questions with no mention in either window.
    never_listed: list["QuestionStableItem"]
    # Questions mentioned at least once in the current window.
    listed: list["QuestionStableItem"]


class QuestionStableItem(BaseModel):
    """Minimal row used by the 稳定 / 从未上榜 / 上榜 quadrants."""

    prompt_id: int
    prompt: str
    category: str | None
    platforms: list[str] = []


# Late resolution — DropEvent / QuestionStatusChangesOut reference
# QuestionStableItem in their type annotations.
QuestionStatusChangesOut.model_rebuild()


class QuestionProductAnalyticsOut(BaseModel):
    project_id: int
    prompt_id: int
    start: datetime
    end: datetime
    platforms: list[QuestionPlatformStat]
    prev: QuestionPrevStat | None = None
    long_prev: QuestionPrevStat | None = None
    excerpts: dict[str, PlatformExcerpt | None]


class QuestionCompetitorAnalyticsOut(BaseModel):
    project_id: int
    prompt_id: int
    start: datetime
    end: datetime
    brands: list[CompetitorBrandStat]
    excerpts: dict[str, PlatformExcerpt | None]


class CompetitorBrandStat(BaseModel):
    """One brand's row in the 竞品分析 view's brand × model matrix.

    Re-aggregates ``geo_brand_mentions`` per (prompt × brand)
    over the same window the analytics item uses. ``is_self`` flags the
    monitored brand so the UI can render the 「自身」 tag + accent ring
    around its card. ``color`` is a fixed palette slot (NOT derived from
    data) so the visual layout stays stable across windows — see the
    backend helper for the assignment rule.

    ``model_ranks`` keys are the platform identifiers (``豆包`` /
    ``元宝`` / ...). The value is the best (smallest) rank observed in
    the window for that brand on that platform; ``None`` when the brand
    never appeared on that platform in the window.
    """

    brand: str
    is_self: bool
    color: str
    # KPI cards in the brand × matrix view.
    mention_rate: float
    top1_rate: float
    top3_rate: float
    avg_rank: float | None
    # Best rank per model — ``None`` means the brand didn't appear on
    # that platform in this window.
    model_ranks: dict[str, int | None] = {}


class QuestionCompetitorOut(BaseModel):
    """One prompt's brand × model matrix. Returned inside the
    competitor endpoint response so a single round-trip gives the
    frontend everything the 竞品分析 sub-pane needs to render.

    ``brands`` is pre-sorted by the backend: the self brand first, then
    competitors by mention_rate descending (the higher-mention brands
    sit next to the operator's own brand for easier comparison).
    """

    prompt_id: int
    brands: list[CompetitorBrandStat] = []


# --------------------------------------------------------------------------
# Overview tab (docs/ui-sample #tab-overview)
# --------------------------------------------------------------------------


class OverviewKpi(BaseModel):
    """One KPI card: current value, same-length previous window, sparkline."""

    value: float
    prev_value: float
    # None when the previous window is empty, so the UI hides the arrow
    # instead of rendering a bogus +100%.
    delta_pct: float | None
    spark: list[float]


class TrendSeries(BaseModel):
    platform: str
    data: list[int]


class PlatformRank(BaseModel):
    platform: str
    top1_rate: float
    sample: int


class ModelDimension(BaseModel):
    """Per-platform rollup for the 模型维度 sub-pane (2×2 grid:
    mention_rate / top1_rate / top2_rate / top3_rate).

    Every rate here uses the platform's own ``total_subtasks`` as the
    denominator — same shape as CompetitorAnalysisTab's per-brand KPI,
    so the UI can mix self + competitors on a single chart later if
    needed. ``sample`` is the raw subtask count for tooltip display.
    """

    platform: str
    mention_rate: float
    top1_rate: float
    top2_rate: float
    top3_rate: float
    sample: int


class ProjectOverviewOut(BaseModel):
    project_id: int
    start: date
    end: date
    days: int
    labels: list[str]
    # 4 KPI cards (matching docs/更新版UI #tab-overview)
    mention_rate: OverviewKpi
    top1_rate: OverviewKpi
    top3_rate: OverviewKpi
    correct_rate: OverviewKpi
    # Detail numbers fed into each card's KPI-meta block
    total_mentions: OverviewKpi
    question_count: OverviewKpi
    answer_count: OverviewKpi
    trend: list[TrendSeries]
    ranking: list[PlatformRank]
    model_dimensions: list[ModelDimension]
    pending_count: int
    failed_count: int


# --------------------------------------------------------------------------
# Competitor analysis (data tab → 竞品分析)
# --------------------------------------------------------------------------


class CompetitorKpi(BaseModel):
    """Per-brand rollup used by the 竞品概览 table and the
    trend chart. Same shape for the self brand and competitors so the
    UI can mix them on the same chart / same row color logic.

    ``is_mention`` is the count of distinct (subtask × brand) rows
    where the brand was actually mentioned (``is_mention > 0``).
    Since the regex pass writes a 0/1 ``is_mention`` for every
    (subtask, brand) pair, this is equivalent to "how many times was
    this brand actually named in the AI's reply". ``mention_rate`` is
    that divided by ``total_subtasks`` (the window's denominator,
    shared across all brands)."""

    brand: str
    # Display name — usually the canonical string itself; the row in
    # ``geo_project_competitors`` adds aliases but no separate display
    # label, so we mirror the canonical to keep the shape uniform.
    name: str
    aliases: list[str] | None
    is_self: bool
    is_mention: int
    mention_rate: float
    top3_rate: float
    recommend_rate: float
    avg_sentiment: float | None
    avg_rank: float | None
    # Last 15 daily mention counts (zero-fill when a brand was missing on
    # a given day, capped at the window length). The UI renders this as
    # a sparkline in the 竞品概览 table.
    spark: list[int]
    # — 新增 — 详见 docs/superpowers/specs/2026-08-19-competitor-analysis-remove-advantages-matrix.md §1.1
    top1_rate: float
    sentiment_positive: float
    sentiment_neutral: float
    sentiment_negative: float
    mention_rate_delta: float | None
    top1_rate_delta: float | None
    top3_rate_delta: float | None
    sentiment_delta: float | None


class CompetitorTrendSeries(BaseModel):
    brand: str
    name: str
    is_self: bool
    # One of the platform chart colors (PLATFORM_CATALOG[*].chartColor
    # for known platforms; the frontend falls back to a default palette
    # for unknown ones). We hard-code the self color so the line stays
    # distinct in the legend.
    color: str
    data: list[int]


class CompetitorTrendBlock(BaseModel):
    labels: list[str]
    series: list[CompetitorTrendSeries]


class QuadrantPoint(BaseModel):
    platform: str
    self_mention_rate: float
    competitor_avg_mention_rate: float


class ModelDiff(BaseModel):
    platform: str
    self_mention_rate: float
    self_top1_rate: float
    self_top3_rate: float
    competitor_mention_rate: float
    competitor_top1_rate: float
    competitor_top3_rate: float


class DiffCore(BaseModel):
    """核心指标对比柱状图数据,三个值一一对应 ``labels``,单位 0-100。

    ``self`` 不能直接做字段名(与 ``BaseModel.__init__`` 的位置参数撞名),
    所以内部叫 ``self_values``,靠 alias 保持 JSON 键仍是 ``self``。
    """

    model_config = ConfigDict(populate_by_name=True)

    labels: list[str]
    self_values: list[float] = Field(alias="self")
    competitor_avg: list[float]


class CompetitorAnalysisOut(BaseModel):
    project_id: int
    start: date
    end: date
    days: int
    # Window denominator — distinct (subtask, brand) rows in the
    # window after the WHERE clause. All brand ``mention_rate`` values
    # divide by this same number.
    total_subtasks: int
    # The monitored brand (when ``geo_projects.brand`` is set), or
    # ``None`` for legacy projects that haven't picked a brand yet.
    self_brand: CompetitorKpi | None
    # All non-self brands that appeared at least once in the window,
    # ordered by is_mention DESC. Empty list when no competitor has
    # been picked up yet.
    competitors: list[CompetitorKpi]
    trend: CompetitorTrendBlock
    # — 新增 — 详见 spec §1.3
    diff_core: DiffCore
    diff_model: list[ModelDiff]
    diff_quadrant: list[QuadrantPoint]
    previous_window_start: date | None
    previous_window_end: date | None


# --------------------------------------------------------------------------
# Citation analysis (data tab → 引用源分析)
# --------------------------------------------------------------------------


# Domain-based type classification. The ui-sample uses 7 buckets; the keys
# here are the on-screen labels and the values are the matching host suffixes.
# Anything that doesn't match falls into "其他". The classifier is a small
# substring check on the subdomain+host so a URL like "news.sina.com.cn"
# still hits the "新闻网站" entry.
CITATION_TYPE_KEYS = (
    "官方网站",
    "新闻网站",
    "社交媒体",
    "百科",
    "海外网站",
    "垂类论坛",
    "自媒体",
)


# Substring matchers; order matters — the first hit wins. Each entry is
# (type, list of host substrings). The host is lowercased before checking.
_CITATION_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("百科", ("baike.baidu.com", "wikipedia.org", "wiki.", "/wiki/")),
    (
        "官方网站",
        (
            ".gov.cn",
            ".gov.",
            ".edu.cn",
            ".edu.",
            ".org.cn",
            "anthropic.com",
            "openai.com",
            "deepseek.com",
            "platform.deepseek",
            "qwen.ai",
            "qwen.com",
            "tongyi.aliyun.com",
            "yiyan.baidu.com",
            "kimi.moonshot.cn",
            "kimi.com",
            "hunyuan.tencent.com",
            "liaobots.com",
            "openrouter.ai",
            "artificialanalysis.ai",
            "lmarena.ai",
            "superclueai.com",
            "superclue.org",
            "vellum.ai",
            "toolcenter.ai",
            "官网",
        ),
    ),
    (
        "新闻网站",
        (
            "news.sina.com.cn",
            "news.sina.com",
            "sina.com",
            "sohu.com",
            "163.com",
            "qq.com/news",
            "ifeng.com",
            "thepaper.cn",
            "xinhuanet.com",
            "people.com.cn",
            "huanqiu.com",
            "chinanews.com",
            "dxy.com",
            "yicai.com",
            "caixin.com",
            "jiemodui.com",
            "36kr.com",
            "tmtpost.com",
            "techweb.com.cn",
            "c114.com.cn",
            "donews.com",
            "ithome.com",
            "leiphone.com",
            "pingwest.com",
        ),
    ),
    (
        "社交媒体",
        (
            "weibo.com",
            "weibo.cn",
            "xiaohongshu.com",
            "douban.com",
            "zhihu.com",
            "weixin.qq.com",
            "mp.weixin.qq.com",
            "tieba.baidu.com",
            "baijiahao.baidu.com",
        ),
    ),
    (
        "垂类论坛",
        (
            "csdn.net",
            "juejin.cn",
            "segmentfault.com",
            "oschina.net",
            "v2ex.com",
            "gitee.com",
            "51cto.com",
            "infoq.cn",
        ),
    ),
    (
        "自媒体",
        (
            "douyin.com",
            "bilibili.com",
            "kuaishou.com",
            "xiguashipin.com",
            "ixigua.com",
            "youtube.com",
            "youku.com",
            "v.qq.com",
            "video.sina.com.cn",
        ),
    ),
)


class CitationOut(BaseModel):
    """One URL aggregated across all subtasks that cited it in the window.

    ``title`` is the most-recent title the upstream payload attached to
    this URL (we don't store a citation history, so the latest write
    wins). ``avg_rank`` is the mean position of this URL inside the
    subtask's reference_list — the bucket is then derived on the
    frontend. ``platforms`` is the deduped set of platforms that cited
    this URL so the UI can show which models anchored on it.
    """

    url: str
    site: str
    title: str | None
    # Domain-based classifier; comes from
    # :data:`_CITATION_DOMAIN_RULES`. Falls back to "其他" when nothing
    # matched.
    type: str
    count: int
    avg_rank: float | None
    platforms: list[str]
    first_seen: datetime
    last_seen: datetime


class CitationAnalysisOut(BaseModel):
    project_id: int
    start: date
    end: date
    days: int
    # Total citation rows in the window (one per subtask that returned
    # a non-empty reference_list). Used by the UI as the "共 N 条" line.
    total_citations: int
    # Distinct URLs that received at least one citation in the window.
    unique_urls: int
    # Per-type counts so the UI can render the secondary tabs and the
    # "其他" bucket without re-aggregating.
    type_counts: dict[str, int]
    items: list[CitationOut]


class SourcePreferenceKpi(BaseModel):
    """窗口聚合 KPI — 4 个 + 1 个分母。"""
    total_references: int
    unique_urls: int
    cross_platform_urls: int
    avg_refs_per_subtask: float
    total_subtasks: int


class SourceTypeSlice(BaseModel):
    type: str
    count: int


class SourcePlatformSlice(BaseModel):
    platform: str
    total_refs: int
    unique_urls: int


class SourceTrendDay(BaseModel):
    date: date
    new_urls: int
    lost_urls: int


class SourcePreferenceItem(BaseModel):
    url: str
    site: str
    title: str | None
    type: str
    count: int
    platforms: list[str]
    first_seen: datetime
    last_seen: datetime


class SourcePreferenceOut(BaseModel):
    project_id: int
    start: date
    end: date
    days: int
    kpi: SourcePreferenceKpi
    type_counts: list[SourceTypeSlice]
    platform_slices: list[SourcePlatformSlice]
    top_sources: list[SourcePreferenceItem]
    trend: list[SourceTrendDay]
