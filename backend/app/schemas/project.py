"""Pydantic schemas for the Project API surface.

The v2 schedule is embedded on the project row, so the schedule schemas
live here too rather than in a ``schedule`` module. Slots are exchanged as
a list (``[{"hour": 9, "minute": 0}, ...]``, at most 2) and mapped onto the
``slot1_*`` / ``slot2_*`` columns by ``Project.set_schedule_slots``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    screenshot: int = Field(default=0, ge=0, le=2)


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
    brand: str | None = None
    aliases: list[str] | None = None
    category_taxonomy: list[str] | None = None
    # Number of prompts in this project — kept on the list endpoint so the
    # sidebar's 问题提及分析 badge can render the real count without a
    # second round-trip. Detail endpoint returns the same value
    # (``len(prompts)``) for consistency.
    prompts_count: int = 0
    created_at: datetime
    updated_at: datetime


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
    # Remote taskId once the run's Task row is created; null while still queued.
    task_id: str | None
    error_message: str | None
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
    brand_canonical: str
    is_self: bool
    mention_count: int
    rank_position: int | None
    sentiment_score: float | None
    is_recommended: bool | None
    concern_hits_json: list[str] | None
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


class QuestionPrevStat(BaseModel):
    """Same KPI shape as the current window, for the prev-period delta row."""

    total: int
    matched: int
    top1_rate: float
    top3_rate: float
    mention_rate: float
    rank_avg: float | None


class QuestionAnalyticsItem(BaseModel):
    """One question's roll-up for the 问题提及分析 tab.

    Items are keyed by the prompt text (matches ``BrandMention.prompt``).
    The prompt's category / status come from ``geo_project_prompts`` so
    the frontend can group + sort without re-fetching project detail.
    """

    # ``ProjectPrompt.id`` for this prompt — needed by the frontend to
    # call ``listPromptAnswers`` (which keys by numeric prompt_id).
    prompt_id: int
    prompt: str
    category: str | None
    status: str
    # KPI cards.
    total: int
    matched: int
    top1_rate: float
    top3_rate: float
    mention_rate: float
    rank_avg: float | None
    # Coverage: distinct platforms in the rows for this prompt.
    coverage: int
    # Per-platform breakdown for the 模型对比 table.
    platforms: list[QuestionPlatformStat]
    # Same-shape KPI block for the immediately-preceding window;
    # None when the prev window is empty.
    prev: QuestionPrevStat | None


class QuestionAnalyticsOut(BaseModel):
    """Top-level response for ``GET /projects/{id}/questions/analytics``."""

    project_id: int
    # Inclusive window used for the "current" KPI block. Returned so the
    # UI can echo "(2026-08-01 ~ 2026-08-14)" without re-deriving the
    # window math on the client.
    start: str
    end: str
    items: list[QuestionAnalyticsItem]


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


class ProjectOverviewOut(BaseModel):
    project_id: int
    start: date
    end: date
    days: int
    labels: list[str]
    total_mentions: OverviewKpi
    top1_rate: OverviewKpi
    top3_rate: OverviewKpi
    question_count: OverviewKpi
    answer_count: OverviewKpi
    trend: list[TrendSeries]
    ranking: list[PlatformRank]
    pending_count: int
    failed_count: int


# --------------------------------------------------------------------------
# Competitor analysis (data tab → 竞品分析)
# --------------------------------------------------------------------------


class CompetitorKpi(BaseModel):
    """Per-brand rollup used by the 竞品概览 table and the
    trend chart. Same shape for the self brand and competitors so the
    UI can mix them on the same chart / same row color logic.

    ``mention_count`` is the count of distinct (subtask × brand) rows
    where the brand was actually mentioned (``mention_count > 0``).
    Since the regex pass writes a 0/1 ``mention_count`` for every
    (subtask, brand) pair, this is equivalent to "how many times was
    this brand actually named in the AI's reply". ``mention_rate`` is
    that divided by ``total_subtasks`` (the window's denominator,
    shared across all brands)."""

    brand_canonical: str
    # Display name — usually the canonical string itself; the row in
    # ``geo_project_competitors`` adds aliases but no separate display
    # label, so we mirror the canonical to keep the shape uniform.
    name: str
    aliases: list[str] | None
    is_self: bool
    mention_count: int
    mention_rate: float
    top3_rate: float
    recommend_rate: float
    avg_sentiment: float | None
    avg_rank: float | None
    # Last 15 daily mention counts (zero-fill when a brand was missing on
    # a given day, capped at the window length). The UI renders this as
    # a sparkline in the 竞品概览 table.
    spark: list[int]


class CompetitorTrendSeries(BaseModel):
    brand_canonical: str
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


class ConcernTag(BaseModel):
    """One tag in the 差异化标签云. ``cls`` mirrors the ui-sample css:
    "brand" / "positive" / "negative" / "warn" / "default". The
    frontend maps each ``cls`` to a color from ``.tag-cloud .tag.*``."""

    text: str
    weight: int
    cls: str


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
    # ordered by mention_count DESC. Empty list when no competitor has
    # been picked up yet.
    competitors: list[CompetitorKpi]
    trend: CompetitorTrendBlock
    # Aggregated ``concern_hits_json`` tokens (per the LLM extraction
    # schema these are the project ``keywords`` that co-occurred with
    # the brand in the AI's reply). The frontend renders this as the
    # 差异化标签云 — until a dedicated NLP keyword-extraction step
    # lands, the concern-hits JSON is the best structured signal we
    # have for "what does the AI associate this brand with?".
    concern_tags: list[ConcernTag]


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
