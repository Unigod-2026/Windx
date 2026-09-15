"""Project CRUD, 4-tab config, embedded schedule, runs and task list APIs.

v2 (plan Appendix A.2) folded the old ``/api/schedules`` surface into the
project: there is no standalone schedule entity, so every schedule endpoint
is namespaced under ``/api/projects/{id}/schedule``. ``ScheduleRun`` rows
are keyed by ``project_id``.

Review workflow (post 20260908) lives on the project row itself: wizard
submissions land as ``status=PENDING`` and travel through approve / reject
without a separate ``geo_pending_projects`` table. The wizard-shaped
endpoints (``POST /api/projects``, ``PUT /api/projects/{id}/draft``,
``POST /api/projects/{id}/{approve,reject,withdraw}``) are declared
together near the top so the lifecycle is easy to follow.

Route-order note: ``/api/projects/runs/{run_id}`` is declared before
``/api/projects/{project_id}`` so the literal ``runs`` segment is not
swallowed by the int path converter.
"""

from __future__ import annotations

import io
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import Integer, and_, case, func, literal, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import require_super_admin, get_current_user
from app.models.common import now_local
from app.models.customer import AdminUser, Customer
from app.models.enums import (
    AdminRole,
    DeliveryMode,
    ProjectStatus,
    RegionStrategy,
    RunStatus,
    RunTrigger,
)
from app.models.project import (
    BrandMention,
    OwnArticle,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.schedule import ScheduleRun
from app.models.task import Subtask, Task
from app.services.scheduler import run_project_async
from app.services.scheduler_runtime import reload_jobs
from app.services.competitor_analysis import (
    _resolve_competitor_window,
    compute_competitor_analysis,
)
from app.services.source_preferences import (
    _compound_platform,
    _expand_platform_keys,
    compute_source_detail,
    compute_source_preferences,
    compute_source_self,
    compute_source_video,
)
from app.services import own_articles
from app.schemas.project import (
    BrandMentionListOut,
    BrandMentionOut,
    BrandMentionSummary,
    CitationAnalysisOut,
    CitationOut,
    CompetitorAnalysisOut,
    CompetitorBrandStat,
    CompetitorIn,
    CompetitorListOut,
    CompetitorOut,
    PromptAnswerListOut,
    PromptAnswerOut,
    PromptAnswerDetailOut,
    KeywordsUpdate,
    ModelDimension,
    PlatformsUpdate,
    ProjectCreate,
    ProjectDetailOut,
    ProjectListOut,
    ProjectOut,
    ProjectOverviewOut,
    ProjectTaskListOut,
    ProjectTaskOut,
    ProjectUpdate,
    OverviewKpi,
    PlatformRank,
    PromptOut,
    PromptsUpdate,
    QuestionProductAnalyticsOut,
    QuestionCompetitorAnalyticsOut,
    QuestionCompetitorOut,
    QuestionPlatformStat,
    QuestionPrevStat,
    QuestionStableItem,
    QuestionStatusChangesOut,
    QuestionSummaryItem,
    QuestionSummaryOut,
    PlatformExcerpt,
    CategoryStat,
    DropEvent,
    ReviewDecisionIn,
    RunSummary,
    ScheduleOut,
    ScheduleRunListOut,
    ScheduleRunOut,
    ScheduleStatusUpdate,
    ScheduleUpdate,
    SubtaskListOut,
    SubtaskOut,
    TrendSeries,
    TriggerOut,
    SourcePlatformSlice,
    SourcePreferenceItem,
    SourcePreferenceKpi,
    SourcePreferenceOut,
    SourceDetailItem,
    SourceDetailOut,
    SourceSelfItem,
    SourceSelfOut,
    SourceTrendDay,
    SourceTypeSlice,
    VideoSourceOut,
    OwnArticleImportPreview,
    OwnArticleImportResult,
    OwnArticleListOut,
    OwnArticleOut,
    WizardModelConfig,
    WizardPayload,
    WizardSemantic,
    WizardSubmissionIn,
    _CITATION_DOMAIN_RULES,
)
from app.services.schedule_time import cooldown_key, earliest_next_run

router = APIRouter(prefix="/api", tags=["projects"])


# Sentiment label → float. The DB column is VARCHAR(16) holding the API label
# ("positive" / "neutral" / "negative") since the API-pass refactor (migration
# 20260818_0001). Dashboard KPIs still want a numeric average for the color
# buckets (>=0.7 green / >=0.5 orange / else red), so we translate on the fly.
_SENTIMENT_TO_FLOAT: dict[str, float] = {
    "positive": 1.0,
    "neutral": 0.5,
    "negative": 0.0,
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _paginate(page: int, size: int) -> tuple[int, int]:
    return max(1, page), min(100, max(1, size))


def _get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    return p


def _assert_customer_access(user: AdminUser, project: Project) -> None:
    """Block ``customer_admin`` from peeking at projects outside their tenant."""
    if user.role is AdminRole.CUSTOMER_ADMIN and project.customer_id != user.customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="project does not belong to your customer",
        )


def _resolve_window_inline(
    days: int | None,
    start: date | None,
    end: date | None,
) -> tuple[datetime, datetime]:
    """共用窗口解析:`start`/`end` 优先,否则取最近 N 天(默认 15)。

    返回 ``[win_start_dt, win_end_dt]``,起闭是 ``[00:00, 23:59:59]`` —
    与 ``list_brand_mentions`` 及三个 v2 analytics 端点保持一致;便于
    ``BrandMention.created_at``/``Subtask.updated_at`` 用 ``>=`` / ``<`` 跨端点
    统一比对。

    raises:
      400: ``start`` / ``end`` 必须同进同出,且 end ≥ start;``days`` 落在
           ``[1, 90]``。
    """
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=window_days - 1)
        win_end = today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    return win_start_dt, win_end_dt


# --------------------------------------------------------------------------
# Compound key helpers — ``${platform_code}__${delivery}__${thinking}``
# 形如 ``qianwen__web__fast`` / ``baidu_mobile__mobile__think``,与
# ``frontend/src/pages/Projects/platforms.ts`` 的 ``OVERVIEW_KEY_RE`` 与
# ``parseOverviewKey`` 是 wire contract 双端。Overview / 问题提及分析两
# 边共用,所以放在这里而不是 endpoint 内部:
#  - trend / ranking / model_dimensions 在 Overview 已落地 compound key;
#  - 问题提及分析 4 个端点现在也按 triple 拆分,避免 tab 之间口径错位;
#  - GlobalToolbar 工具栏勾选 / 反选 通过 compound key 走 wire,后端解析
#    后用 SQL ``tuple_(...).in_(triples)`` 一次性过滤三个列。
# --------------------------------------------------------------------------

_COMPOUND_KEY_RE = re.compile(r"^(.+)__(web|mobile)__(fast|think)$")


def compound_key(
    platform_code: str,
    delivery_mode: str,
    thinking_mode: bool | None,
) -> str:
    """``${platform_code}__${delivery_mode}__${thinking}`` —— ``thinking_mode``
    缺省按 False 处理,避免与旧 fixture ``None`` 行拼出 ``__None__`` 这种坏
    key。"""
    thinking = "think" if thinking_mode else "fast"
    return f"{platform_code}__{delivery_mode}__{thinking}"


def parse_compound_key(
    raw: str,
) -> tuple[str, str, bool] | None:
    """反向解出 ``(platform_code, delivery_mode, is_thinking)``;非法 token
    返回 ``None``,调用方按「静默忽略」处理(Overview 用同一口径)。"""
    m = _COMPOUND_KEY_RE.fullmatch(raw)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3) == "think"


def parse_platforms_param(
    raw: str | None,
) -> set[tuple[str, str, bool]] | None:
    """``?platforms=qianwen__web__fast,baidu_mobile__mobile__think`` →
    ``{(platform_code, delivery_mode, is_thinking)}``。

    - 缺省 / 空字符串 → ``None``,调用方走「全选」分支;
    - 任一 token 非法 → 静默忽略(与 Overview 一致);全部非法 → ``set()``
      由调用方按「0 行」处理。
    """
    if raw is None:
        return None
    if not raw.strip():
        return None
    triples: set[tuple[str, str, bool]] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        parsed = parse_compound_key(tok)
        if parsed is None:
            continue
        triples.add(parsed)
    return triples


def parse_prompt_ids_param(
    raw: str | None,
) -> list[int] | None:
    """``?prompt_ids=12,34,56`` → ``[12, 34, 56]``。缺省 / 空字符串 → ``None``
    (走「不筛」分支);任一非数字 token 静默丢弃。"""
    if raw is None:
        return None
    if not raw.strip():
        return None
    ids: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            ids.append(int(tok))
        except ValueError:
            continue
    return ids


def project_platform_triples(
    db: Session, project_id: int
) -> set[tuple[str, str, bool]]:
    """该项目配的 ``(platform_code, delivery_mode, is_thinking)`` 三元组集合,
    作为「覆盖度分母」与图表 series 名空间。

    注意:与 Overview 的 ``_overview_key`` / selected_triples 口径一致 —
    都走 ``platform_code``(不是 ``platform``),mobile 档的真实 code 来自
    这列。"""
    rows = db.execute(
        select(
            ProjectPlatform.platform_code,
            ProjectPlatform.delivery_mode,
            ProjectPlatform.thinking_mode,
        ).where(ProjectPlatform.project_id == project_id)
    ).all()
    return {
        (r.platform_code, r.delivery_mode.value, bool(r.thinking_mode))
        for r in rows
    }


def _next_run(p: Project):
    """Earliest upcoming fire time across both ``fast`` / ``think`` modes.

    Only an enabled schedule on an active project has a next run. Time-of-
    day comes from the global ``MONITOR_DEFAULT_HOUR`` /
    ``MONITOR_DEFAULT_MINUTE`` env vars (per spec §weekly-schedule). The
    per-mode breakdown (so the dashboard can show "下次快速 / 下次思考")
    lives in :mod:`app.api.dashboard`.
    """
    if not p.schedule_enabled or p.status is not ProjectStatus.ACTIVE:
        return None
    settings = get_settings()
    return earliest_next_run(
        p.monitor_schedule,
        hour=settings.monitor_default_hour,
        minute=settings.monitor_default_minute,
    )


def _to_out(p: Project, prompts_count: int | None = None) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.next_run_at = _next_run(p)
    out.prompts_count = prompts_count if prompts_count is not None else 0
    return out


def _prompts_count_for(db: Session, project_ids: list[int]) -> dict[int, int]:
    """One GROUP BY query instead of N+1 — returns {project_id: count}.

    ``project_ids`` may be empty; the caller should fall back to per-row
    computation if needed (currently nothing does).
    """
    if not project_ids:
        return {}
    rows = db.execute(
        select(ProjectPrompt.project_id, func.count(ProjectPrompt.id))
        .where(ProjectPrompt.project_id.in_(project_ids))
        .group_by(ProjectPrompt.project_id)
    ).all()
    return {pid: cnt for pid, cnt in rows}


def _to_detail(p: Project, db: Session) -> ProjectDetailOut:
    # Built from the ProjectOut payload rather than ``model_validate(p)``:
    # the detail fields share names with the ORM relationships, and
    # from_attributes would pull the raw ORM rows instead of the ordered,
    # flattened lists queried below.
    prompts = [
        PromptOut.model_validate(r)
        for r in db.scalars(
            select(ProjectPrompt)
            .where(ProjectPrompt.project_id == p.id)
            .order_by(ProjectPrompt.sort)
        )
    ]
    return ProjectDetailOut(
        **_to_out(p, prompts_count=len(prompts)).model_dump(),
        prompts=prompts,
        keywords=[
            r.keyword
            for r in db.scalars(
                select(ProjectKeyword)
                .where(ProjectKeyword.project_id == p.id)
                .order_by(ProjectKeyword.sort)
            )
        ],
        platforms=[
            {
                "id": r.id,
                "platform": r.platform,
                "platform_code": r.platform_code,
                "mode": r.mode,
                "delivery_mode": r.delivery_mode,
                "thinking_mode": r.thinking_mode,
                "screenshot": r.screenshot,
            }
            for r in db.scalars(
                select(ProjectPlatform)
                .where(ProjectPlatform.project_id == p.id)
                .order_by(ProjectPlatform.sort)
            )
        ],
    )


def _apply_schedule(
    p: Project,
    *,
    enabled: bool,
    monitor_schedule: dict[str, dict] | None,
) -> None:
    """Write the per-mode ``monitor_schedule`` + enabled flag onto the row.

    ``monitor_schedule`` is the canonical per-mode map
    ``{"fast": {"freq", "days"}, "think": {"freq", "days"}}``. An entry
    whose ``days`` is empty is treated as "this mode is not scheduled"
    and dropped before the row is written — keeps a half-cleared project
    from looking identical to one that was never configured.

    Validation rule: an enabled schedule must have at least one mode with
    a non-empty ``days`` list. We coerce empty/full-null inputs to
    ``None`` so a disabled project can round-trip through the API without
    spurious defaults.
    """
    cleaned = _clean_monitor_schedule(monitor_schedule)
    if enabled and not _has_any_days(cleaned):
        raise HTTPException(400, "cannot enable a schedule with no monitor_days")
    p.monitor_schedule = cleaned
    p.schedule_enabled = enabled


def _clean_monitor_schedule(value: dict | None) -> dict | None:
    """Strip empty / malformed entries from a monitor_schedule payload.

    Returns ``None`` when nothing is left so a totally-disabled project
    doesn't round-trip through the API with ``{}`` masquerading as
    "configured but empty" — the wizard and the schedule endpoint both
    treat ``None`` as "no schedule".

    Accepts either raw dicts (from the JSON body after FastAPI parses
    them) or Pydantic ``MonitorScheduleEntry`` instances (when the
    payload flows through ``ProjectCreate.monitor_schedule`` /
    ``WeeklyScheduleUpdate.monitor_schedule`` and gets here still
    wrapped). Pydantic models expose ``model_dump`` so we use that.
    """
    if not value:
        return None
    out: dict[str, dict] = {}
    for mode in ("fast", "think"):
        entry = value.get(mode)
        if entry is None:
            continue
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        if not isinstance(entry, dict):
            continue
        days = entry.get("days") or []
        if not days:
            continue
        freq = entry.get("freq") or "w1"
        out[mode] = {"freq": freq, "days": list(days)}
    return out or None


def _has_any_days(schedule: dict | None) -> bool:
    if not schedule:
        return False
    for entry in schedule.values():
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        days = entry.get("days") if isinstance(entry, dict) else None
        if days:
            return True
    return False


# --------------------------------------------------------------------------
# Wizard materialisation
#
# The wizard submits a single ``WizardPayload`` blob. We materialise it
# onto the project row + the three child tables (prompts / competitors /
# platforms) on every submit / draft / approve so the 待审核 page can show
# the full structure without a separate "draft" surface — the project row
# IS the draft while ``status=PENDING``.
#
# The platform mapping mirrors ``wizardConfig.WIZARD_MODELS``: each model
# option carries ``hasMobile`` + ``mobileCode``. We hard-code the same
# mapping here so the backend can resolve ``platform_code`` for both
# surfaces without consulting the frontend. ``platform_code`` is what the
# scheduler forwards to ``LLMClient.submit_task``; getting it wrong means
# downstream prompts can't find the model. If a model is added to the
# frontend catalogue, the corresponding entry below has to be added too.
# --------------------------------------------------------------------------


_WIZARD_MODEL_CATALOG: dict[
    str, dict[str, str | bool | None]
] = {
    "doubao": {"has_mobile": True, "mobile_code": "doubao_mobile"},
    "yuanbao": {"has_mobile": True, "mobile_code": "yuanbao_mobile"},
    "qianwen": {"has_mobile": True, "mobile_code": "qianwen_mobile"},
    "kimi": {"has_mobile": False, "mobile_code": None},
    "deepseek": {"has_mobile": True, "mobile_code": "deepseek_mobile"},
    "baiduai": {"has_mobile": True, "mobile_code": "baidu_mobile"},
    "antafu": {"has_mobile": False, "mobile_code": None},
    "chatgpt": {"has_mobile": False, "mobile_code": None},
    # 2026-09 远端 /api/business/system/models 新增;web only。
    "weibo_zhisou": {"has_mobile": False, "mobile_code": None},
    "quark": {"has_mobile": False, "mobile_code": None},
    # douyinai 走"抖音AI搜索"web;远端 mobile 对应 douyin_mobile,命名规则
    # 不统一(baiduai → baidu_mobile 同样是这套),显式维护。
    "douyinai": {"has_mobile": True, "mobile_code": "douyin_mobile"},
}


def _expand_wizard_platforms(
    db: Session,
    project_id: int,
    models: list[str],
    devices: list[str],
    models_config: list[WizardModelConfig] | None = None,
    modes: list[Literal["fast", "think"]] | None = None,
) -> list[ProjectPlatform]:
    """Translate the wizard's model selection into ``ProjectPlatform`` rows.

    Two input shapes converge here:

    * ``models_config`` (待审核 modal) — every surface is already an
      explicit code with its own 快速 / 思考 / 截图 choice, so it wins
      over ``devices`` and produces one row per (code, mode).
    * ``models`` + ``devices`` + ``modes`` (wizard) — web codes
      cross-producted with the selected surfaces and modes;
      ``devices`` defaults to ``["pc"]`` and ``modes`` defaults to
      ``["fast"]`` so a submission that forgets either still yields a
      usable row. Mobile-only models (``has_mobile=False``) drop out of
      the mobile pass rather than shipping a code the remote can't
      resolve.

    ``thinking_mode`` carries the 思考模式 flag; a card with both modes
    on emits two rows sharing ``platform_code``.
    """
    # Pre-resolve the (web_code → mobile_code) lookup so the per-row
    # branch below stays readable.
    web_to_mobile: dict[str, str] = {
        web: info["mobile_code"]
        for web, info in _WIZARD_MODEL_CATALOG.items()
        if info.get("has_mobile") and info.get("mobile_code")
    }
    mobile_to_web: dict[str, str] = {
        mobile: web for web, mobile in web_to_mobile.items()
    }

    # (platform, platform_code, delivery, thinking, screenshot) tuples,
    # deduped by ``(platform_code, thinking)`` so a payload that lists the
    # same surface twice (e.g. a stale ``models`` entry alongside
    # ``models_config``) doesn't double-submit to the remote. ``thinking``
    # is the boolean twin of ``mode`` (``False`` ↔ ``"search"``,
    # ``True`` ↔ ``"reasoning_search"``),所以 dedup 键等价于远端的
    # ``(platform_code, mode)`` 元组。同一 ``platform``(逻辑模型名,如
    # ``doubao``)的最大输出是 4 行:web×fast、web×think、mobile×fast、
    # mobile×think,正好覆盖远端去重粒度下的全部 4 种调用。
    specs: list[tuple[str, str, DeliveryMode, bool, int]] = []
    seen: set[tuple[str, bool]] = set()

    def _push(code: str, thinking: bool, screenshot: int) -> None:
        if code in mobile_to_web:
            platform = mobile_to_web[code]
            delivery = DeliveryMode.MOBILE
        elif code in _WIZARD_MODEL_CATALOG:
            platform = code
            delivery = DeliveryMode.WEB
        else:
            # Unknown code (legacy / typo) — drop silently. The UI only
            # renders known WIZARD_MODELS so this branch is defensive.
            return
        key = (code, thinking)
        if key in seen:
            return
        seen.add(key)
        specs.append((platform, code, delivery, thinking, screenshot))

    if models_config:
        # ``models_config`` carries one entry per model card; entries with
        # an empty ``modes`` list are "card visible but unselected" and
        # must NOT emit a row — the previous ``entry.modes or ["fast"]``
        # fallback silently produced a row per unselected card on every
        # draft save, so a 12-card wizard state could inflate
        # ``geo_project_platforms`` by ~10 phantom rows per save.
        for entry in models_config:
            if not entry.modes:
                continue
            for mode in entry.modes:
                _push(entry.code, mode == "think", 1 if entry.screenshot else 0)
    else:
        # ``modes`` defaults to ``["fast"]`` so legacy wizard submissions
        # without the modes field keep producing rows (mirrors the
        # pre-modes behaviour).
        effective_modes = modes or ["fast"]
        for model in models:
            if not model:
                continue
            if model in mobile_to_web:
                # Explicit mobile code — independent of ``devices``.
                for mode in effective_modes:
                    _push(model, mode == "think", 0)
                continue
            info = _WIZARD_MODEL_CATALOG.get(model)
            if info is None:
                continue
            for device in devices or ["pc"]:
                if device == "mobile":
                    if not info.get("has_mobile"):
                        continue
                    code = info["mobile_code"]
                else:
                    code = model
                if not code:
                    continue
                for mode in effective_modes:
                    _push(str(code), mode == "think", 0)

    out: list[ProjectPlatform] = []
    for sort, (platform, code, delivery, thinking, screenshot) in enumerate(specs):
        # ``platform_code`` 一律按 WIZARD_MODELS 走:web = value,mobile =
        # mobileCode。thinking 维度由 ``mode`` / ``thinking_mode`` 列承担,
        # scheduler 把 ``platform`` + ``mode`` 作为独立字段转发给远端
        # LLM —— 远端去重键是 ``(platform, mode)`` 元组,不是单一
        # ``platform`` 名,所以同名 + 不同 mode 会被算成两次调用,不需要
        # 在 platform_code 里塞 ``_reasoning`` 后缀。
        row = ProjectPlatform(
            project_id=project_id,
            platform=platform,
            platform_code=code,
            # fast → search,think → reasoning_search。UI 二分模式
            # (快速 / 思考) → 远端四选一 mode 的 1:1 映射 —— Segmented
            # 只有这两档,所以只能落到这两个具体 mode 上;scheduler 在
            # :mod:`app.services.scheduler` 把这一列原样转发给远端
            # LLM(``https://github.com/molizhishu/molizhishu-api-pub/blob/main/docs/api/submit-task.md``),
            # 所以这一行既是 UI 桶,
            # 也是真正给远端用的 mode。
            mode="reasoning_search" if thinking else "search",
            delivery_mode=delivery,
            thinking_mode=thinking,
            screenshot=screenshot,
            sort=sort,
        )
        db.add(row)
        out.append(row)
    return out


def _prune_semantic(payload: WizardSemantic) -> dict | None:
    """Strip empty fields so the stored JSON isn't full of ``null``s.

    Mirrors the previous ``_prune_semantic`` helper from the deleted
    pending-projects service. ``selling_points`` keeps its empty list
    (the wizard always writes an explicit list); everything else is
    dropped when falsy. Returns ``None`` when nothing is left so the
    project row can store ``NULL``.
    """
    cleaned: dict = {"selling_points": list(payload.selling_points)}
    for field in (
        "website",
        "phone",
        "address",
        "email",
        "wechat_service",
        "wechat_official",
        "xiaohongshu",
        "douyin",
        "weibo",
        "custom",
    ):
        value = getattr(payload, field)
        if value:
            cleaned[field] = value
    return cleaned or None


def _materialise_wizard_payload(
    db: Session,
    project: Project,
    payload: WizardPayload,
    *,
    preserve_schedule_enabled: bool = False,
) -> None:
    """Write wizard payload fields onto an existing ``Project`` row.

    Replaces the project-row fields that the wizard owns, then wipes and
    rebuilds the three child tables (prompts / competitors / platforms).
    Caller is responsible for ``commit()`` so the function can be reused
    from submit (one transaction) and draft-edit (one transaction).

    ``preserve_schedule_enabled`` defaults to ``False``: PENDING
    submissions compute ``schedule_enabled`` from ``monitor.days``
    (``bool(days)``). When ``True`` (active/disabled edits routed
    through ``put_wizard_draft``) the existing ``schedule_enabled`` is
    kept — that flag lives on the list-page Switch, so a wizard edit
    must not silently flip it.
    """
    # Project-row fields owned by the wizard.
    project.brand = payload.brand.name
    project.aliases = list(payload.brand.aliases)
    project.sentiment_enabled = payload.sentiment == "on"
    project.region_strategy = (
        RegionStrategy.NATIONAL_RANDOM
        if payload.geo.mode == "national_random"
        else RegionStrategy.FIXED
    )
    if payload.geo.mode == "fixed" and payload.geo.region_code:
        project.region_codes = [payload.geo.region_code]
    else:
        project.region_codes = None
    project.category_taxonomy = list(payload.categories) or None
    project.semantic_json = _prune_semantic(payload.semantic)
    # Schedule. Per-mode: the wizard owns a ``{fast, think}`` map and we
    # write it straight onto ``monitor_schedule``. The schedule can't be
    # enabled without at least one mode picking a non-empty day list —
    # otherwise we silently leave it disabled so the operator doesn't
    # end up with a master switch on and zero crons registered.
    # ``preserve_schedule_enabled`` overrides that flip because the active
    # modal route is allowed to rewrite freq / days without touching
    # the master switch.
    schedule_payload = payload.monitor.schedules or {}
    cleaned_schedule = _clean_monitor_schedule(
        {
            mode: entry.model_dump() if entry else None
            for mode, entry in schedule_payload.items()
        }
    )
    project.monitor_schedule = cleaned_schedule
    if not preserve_schedule_enabled:
        project.schedule_enabled = _has_any_days(cleaned_schedule)

    # Prompts — delete + insert so order matches the wizard verbatim.
    db.query(ProjectPrompt).filter(ProjectPrompt.project_id == project.id).delete()
    for i, q in enumerate(payload.questions):
        db.add(
            ProjectPrompt(
                project_id=project.id,
                prompt=q.text,
                category=q.category or None,
                status="monitoring",
                sort=i,
            )
        )

    # Competitors — same delete + insert pattern; we accept whatever
    # name / alias list the wizard provides.
    db.query(ProjectCompetitor).filter(
        ProjectCompetitor.project_id == project.id
    ).delete()
    for i, c in enumerate(payload.competitors):
        db.add(
            ProjectCompetitor(
                project_id=project.id,
                name=c.name,
                note=c.product,
                aliases=list(c.aliases),
                origin="manual",
                status="confirmed",
                sort=i,
            )
        )

    # Platforms — wipe and rebuild from (model × device). Any mobile
    # rows whose model has no mobile variant are silently dropped
    # (handled by ``_expand_wizard_platforms``).
    db.query(ProjectPlatform).filter(ProjectPlatform.project_id == project.id).delete()
    _expand_wizard_platforms(
        db,
        project.id,
        list(payload.models),
        list(payload.monitor.devices),
        list(payload.models_config),
        list(payload.monitor.modes),
    )


# --------------------------------------------------------------------------
# Project CRUD
# --------------------------------------------------------------------------


@router.post("/customers/{customer_id}/projects", response_model=ProjectOut)
def create_project(
    customer_id: int,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "customer not found")
    if db.scalar(
        select(Project).where(
            Project.customer_id == customer_id, Project.code == payload.code
        )
    ):
        raise HTTPException(400, "project code exists in this customer")

    p = Project(
        customer_id=customer_id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
        status=ProjectStatus.ACTIVE,
        sentiment_enabled=payload.sentiment_enabled,
        region_strategy=payload.region_strategy,
        region_codes=payload.region_codes,
        category_taxonomy=payload.category_taxonomy,
    )
    _apply_schedule(
        p,
        enabled=payload.schedule_enabled,
        monitor_schedule=payload.monitor_schedule,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


# --------------------------------------------------------------------------
# Wizard review workflow
#
# The wizard submission, draft edit, approve / reject and withdraw all
# target the SAME project row — there's no separate pending shadow
# table since the 20260908_0002 migration. ``POST /api/projects`` is the
# entry point for a new submission; ``PUT /api/projects/{id}/draft``
# overwrites the wizard payload for an existing PENDING row; the
# approve / reject / withdraw endpoints drive the lifecycle transitions.
#
# Tenant scoping: customer_admin may only create / edit / withdraw rows
# inside their own ``customer_id``. super_admin may pick any tenant via
# ``customer_id`` in the body. Tenant mismatch returns 403.
# --------------------------------------------------------------------------


def _resolve_wizard_customer_id(
    db: Session,
    user: AdminUser,
    requested: int | None,
) -> int:
    """Pick the ``customer_id`` a wizard submission lands in.

    customer_admin → always their own tenant; super_admin → the body's
    ``customer_id`` (mandatory — None is treated as 400). Tenant must
    exist.
    """
    if user.role is AdminRole.CUSTOMER_ADMIN:
        if user.customer_id is None:
            raise HTTPException(403, "customer admin has no tenant binding")
        return user.customer_id
    if requested is None:
        raise HTTPException(400, "customer_id is required for super admin")
    if not db.get(Customer, requested):
        raise HTTPException(404, "customer not found")
    return requested


def _generate_wizard_code(db: Session, customer_id: int, brand_name: str) -> str:
    """Stable per-customer code derived from brand + counter suffix.

    The wizard never asks the operator for a code; we materialise one so
    the ``(customer_id, code)`` unique index is satisfied. The slug
    keeps the human-readable part short; the counter disambiguates
    when two submissions use the same brand name.
    """
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", brand_name.lower()).strip("-")[:24] or "project"
    base = f"wiz-{slug}"
    candidate = base
    counter = 1
    while db.scalar(
        select(Project).where(
            Project.customer_id == customer_id, Project.code == candidate
        )
    ):
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate


@router.post("/projects", response_model=ProjectOut)
def submit_wizard_project(
    payload: WizardSubmissionIn,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Wizard submission. Creates a ``status=PENDING`` project row, then
    materialises prompts / platforms / competitors from the wizard payload
    so the 待审核 page is fully queryable without a draft table.

    Returns ``ProjectOut`` so the frontend can navigate straight to the
    detail view (the new project id is known immediately).
    """
    customer_id = _resolve_wizard_customer_id(db, user, payload.customer_id)
    now = now_local()
    code = _generate_wizard_code(db, customer_id, payload.payload.brand.name)
    project = Project(
        customer_id=customer_id,
        name=payload.payload.brand.name,
        code=code,
        description=None,
        status=ProjectStatus.PENDING,
        # Review metadata — populated up front so the pending row carries
        # the submitter identity from the moment of submission. Approved /
        # rejected timestamps get filled in by the lifecycle endpoints.
        submitted_by=user.id,
        submitted_at=now,
        wizard_payload_json=json.dumps(
            payload.payload.model_dump(mode="json"), ensure_ascii=False
        ),
    )
    db.add(project)
    db.flush()  # surface the PK before the child inserts
    _materialise_wizard_payload(db, project, payload.payload)
    db.commit()
    db.refresh(project)
    return _to_out(project)


@router.put("/projects/{project_id}/draft", response_model=ProjectOut)
def put_wizard_draft(
    project_id: int,
    payload: WizardSubmissionIn,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Re-edit a project's wizard payload. Used both for PENDING drafts
    and for active/disabled rows now that the edit modal routes every
    save through this endpoint. Both ``super_admin`` and the original
    ``customer_admin`` may update.

    The lifecycle rules:

    - REJECTED rows are dead-on-arrival: the UI shows a re-submit
      button instead, so a 409 here is purely defensive.
    - ACTIVE + ``schedule_enabled`` rows are mid-flight in the
      scheduler loop; rewriting platforms / days / keywords out from
      under a running cron could produce inconsistent run state, so
      the operator has to pause the schedule first. PENDING, ACTIVE
      (paused), and DISABLED rows all accept the edit.
    - ``preserve_schedule_enabled`` controls whether the active toggle
      is recomputed from ``monitor.days`` (default: PENDING semantics)
      or kept verbatim (paused active/disabled editing).
    """
    project = _get_project(db, project_id)
    if project.status is ProjectStatus.REJECTED:
        raise HTTPException(
            409, "wizard draft cannot be saved while project is rejected"
        )
    if (
        project.status is ProjectStatus.ACTIVE
        and project.schedule_enabled
    ):
        raise HTTPException(
            409,
            "wizard draft cannot be saved while the project is actively scheduled; "
            "pause it on the list page first",
        )
    _assert_customer_access(user, project)
    _materialise_wizard_payload(
        db,
        project,
        payload.payload,
        preserve_schedule_enabled=payload.preserve_schedule_enabled,
    )
    # 「监控名称」属于项目行字段,wizard payload 不携带;PENDING 走这里
    # 更新(active/disabled 也可以带,但已有 update_project 路径同名改写,
    # 幂等冗余)。trim 跟 wizard submit 时的 ``brand.name`` 处理对齐。
    if payload.name is not None:
        trimmed = payload.name.strip()
        if trimmed:
            project.name = trimmed
    project.wizard_payload_json = json.dumps(
        payload.payload.model_dump(mode="json"), ensure_ascii=False
    )
    db.commit()
    db.refresh(project)
    return _to_out(project)


@router.post("/projects/{project_id}/approve", response_model=ProjectOut)
def approve_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_super_admin),
):
    """Super admin only. ``PENDING`` → ``ACTIVE`` and stamps approver + reviewed
    audit fields. Materialised wizard payload becomes the canonical
    project config — the wizard_payload_json column is kept on the row
    for audit (UI doesn't render it on the active page).

    审批本身不启用调度 —— ``schedule_enabled`` 强制写 False,ops 在列表页
    ``Switch`` 主动开才算进 rotation。这避免了「提交时勾了周一 → 审批通过后
    立刻开始跑」的隐式副作用,也让 PENDING 时配的 ``monitor.days`` 仅作为
    待审材料的展示,不被解读为「已经同意按此频率跑」。
    """
    project = _get_project(db, project_id)
    if project.status is not ProjectStatus.PENDING:
        raise HTTPException(
            409, f"only pending projects can be approved (current: {project.status.value})"
        )
    now = now_local()
    project.status = ProjectStatus.ACTIVE
    project.schedule_enabled = False
    project.reviewed_by = user.id
    project.reviewed_at = now
    project.approved_by = user.id
    project.approved_at = now
    db.commit()
    db.refresh(project)
    # 状态/字段变更可能影响 job 表(此前的 schedule_enabled=true 行被拒收、
    # 新增的 disabled 行不需要 register),刷一遍让 APScheduler 与 DB 对齐。
    if scheduler := getattr(request.app.state, "scheduler", None):
        reload_jobs(scheduler)
    return _to_out(project)


@router.post("/projects/{project_id}/reject", response_model=ProjectOut)
def reject_project(
    project_id: int,
    payload: ReviewDecisionIn,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_super_admin),
):
    """Super admin only. ``PENDING`` → ``REJECTED`` and stamps the review note.
    Schedule stays disabled (it was never enabled on a pending row)."""
    project = _get_project(db, project_id)
    if project.status is not ProjectStatus.PENDING:
        raise HTTPException(
            409, f"only pending projects can be rejected (current: {project.status.value})"
        )
    now = now_local()
    project.status = ProjectStatus.REJECTED
    project.reviewed_by = user.id
    project.reviewed_at = now
    project.review_note = payload.review_note
    db.commit()
    db.refresh(project)
    return _to_out(project)


@router.post("/projects/{project_id}/withdraw")
def withdraw_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Customer admin hard-deletes their own pending submission. Super
    admin can withdraw any pending row. Approved / rejected rows are
    kept for audit and return 409 here — withdrawing an audited row
    would lose the history."""
    project = _get_project(db, project_id)
    if project.status is not ProjectStatus.PENDING:
        raise HTTPException(
            409, f"only pending projects can be withdrawn (current: {project.status.value})"
        )
    if user.role is AdminRole.CUSTOMER_ADMIN:
        if project.customer_id != user.customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="project does not belong to your customer",
            )
    # Wipe child rows first so a future ``DELETE`` policy can remove the
    # project row without leaving orphaned prompts / competitors /
    # platforms. The dependent tables don't FK to ``geo_projects`` so
    # this is belt-and-suspenders; we keep it explicit so a future
    # cascade policy change can't quietly strand children.
    db.query(ProjectPrompt).filter(ProjectPrompt.project_id == project.id).delete()
    db.query(ProjectCompetitor).filter(
        ProjectCompetitor.project_id == project.id
    ).delete()
    db.query(ProjectPlatform).filter(ProjectPlatform.project_id == project.id).delete()
    db.query(ProjectKeyword).filter(ProjectKeyword.project_id == project.id).delete()
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.get("/projects", response_model=ProjectListOut)
def list_projects(
    page: int = 1,
    size: int = 20,
    customer_id: int | None = None,
    status: str | None = None,
    schedule_enabled: bool | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    page, size = _paginate(page, size)
    stmt = select(Project)
    # customer_admin is auto-scoped to their own customer; super_admin may
    # pass ?customer_id= to filter. An explicit customer_id still wins so
    # super_admin tooling can scope when it wants to.
    if user.role is AdminRole.CUSTOMER_ADMIN:
        stmt = stmt.where(Project.customer_id == user.customer_id)
    elif customer_id is not None:
        stmt = stmt.where(Project.customer_id == customer_id)
    if status:
        stmt = stmt.where(Project.status == status)
    if schedule_enabled is not None:
        stmt = stmt.where(Project.schedule_enabled == schedule_enabled)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Project.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    counts = _prompts_count_for(db, [p.id for p in items])
    return ProjectListOut(
        items=[_to_out(p, prompts_count=counts.get(p.id, 0)) for p in items],
        total=total,
        page=page,
        size=size,
    )


# Declared before /projects/{project_id} so "runs" isn't parsed as an id.
@router.get("/projects/runs/{run_id}", response_model=ScheduleRunOut)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    r = db.get(ScheduleRun, run_id)
    if not r:
        raise HTTPException(404, "run not found")
    counts_map = _subtask_counts_for_runs(db, [run_id])
    return _run_with_counts(r, counts_map.get(run_id, {}))


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    return _to_detail(project, db)


def _apply_category_taxonomy_change(
    db: Session,
    project_id: int,
    old_taxonomy: list[str] | None,
    new_taxonomy: list[str] | None,
    renames: dict[str, str] | None,
) -> None:
    """Reconcile ``geo_project_prompts.category`` against a new taxonomy.

    Called from ``PUT /projects/{id}`` when ``category_taxonomy`` is in the
    payload. Runs in this order:

    1. Apply ``renames``: any prompt with category=old gets category=new.
       This preserves references for labels the admin renamed in-place.
    2. Compute the set of *removed* labels (in old_taxonomy but not in
       new_taxonomy and not consumed by a rename). Set matching prompts'
       category to NULL.
    3. Validate the new taxonomy — no empty strings, no duplicates.
    """
    if new_taxonomy is not None:
        if any(not (name and name.strip()) for name in new_taxonomy):
            raise HTTPException(400, "category names must be non-empty")
        if len(set(new_taxonomy)) != len(new_taxonomy):
            raise HTTPException(400, "category names must be unique")
    renames = renames or {}
    for old_name, new_name in renames.items():
        if not old_name or not new_name:
            raise HTTPException(400, "rename mapping requires non-empty names")
        if old_name == new_name:
            continue
        db.execute(
            update(ProjectPrompt)
            .where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.category == old_name,
            )
            .values(category=new_name)
        )

    if new_taxonomy is not None and old_taxonomy is not None:
        renamed_to = set(renames.values())
        removed = [
            name
            for name in old_taxonomy
            if name not in new_taxonomy and name not in renamed_to
        ]
        if removed:
            db.execute(
                update(ProjectPrompt)
                .where(
                    ProjectPrompt.project_id == project_id,
                    ProjectPrompt.category.in_(removed),
                )
                .values(category=None)
            )


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = _get_project(db, project_id)
    # Lifecycle rule (post 20260908): business fields on a PENDING or
    # REJECTED project must go through the wizard flow (draft / approve /
    # reject endpoints). Reject anything other than ``description`` so a
    # stale editor can't silently change the wizard payload without the
    # review metadata catching up. ACTIVE / DISABLED rows are fully
    # editable as before.
    if p.status in (ProjectStatus.PENDING, ProjectStatus.REJECTED):
        editable_in_review = {"description", "status"}
        blocked = set(payload.model_dump(exclude_unset=True)) - editable_in_review
        if blocked:
            raise HTTPException(
                409,
                "use the wizard draft / approve / reject endpoints to edit "
                f"a {p.status.value} project; blocked fields: "
                f"{', '.join(sorted(blocked))}",
            )
    data = payload.model_dump(exclude_unset=True)
    renames = data.pop("category_renames", None)
    old_taxonomy = p.category_taxonomy
    for k, v in data.items():
        setattr(p, k, v)
    if "category_taxonomy" in data:
        _apply_category_taxonomy_change(
            db, project_id, old_taxonomy, p.category_taxonomy, renames
        )
    db.commit()
    db.refresh(p)
    # status ↔ schedule_active: when the project flips active/disabled the
    # APScheduler job set must mirror the change immediately, not on next
    # server boot.
    if "status" in data:
        if (scheduler := getattr(request.app.state, "scheduler", None)):
            reload_jobs(scheduler)
    return _to_out(p, prompts_count=_prompts_count_for(db, [p.id]).get(p.id, 0))


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Soft delete (spec §API). Disabling also stops the schedule, per the
    spec's boundary rule "项目被软删除时调度应停用" — leaving
    ``schedule_enabled`` set would keep the APScheduler job alive."""
    p = _get_project(db, project_id)
    p.status = ProjectStatus.DISABLED
    p.schedule_enabled = False
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# 4-tab config (whole-array replace)
# --------------------------------------------------------------------------


def _replace(db: Session, model, project_id: int, rows: list[dict]) -> None:
    db.query(model).filter(model.project_id == project_id).delete()
    for i, row in enumerate(rows):
        db.add(model(project_id=project_id, sort=i, **row))
    db.commit()


@router.put("/projects/{project_id}/prompts")
def put_prompts(
    project_id: int,
    payload: PromptsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    project = _get_project(db, project_id)
    taxonomy = project.category_taxonomy
    # Categories not in the project's taxonomy are silently dropped to NULL.
    # This protects the admin from 400'ing an entire save because a few
    # prompts still carry labels from a previous taxonomy (the legacy data
    # shipped before this column existed). The frontend's "为问题分配分类"
    # card already surfaces those rows with their legacy value visible, so
    # the admin can choose to re-assign them in the next round of edits.
    rows: list[dict] = []
    dropped: list[str] = []
    if taxonomy:
        allowed = set(taxonomy) | {None}
        for item in payload.prompts:
            cat = item.category
            if cat not in allowed:
                dropped.append(cat)
                cat = None
            rows.append(
                {"prompt": item.prompt, "category": cat, "status": item.status}
            )
    else:
        rows = [
            {"prompt": item.prompt, "category": item.category, "status": item.status}
            for item in payload.prompts
        ]
    _replace(db, ProjectPrompt, project_id, rows)
    return {"ok": True, "count": len(rows), "dropped_categories": dropped}


@router.put("/projects/{project_id}/keywords")
def put_keywords(
    project_id: int,
    payload: KeywordsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    _replace(db, ProjectKeyword, project_id, [{"keyword": k} for k in payload.keywords])
    return {"ok": True, "count": len(payload.keywords)}


@router.put("/projects/{project_id}/platforms")
def put_platforms(
    project_id: int,
    payload: PlatformsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    # Scheduler reads ``platform_code`` verbatim. Web rows fall back to
    # ``platform``; mobile rows are expected to carry the mapped variant
    # (e.g. ``baidu_mobile``) which the wizard's monitor step supplies.
    # The endpoint's callers are the 4-tab config panel (web only) and
    # the wizard (which writes via the pending-projects API), so the
    # fallback covers the legacy case without forcing every caller to
    # know about the column.
    rows = []
    for p in payload.platforms:
        d = p.model_dump()
        if not d.get("platform_code"):
            d["platform_code"] = d["platform"]
        rows.append(d)
    _replace(db, ProjectPlatform, project_id, rows)
    return {"ok": True, "count": len(payload.platforms)}


# --------------------------------------------------------------------------
# Embedded schedule
# --------------------------------------------------------------------------


def _schedule_out(p: Project, db: Session) -> ScheduleOut:
    last = db.scalars(
        select(ScheduleRun)
        .where(ScheduleRun.project_id == p.id)
        .order_by(ScheduleRun.id.desc())
        .limit(1)
    ).first()
    return ScheduleOut(
        project_id=p.id,
        schedule_enabled=p.schedule_enabled,
        monitor_schedule=p.monitor_schedule or {},
        next_run_at=_next_run(p),
        last_run=RunSummary.model_validate(last) if last else None,
    )


@router.get("/projects/{project_id}/schedule", response_model=ScheduleOut)
def get_schedule(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    return _schedule_out(project, db)


@router.put("/projects/{project_id}/schedule", response_model=ScheduleOut)
def put_schedule(
    project_id: int,
    payload: ScheduleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = _get_project(db, project_id)
    _apply_schedule(
        p,
        enabled=payload.schedule_enabled,
        monitor_schedule=payload.monitor_schedule,
    )
    db.commit()
    db.refresh(p)
    # monitor_schedule / schedule_enabled changed → APScheduler's in-memory
    # job set is stale (jobs were registered once at lifespan startup).
    # Without this reload, new weekdays won't fire until the next
    # server restart.
    if (scheduler := getattr(request.app.state, "scheduler", None)):
        reload_jobs(scheduler)
    return _schedule_out(p, db)


@router.delete("/projects/{project_id}/schedule", response_model=ScheduleOut)
def delete_schedule(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Reset to the no-schedule state; run history is kept."""
    p = _get_project(db, project_id)
    p.monitor_schedule = None
    p.schedule_enabled = False
    db.commit()
    db.refresh(p)
    if (scheduler := getattr(request.app.state, "scheduler", None)):
        reload_jobs(scheduler)
    return _schedule_out(p, db)


@router.put("/projects/{project_id}/schedule/status", response_model=ScheduleOut)
def put_schedule_status(
    project_id: int,
    payload: ScheduleStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Toggle only ``schedule_enabled``; freq/days are preserved across a disable."""
    p = _get_project(db, project_id)
    enabled = payload.status == "enabled"
    if enabled and not _has_any_days(p.monitor_schedule):
        raise HTTPException(400, "请先在「编辑监控项目」里配置每周监控日期,再启用调度")
    p.schedule_enabled = enabled
    db.commit()
    db.refresh(p)
    if (scheduler := getattr(request.app.state, "scheduler", None)):
        reload_jobs(scheduler)
    return _schedule_out(p, db)


@router.post("/projects/{project_id}/schedule/trigger", response_model=TriggerOut)
def trigger_schedule(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    """Manually queue one or two runs and kick off the submissions.

    Split rule: when the project carries both ``thinking_mode=False``
    and ``thinking_mode=True`` platform rows, the trigger creates two
    ``ScheduleRun`` rows (``mode="fast"`` + ``mode="think"``) and fires
    two background tasks. Each run's ``run_project_async`` then drops
    the wrong half of the platforms inside ``run_project``'s existing
    mode filter — same behaviour as the cron jobs in
    :mod:`app.services.scheduler_runtime`, so manual + cron stay
    consistent.

    Single-run path (only fast or only think): one ``ScheduleRun`` with
    ``mode=""`` (no filter), matching the pre-split behaviour. We don't
    pre-tag with the active mode because there's no second run to pair
    it with and the test fixture (``deepseek`` only) relies on this.

    The ``cooldown_key`` unique index is what enforces the 5-minute
    window — we let each INSERT fail and translate the conflict into
    ``skipped`` for that run rather than pre-checking, so concurrent
    triggers can't both pass. ``cooldown_key`` is mode-aware, so the
    fast and think keys don't collide with each other and a cron fire
    at the same minute still dedupes against the matching manual run.
    """
    p = _get_project(db, project_id)
    if not db.scalar(
        select(func.count())
        .select_from(ProjectPrompt)
        .where(ProjectPrompt.project_id == project_id)
    ):
        raise HTTPException(400, "project has no prompts configured")

    has_fast = bool(
        db.scalar(
            select(func.count())
            .select_from(ProjectPlatform)
            .where(
                ProjectPlatform.project_id == project_id,
                ProjectPlatform.thinking_mode.is_(False),
            )
        )
    )
    has_think = bool(
        db.scalar(
            select(func.count())
            .select_from(ProjectPlatform)
            .where(
                ProjectPlatform.project_id == project_id,
                ProjectPlatform.thinking_mode.is_(True),
            )
        )
    )

    now = now_local()

    if has_fast and has_think:
        fast_id, fast_status = _insert_schedule_run(
            db, project_id, slot_index=0, trigger_type=RunTrigger.MANUAL,
            mode="fast", now=now,
        )
        think_id, think_status = _insert_schedule_run(
            db, project_id, slot_index=0, trigger_type=RunTrigger.MANUAL,
            mode="think", now=now,
        )
        if fast_status == "queued":
            background_tasks.add_task(
                run_project_async, project_id, 0, RunTrigger.MANUAL, "fast",
                run_id=fast_id,
            )
        if think_status == "queued":
            background_tasks.add_task(
                run_project_async, project_id, 0, RunTrigger.MANUAL, "think",
                run_id=think_id,
            )
        return TriggerOut(
            run_id=fast_id,
            think_run_id=think_id,
            status="queued" if "queued" in (fast_status, think_status) else "skipped",
        )

    # 单模式(只 fast / 只 think)走老路径,``mode=""`` 让 ``run_project``
    # 不过滤平台行,保持拆分前的批量行为。
    run_id, status = _insert_schedule_run(
        db, project_id, slot_index=0, trigger_type=RunTrigger.MANUAL,
        mode="", now=now,
    )
    if status == "queued":
        background_tasks.add_task(
            run_project_async, project_id, 0, RunTrigger.MANUAL, "",
            run_id=run_id,
        )
    return TriggerOut(run_id=run_id, status=status)


def _insert_schedule_run(
    db: Session,
    project_id: int,
    *,
    slot_index: int,
    trigger_type: RunTrigger,
    mode: str,
    now: datetime,
) -> tuple[int, Literal["queued", "skipped"]]:
    """Insert one ``ScheduleRun`` and return ``(run_id, status)``.

    ``mode`` flows into ``cooldown_key`` so fast / think / mixed triggers
    each get their own 5-minute bucket. On cooldown conflict we roll back
    and surface the existing run's id with status ``"skipped"``; callers
    inspect the status to decide whether to fire ``run_project_async``.
    """
    key = cooldown_key(project_id, slot_index, now, mode=mode)
    run = ScheduleRun(
        project_id=project_id,
        slot_index=slot_index,
        trigger_type=trigger_type,
        mode=mode,
        triggered_at=now,
        status=RunStatus.QUEUED,
        cooldown_key=key,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ScheduleRun).where(ScheduleRun.cooldown_key == key))
        if existing is None:
            raise HTTPException(500, "cooldown conflict")
        return (existing.id, "skipped")
    db.refresh(run)
    return (run.id, "queued")


# --------------------------------------------------------------------------
# Runs + tasks
# --------------------------------------------------------------------------


def _subtask_counts_for_runs(
    db: Session, run_ids: list[int]
) -> dict[int, dict[str, int]]:
    """Aggregate per-run subtask status counts.

    Joins ``Task`` (filtered by ``schedule_run_id``) to its ``Subtask`` rows and
    bins them by status. Runs that have no Task yet (e.g. a queued manual
    trigger that hasn't submitted) are absent from the result; callers fall
    back to zero counts in that case.
    """
    if not run_ids:
        return {}
    stmt = (
        select(
            Task.schedule_run_id,
            Subtask.status,
            func.count(Subtask.subtask_id),
        )
        .join(Subtask, Subtask.task_id == Task.task_id)
        .where(Task.schedule_run_id.in_(run_ids))
        .group_by(Task.schedule_run_id, Subtask.status)
    )
    out: dict[int, dict[str, int]] = {}
    for run_id, status, n in db.execute(stmt).all():
        bucket = out.setdefault(
            run_id,
            {"success_count": 0, "failed_count": 0, "partial_count": 0, "total_count": 0},
        )
        bucket["total_count"] += n
        if status in ("success", "completed"):
            bucket["success_count"] += n
        elif status == "failed":
            bucket["failed_count"] += n
        elif status == "partial_completed":
            bucket["partial_count"] += n
    return out


def _run_with_counts(r: ScheduleRun, counts: dict[str, int]) -> ScheduleRunOut:
    payload = {
        "id": r.id,
        "project_id": r.project_id,
        "slot_index": r.slot_index,
        "trigger_type": r.trigger_type,
        "status": r.status,
        "triggered_at": r.triggered_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "task_id": r.task_id,
        "error_message": r.error_message,
        **counts,
    }
    return ScheduleRunOut.model_validate(payload)


@router.get("/projects/{project_id}/runs", response_model=ScheduleRunListOut)
def list_runs(
    project_id: int,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    page, size = _paginate(page, size)
    stmt = select(ScheduleRun).where(ScheduleRun.project_id == project_id)
    if status:
        stmt = stmt.where(ScheduleRun.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(ScheduleRun.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    counts_map = _subtask_counts_for_runs(db, [r.id for r in items])
    return ScheduleRunListOut(
        items=[_run_with_counts(r, counts_map.get(r.id, {})) for r in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/projects/{project_id}/tasks", response_model=ProjectTaskListOut)
def list_project_tasks(
    project_id: int,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    page, size = _paginate(page, size)
    stmt = select(Task).where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Task.task_id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ProjectTaskListOut(
        items=[ProjectTaskOut.model_validate(t) for t in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/projects/{project_id}/tasks/{task_id}/subtasks", response_model=SubtaskListOut)
def list_task_subtasks(
    project_id: int,
    task_id: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Return the Subtask rows attached to a single ``geo_tasks`` row.

    Used by the per-project task-detail modal so an operator can see
    which sub-task failed and why without leaving the project list.
    The parent Task is scoped by ``project_id`` so callers can't peek
    at tasks belonging to a different project by guessing IDs.
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="task not found")
    rows = db.scalars(
        select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.subtask_id)
    ).all()
    return SubtaskListOut(
        items=[SubtaskOut.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get(
    "/projects/{project_id}/prompts/{prompt_id}/answers",
    response_model=PromptAnswerListOut,
)
def list_prompt_answers(
    project_id: int,
    prompt_id: int,
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    platform: str | None = None,
    platforms: list[str] | None = Query(default=None),
    preview_chars: int = 200,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Return every ``geo_subtasks`` row that was generated for this prompt.

    Drives the 问题提及分析 → 模型对比 → 查看原文 modal: when an operator
    wants to read what every AI actually said, we list all subtasks whose
    ``prompt`` text matches the project's ``ProjectPrompt.prompt`` (the
    Subtask table does not store ``prompt_id``; it stores the verbatim text
    that the user submitted). Window filtering rides on the parent task's
    ``created_local_at`` — same semantics as the overview endpoint — so
    ``start``/``end`` win over ``days``.

    ``platform`` narrows the result to a single AI model — legacy single-
    model filter, kept for the QuestionTab 查看原文 modal. ``platforms``
    accepts a list of compound keys (``<base>__<delivery>__<thinking>``)
    from the GlobalToolbar 「模型」dropdown, applied via the same
    ``_expand_platform_keys`` / compound-key post-filter pipeline as
    source-preferences so the 答案质量分析 page sees exactly the same
    slice the user selected. The two filters compose: ``platform`` is
    applied as a strict equality, then ``platforms`` narrows further if
    provided.

    The list intentionally omits the heavy fields (full ``answer_content``
    text, ``page_screenshot`` base64, all structured-payload JSON). Each
    row carries a truncated ``answer_content`` slice of ``preview_chars``
    plus the original ``answer_length`` and a ``truncated`` flag, so the
    modal can render the per-row preview card and only request the full
    payload (via :func:`get_subtask_detail`) when the operator clicks
    展开全部. That keeps the list response small regardless of how long
    each AI's answer is — a 60-row month window with megabyte-scale
    answers still lands well under 100 KB.
    """
    from datetime import timedelta

    from app.models.common import now_local

    if preview_chars < 50 or preview_chars > 2000:
        raise HTTPException(400, "preview_chars must be between 50 and 2000")

    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    prompt = db.get(ProjectPrompt, prompt_id)
    if prompt is None or prompt.project_id != project_id:
        raise HTTPException(404, "prompt not found in this project")
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start, win_end = today - timedelta(days=window_days - 1), today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    base_stmt = (
        select(
            Subtask.subtask_id,
            Subtask.task_id,
            Subtask.platform,
            Subtask.mode,
            Subtask.status,
            Subtask.answer_content,
            Subtask.error_message,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Subtask.prompt == prompt.prompt,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    if platform is not None:
        base_stmt = base_stmt.where(Subtask.platform == platform)
    # Toolbar compound-key filter: SQL narrows by ``platform_code`` so we
    # don't pull every subtask just to drop most of them in Python. The
    # compound-key post-filter below handles the (base, delivery, thinking)
    # granularity — e.g. user勾了 web+fast 但同 base 也有 web+think 行
    # 时,后者 SQL 仍会被拉进来,要在 Python 里再过一刀。
    selected_compound_keys: set[str] | None = None
    if platforms is not None:
        platform_codes = _expand_platform_keys(platforms)
        if platform_codes:
            base_stmt = base_stmt.where(Subtask.platform.in_(platform_codes))
        # Empty list = "filter to nothing" (no platform selected in toolbar);
        # short-circuit so the caller doesn't waste a round-trip.
        elif not platforms:
            return PromptAnswerListOut(items=[], total=0)
        selected_compound_keys = set(platforms)
    # Sort key + id first so MySQL can sort on a tiny row, then re-fetch
    # the rest by id. Selecting every JSON / page_screenshot /
    # answer_content straight into the sort buffer blew past the server's
    # ``sort_buffer_size`` (256KB default) on a single prompt that has a
    # few long answers in the window.
    sort_rows = db.execute(
        base_stmt.with_only_columns(
            Subtask.subtask_id,
            Subtask.task_id,
            Subtask.platform,
            Subtask.mode,
            Task.created_local_at,
        ).order_by(Task.created_local_at.desc(), Subtask.subtask_id)
    ).all()
    if selected_compound_keys is not None:
        sort_rows = [
            r for r in sort_rows
            if _compound_platform(r.platform, r.mode) in selected_compound_keys
        ]
    if not sort_rows:
        return PromptAnswerListOut(items=[], total=0)
    sub_ids = [r.subtask_id for r in sort_rows]
    created_at_by_sub = {r.subtask_id: r.created_local_at for r in sort_rows}
    # Second pass: only the columns the list actually needs. We pull the
    # full ``answer_content`` here so we can slice it in Python; the JSON
    # columns and ``page_screenshot`` are deliberately left for the detail
    # endpoint.
    light_rows = db.execute(
        select(
            Subtask.subtask_id,
            Subtask.task_id,
            Subtask.platform,
            Subtask.mode,
            Subtask.status,
            Subtask.answer_content,
            Subtask.error_message,
            # ``raw_result_json.allRankings`` 是本回答里的全品牌排名列表 —— 数据
            # 真源在 subtask 行上(``BrandMention.raw_extraction`` 只存派生 payload,
            # 不带 allRankings),所以 list 端点一并带回。前端卡片底部按顺序缩略展示,
            # hover Tooltip 看完整列表。
            Subtask.raw_result_json,
        ).where(Subtask.subtask_id.in_(sub_ids))
    ).all()
    light_by_sub = {r.subtask_id: r for r in light_rows}
    # Pull the project's own-brand mention (is_self=true) for every subtask
    # in the window. ``rank_position`` was written by ``_find_competitor_rank``
    # (extraction.py) from LLM ``raw.allRankings``; ``sentiment`` is the
    # LLM-emitted polarity. One SQL roundtrip keeps the list endpoint cheap.
    self_mentions = db.execute(
        select(
            BrandMention.subtask_id,
            BrandMention.rank_position,
            BrandMention.sentiment,
        ).where(
            BrandMention.subtask_id.in_(sub_ids),
            BrandMention.is_self.is_(True),
        )
    ).all()
    self_by_sub: dict[str, object] = {
        m.subtask_id: m for m in self_mentions
    }
    items = [
        _build_preview_answer(
            sid=sid,
            row=light_by_sub[sid],
            created_local_at=created_at_by_sub[sid],
            preview_chars=preview_chars,
            self_rank=getattr(self_by_sub.get(sid), "rank_position", None),
            self_sentiment=getattr(self_by_sub.get(sid), "sentiment", None),
            all_rankings=_extract_all_rankings(light_by_sub[sid].raw_result_json),
        )
        for sid in sub_ids
    ]
    return PromptAnswerListOut(items=items, total=len(items))


def _build_preview_answer(
    *,
    sid: str,
    row,
    created_local_at,
    preview_chars: int,
    self_rank: int | None = None,
    self_sentiment: str | None = None,
    all_rankings: list[dict] | None = None,
) -> "PromptAnswerOut":
    """Slice ``answer_content`` to ``preview_chars`` and emit a list-row
    schema. We keep the original length in ``answer_length`` so the UI
    can render the 展开全部 (N 字) affordance without a second fetch.
    ``self_rank`` / ``self_sentiment`` are pulled from the project's own-
    brand mention row for this subtask (see list_prompt_answers above).
    ``all_rankings`` comes straight from ``Subtask.raw_result_json`` so
    the UI can show the full brand ranking list per answer.
    """
    full_text = row.answer_content or ""
    length = len(full_text)
    if length <= preview_chars:
        preview = full_text
        truncated = False
    else:
        preview = full_text[:preview_chars]
        truncated = True
    return PromptAnswerOut(
        subtask_id=sid,
        task_id=row.task_id,
        platform=row.platform,
        mode=row.mode,
        status=row.status,
        answer_content=preview,
        answer_length=length,
        truncated=truncated,
        error_message=row.error_message,
        created_local_at=created_local_at,
        self_rank=self_rank,
        self_sentiment=self_sentiment,
        all_rankings=all_rankings,
    )


def _extract_all_rankings(raw_result_json: object) -> list[dict] | None:
    """Return ``raw_result_json.allRankings`` if it's a list of {name, rank}
    dicts; otherwise ``None``.

    ``Subtask.raw_result_json`` holds the verbatim LLM extraction payload;
    the platform-facing schema isn't 100% consistent (some platforms wrap
    ``allRankings`` differently, some omit it for failed runs), so we
    defensively normalise here. We only keep entries that look like
    ``{"name": str, "rank": int > 0}`` — anything else is silently dropped
    so the UI never renders junk like ``None`` or non-dict rows.
    """
    if not isinstance(raw_result_json, dict):
        return None
    rows = raw_result_json.get("allRankings")
    if not isinstance(rows, list):
        return None
    out: list[dict] = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        rank = entry.get("rank")
        if isinstance(name, str) and name.strip() and isinstance(rank, int) and rank > 0:
            out.append({"name": name.strip(), "rank": rank})
    return out or None


@router.get(
    "/subtasks/{subtask_id}",
    response_model=PromptAnswerDetailOut,
)
def get_subtask_detail(
    subtask_id: str,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Single-subtask full payload, fetched on demand from the
    查看原文 → 展开全部 modal. The list endpoint deliberately trims the
    answer text and drops the structured payload; this route restores
    them in one round-trip. Tenant scoping rides on the subtask's parent
    Task → Project chain so a customer_admin can't peek at other
    customers' answers by guessing subtask IDs.
    """
    sub = db.get(Subtask, subtask_id)
    if sub is None:
        raise HTTPException(404, "subtask not found")
    task = db.get(Task, sub.task_id)
    if task is None:
        raise HTTPException(404, "parent task not found")
    _assert_customer_access(user, task.project)
    full_text = sub.answer_content or ""
    return PromptAnswerDetailOut(
        subtask_id=sub.subtask_id,
        task_id=sub.task_id,
        platform=sub.platform,
        mode=sub.mode,
        status=sub.status,
        answer_content=full_text,
        answer_length=len(full_text),
        truncated=False,
        page_screenshot=sub.page_screenshot,
        error_message=sub.error_message,
        created_local_at=task.created_local_at,
        reference_list=sub.reference_list_json,
        citation_list=sub.citation_list_json,
        reasoning_process=sub.reasoning_process_json,
        media_content=sub.media_content_json,
        recommended_questions=sub.recommended_questions_json,
    )


# --------------------------------------------------------------------------
# Competitors (user-defined seed list per project)
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/competitors", response_model=CompetitorListOut)
def list_competitors(
    project_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    items = db.scalars(
        select(ProjectCompetitor)
        .where(ProjectCompetitor.project_id == project_id)
        .order_by(ProjectCompetitor.sort, ProjectCompetitor.id)
    ).all()
    return CompetitorListOut(
        items=[CompetitorOut.model_validate(c) for c in items],
        total=len(items),
    )


@router.post(
    "/projects/{project_id}/competitors",
    response_model=CompetitorOut,
    status_code=201,
)
def create_competitor(
    project_id: int,
    payload: CompetitorIn,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    _get_project(db, project_id)
    next_sort = (
        db.scalar(
            select(func.coalesce(func.max(ProjectCompetitor.sort), -1)).where(
                ProjectCompetitor.project_id == project_id
            )
        )
        or -1
    ) + 1
    c = ProjectCompetitor(
        project_id=project_id,
        name=payload.name.strip(),
        note=payload.note,
        aliases=payload.aliases,
        origin=payload.origin,
        status=payload.status,
        sort=next_sort,
    )
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        # ``uq_project_competitors_project_name`` — name already in this project.
        db.rollback()
        raise HTTPException(400, "competitor name already exists in this project")
    db.refresh(c)
    return CompetitorOut.model_validate(c)


@router.put(
    "/projects/{project_id}/competitors/{competitor_id}",
    response_model=CompetitorOut,
)
def update_competitor(
    project_id: int,
    competitor_id: int,
    payload: CompetitorIn,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(ProjectCompetitor, competitor_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "competitor not found")
    c.name = payload.name.strip()
    c.note = payload.note
    c.aliases = payload.aliases
    c.origin = payload.origin
    c.status = payload.status
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "competitor name already exists in this project")
    db.refresh(c)
    return CompetitorOut.model_validate(c)


@router.delete("/projects/{project_id}/competitors/{competitor_id}")
def delete_competitor(
    project_id: int,
    competitor_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(ProjectCompetitor, competitor_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "competitor not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Brand mentions (drives overview / per-question / per-competitor pages)
# --------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/brand-mentions",
    response_model=BrandMentionListOut,
)
def list_brand_mentions(
    project_id: int,
    page: int = 1,
    size: int = 50,
    is_self: bool | None = None,
    brand: str | None = None,
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """List extraction rows for one project, newest first.

    ``is_self=true`` filters to the monitored brand (default for the
    overview tab). ``brand`` narrows to one specific brand
    (default for the competitor-analysis tab).

    Window filtering rides on ``BrandMention.created_at`` — same as
    :func:`list_prompt_answers`, ``start``/``end`` win over ``days`` and
    are inclusive on both ends. Drives the 问题提及分析 per-question
    delta row (current window vs the immediately preceding window of
    the same length).
    """
    page, size = _paginate(page, size)
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=window_days - 1)
        win_end = today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)
    stmt = select(BrandMention).where(
        BrandMention.project_id == project_id,
        BrandMention.created_at >= win_start_dt,
        BrandMention.created_at <= win_end_dt,
    )
    if is_self is not None:
        stmt = stmt.where(BrandMention.is_self == is_self)
    if brand:
        stmt = stmt.where(BrandMention.brand == brand)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(BrandMention.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return BrandMentionListOut(
        items=[BrandMentionOut.model_validate(m) for m in items],
        total=total,
    )


def _compute_question_summary(
    db: Session,
    project: Project,
    *,
    start: datetime,
    end: datetime,
    selected_triples: set[tuple[str, str, bool]] | None = None,
) -> QuestionSummaryOut:
    """按项目当前窗口聚合每个 prompt 的 KPI + 项目级 category summary。

    单次 SELECT 取 per-(prompt, category, status, platform, delivery,
    thinking, rank) 行,在 Python 中派生 per-prompt 和 per-category 两套
    聚合,严格遵守 spec §4.1「从同一统计结果汇总,不再额外扫描
    geo_brand_mentions」。SQL 预算 = 1 条核心 SELECT。

    ``selected_triples`` 走 Overview 同款口径 —— toolbar 切档后只算
    勾选 (platform_code, delivery_mode, is_thinking) 三元组对应的行;
    缺省 = None 表示「全选」,空集合 = 视为 0 行(不留 N+1)。

    Coverage 严格按 triple 匹配:ProjectPlatform 配置的 (platform_code,
    delivery, thinking) 三元组集合是分母,窗口内 mention 行命中这些
    三元组的去重数是分子 —— 与 Overview / 工具栏「N 个模型档位」
    一致,不再让 mention platform 集合去重与 ProjectPlatform 行数错位。
    """
    configured_triples = project_platform_triples(db, project.id)

    stmt = (
        select(
            ProjectPrompt.id,
            BrandMention.prompt,
            ProjectPrompt.category,
            ProjectPrompt.status,
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            BrandMention.rank_position,
        )
        .join(ProjectPrompt, ProjectPrompt.prompt == BrandMention.prompt)
        .where(
            BrandMention.project_id == project.id,
            ProjectPrompt.project_id == project.id,
            BrandMention.is_self.is_(True),
            BrandMention.created_at >= start,
            BrandMention.created_at < end,
        )
    )
    if selected_triples is not None:
        if not selected_triples:
            # 「全部未选」直接返回空列表,避免 SQL IN () 语法错。
            return QuestionSummaryOut(
                project_id=project.id,
                start=start,
                end=end,
                items=[],
                category_summary=[],
            )
        stmt = stmt.where(
            tuple_(
                BrandMention.platform,
                BrandMention.delivery_mode,
                BrandMention.thinking_mode,
            ).in_(selected_triples)
        )
    rows = db.execute(stmt).all()

    per_prompt: dict[int, dict] = {}
    cat_prompts: dict[str | None, set[int]] = defaultdict(set)
    cat_matched: dict[str | None, int] = defaultdict(int)
    cat_total: dict[str | None, int] = defaultdict(int)
    cat_top1: dict[str | None, int] = defaultdict(int)
    cat_top3: dict[str | None, int] = defaultdict(int)

    for r in rows:
        bucket = per_prompt.setdefault(
            int(r.id),
            {
                "prompt": r.prompt or "",
                "category": r.category,
                "status": r.status or "active",
                "total": 0,
                "matched": 0,
                "rank_sum": 0,
                "rank_count": 0,
                "top1": 0,
                "top3": 0,
                "covered_triples": set(),
            },
        )
        bucket["total"] += 1
        triple = (r.platform, r.delivery_mode, bool(r.thinking_mode))
        if triple in configured_triples:
            bucket["covered_triples"].add(triple)
        if r.rank_position is not None:
            bucket["matched"] += 1
            bucket["rank_sum"] += r.rank_position
            bucket["rank_count"] += 1
            if r.rank_position == 1:
                bucket["top1"] += 1
            if r.rank_position <= 3:
                bucket["top3"] += 1

        cat = r.category
        cat_prompts[cat].add(int(r.id))
        cat_total[cat] += 1
        if r.rank_position is not None:
            cat_matched[cat] += 1
        if r.rank_position == 1:
            cat_top1[cat] += 1
        if r.rank_position is not None and r.rank_position <= 3:
            cat_top3[cat] += 1

    items: list[QuestionSummaryItem] = []
    for prompt_id, b in sorted(per_prompt.items()):
        total = b["total"]
        matched = b["matched"]
        items.append(
            QuestionSummaryItem(
                prompt_id=prompt_id,
                prompt=b["prompt"],
                category=b["category"],
                status=b["status"],
                total=total,
                matched=matched,
                mention_rate=(matched / total) if total else 0.0,
                top1_rate=(b["top1"] / total) if total else 0.0,
                top3_rate=(b["top3"] / total) if total else 0.0,
                rank_avg=(b["rank_sum"] / b["rank_count"]) if b["rank_count"] else None,
                coverage=len(b["covered_triples"]),
            )
        )

    category_summary: list[CategoryStat] = []
    for cat, prompt_ids in cat_prompts.items():
        total = cat_total[cat]
        category_summary.append(
            CategoryStat(
                category=cat,
                prompt_count=len(prompt_ids),
                mention_rate=(cat_matched[cat] / total) if total else 0.0,
                top1_rate=(cat_top1[cat] / total) if total else 0.0,
                top3_rate=(cat_top3[cat] / total) if total else 0.0,
            )
        )

    return QuestionSummaryOut(
        project_id=project.id,
        start=start,
        end=end,
        items=items,
        category_summary=category_summary,
    )


@router.get("/projects/{project_id}/questions/summary", response_model=QuestionSummaryOut)
def questions_summary(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    platforms: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
) -> QuestionSummaryOut:
    """摘要:左侧列表 + 项目级 category 汇总,只算当前窗口。

    与旧 `/questions/analytics` 的差别:不返回平台明细、prev/long_prev、
    摘录、竞品矩阵;由后续 tasks 的 product-analytics / competitor-analytics
    端点按需加载。

    ``platforms`` 是 compound key 子集(``${code}__${delivery}__${thinking}``),
    缺省 = 走全选;非法 token 静默忽略,与 Overview 口径一致。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    win_start_dt, win_end_dt = _resolve_window_inline(days, start, end)
    selected_triples = parse_platforms_param(platforms)

    return _compute_question_summary(
        db,
        project,
        start=win_start_dt,
        end=win_end_dt,
        selected_triples=selected_triples,
    )


def _get_project_prompt_or_404(
    db: Session, *, project_id: int, prompt_id: int
) -> ProjectPrompt:
    prompt = db.get(ProjectPrompt, prompt_id)
    if prompt is None or prompt.project_id != project_id:
        raise HTTPException(404, "prompt not found in this project")
    return prompt


def _compute_question_product_analytics(
    db: Session,
    project: Project,
    prompt: ProjectPrompt,
    *,
    start: datetime,
    end: datetime,
    selected_triples: set[tuple[str, str, bool]] | None = None,
) -> QuestionProductAnalyticsOut:
    """单问题产品分析:per-triple 统计 + prev + long_prev + 摘录。

    SQL 预算 = 2 条核心 SELECT:
      1) stats:扫 long_prev → end 期间的 (platform, delivery, thinking,
         created_at, rank) 行,Python 按窗口分桶(current / prev /
         long_prev)。聚合 key 是 ``(platform_code, delivery_mode,
         is_thinking)`` triple(Overview 同款 compound key 拆分),不再是
         单 modelCode —— 模型对比表每个 ProjectPlatform row 各占一行。
      2) excerpts:每个 triple 取窗口内最新 Subtask + 对应 rank;join
         Task 用 project_id 防御(同一 prompt 文本可能跨项目存在)。

    与 ``questions_status_changes`` / ``questions_competitor_analytics`` 的差别:
    本端点不扫全项目竞品矩阵,只看指定 prompt。

    ``selected_triples`` 是 GlobalToolbar 切档:None = 全选;空 set = 视为
    「全部未选」,直接返回空响应,避免 SQL IN () 语法错。
    """
    if selected_triples is not None and not selected_triples:
        return QuestionProductAnalyticsOut(
            project_id=project.id,
            prompt_id=prompt.id,
            start=start,
            end=end,
            platforms=[],
            prev=None,
            long_prev=None,
            excerpts={},
        )

    length = (end.date() - start.date()).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    long_prev_end = prev_start - timedelta(days=1)
    long_prev_start = long_prev_end - timedelta(days=length - 1)
    prev_end_dt = datetime.combine(prev_end.date(), time.max)
    prev_start_dt = datetime.combine(prev_start.date(), time.min)
    long_prev_end_dt = datetime.combine(long_prev_end.date(), time.max)
    long_prev_start_dt = datetime.combine(long_prev_start.date(), time.min)

    stats_stmt = (
        select(
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            BrandMention.created_at,
            BrandMention.rank_position,
            BrandMention.sentiment,
            BrandMention.is_recommended,
        )
        .where(
            BrandMention.project_id == project.id,
            BrandMention.is_self.is_(True),
            BrandMention.prompt == prompt.prompt,
            BrandMention.created_at >= long_prev_start_dt,
            BrandMention.created_at < end,
        )
        .order_by(BrandMention.platform, BrandMention.created_at)
    )
    if selected_triples is not None:
        stats_stmt = stats_stmt.where(
            tuple_(
                BrandMention.platform,
                BrandMention.delivery_mode,
                BrandMention.thinking_mode,
            ).in_(selected_triples)
        )
    rows = db.execute(stats_stmt).all()

    by_window: dict[
        tuple[str, str, bool, str],
        list[tuple[datetime, int | None, str | None, bool | None]],
    ] = defaultdict(list)
    for r in rows:
        triple = (r.platform, r.delivery_mode, bool(r.thinking_mode))
        if r.created_at >= start:
            bucket = "current"
        elif r.created_at >= prev_start_dt:
            bucket = "prev"
        else:
            bucket = "long_prev"
        by_window[(*triple, bucket)].append(
            (r.created_at, r.rank_position, r.sentiment, bool(r.is_recommended))
        )

    def _agg(
        buckets: list[tuple[datetime, int | None, str | None, bool | None]],
    ) -> dict:
        total = len(buckets)
        ranks = [rk for _, rk, _, _ in buckets if rk is not None]
        matched = len(ranks)
        top1 = sum(1 for rk in ranks if rk == 1)
        top3 = sum(1 for rk in ranks if rk <= 3)
        # 情感倾向:仅算有 rank 的行(rank 缺失说明该行没被抽过 LLM,没
        # sentiment 标签);Molizhishu API 标签 positive=1.0 / neutral=0.5 /
        # negative=0.0,前端再翻译回「正面 / 中性 / 负面」。
        sent_scores = [
            {"positive": 1.0, "neutral": 0.5, "negative": 0.0}.get(s)
            for _, _, s, _ in buckets
            if s in ("positive", "neutral", "negative")
        ]
        avg_sentiment = (sum(sent_scores) / len(sent_scores)) if sent_scores else None
        # 推荐状态:只要至少 1 行 ``is_recommended`` 为真,该档位算「推荐」。
        recommend_yes = any(rec for _, _, _, rec in buckets if rec is True)
        return {
            "total": total,
            "matched": matched,
            "top1": top1,
            "top3": top3,
            "rank_avg": (sum(ranks) / len(ranks)) if ranks else None,
            "avg_sentiment": avg_sentiment,
            "recommend_yes": recommend_yes,
        }

    def _prev_stat_for(bucket: str) -> QuestionPrevStat | None:
        # Aggregate across ALL triples for that window so the prev
        # block is a project-level KPI, not per-platform.
        all_rows: list[tuple[datetime, int | None]] = []
        for key, items in by_window.items():
            if key[3] == bucket:
                all_rows.extend(items)
        agg = _agg(all_rows)
        if agg["total"] == 0:
            return None
        n = agg["total"]
        return QuestionPrevStat(
            total=n,
            matched=agg["matched"],
            top1_rate=(agg["top1"] / n) if n else 0.0,
            top3_rate=(agg["top3"] / n) if n else 0.0,
            mention_rate=(agg["matched"] / n) if n else 0.0,
            rank_avg=agg["rank_avg"],
        )

    # 模型对比表按 compound key 拆分:每个 (platform_code, delivery,
    # thinking) triple 一行,排序按 ProjectPlatform id 顺序,让卡片行序
    # 与 ProjectPlatform 配置保持一致。窗口里没数据的档位也占一行
    # (matched=0, total=0, best_rank=null),跟 ProjectPlatform 行对齐,
    # 避免「勾了 8 个 = 表 5 行」的口径错位。
    configured_triples = project_platform_triples(db, project.id)
    if selected_triples is not None:
        ordered_triples = sorted(
            selected_triples,
            key=lambda t: (
                t[1] == "mobile",
                bool(t[2]),
                t[0],
            ),
        )
    else:
        ordered_triples = sorted(
            configured_triples,
            key=lambda t: (
                t[1] == "mobile",
                bool(t[2]),
                t[0],
            ),
        )

    platforms_out: list[QuestionPlatformStat] = []
    for plat, delivery, is_thinking in ordered_triples:
        cur = by_window.get((plat, delivery, is_thinking, "current"), [])
        prev = by_window.get((plat, delivery, is_thinking, "prev"), [])
        cur_agg = _agg(cur)
        prev_agg = _agg(prev)
        # best_rank derived from current only
        cur_ranks = [rk for _, rk, _, _ in cur if rk is not None]
        best_rank = min(cur_ranks) if cur_ranks else None
        # avg_sentiment / recommend_yes 从 current 窗口聚合 — 模型对比表
        # 每行需要展示该档位的「情感倾向」与「推荐状态」,所以这里填上
        # current 的聚合值;没有匹配行时 avg_sentiment=None /
        # recommend_yes=False,前端会显示「—」与「未推荐」占位。
        platforms_out.append(
            QuestionPlatformStat(
                platform=compound_key(plat, delivery, is_thinking),
                delivery_mode=delivery,
                thinking_mode=is_thinking,
                matched=cur_agg["matched"],
                total=cur_agg["total"],
                best_rank=best_rank,
                avg_sentiment=cur_agg["avg_sentiment"],
                recommend_yes=cur_agg["recommend_yes"],
                brand=None,
                # 每档自己的 prev 窗口数据,让模型对比表可以展示该档位的
                # 环比 pill(横卡片保留项目级 prev)。prev_* 与 _agg 输出对
                # 齐,total=0 时全填 0 而不是 None,前端不再做 null 分支。
                prev_matched=prev_agg["matched"],
                prev_total=prev_agg["total"],
                prev_top1_rate=(prev_agg["top1"] / prev_agg["total"])
                if prev_agg["total"]
                else 0.0,
                prev_top3_rate=(prev_agg["top3"] / prev_agg["total"])
                if prev_agg["total"]
                else 0.0,
                prev_mention_rate=(prev_agg["matched"] / prev_agg["total"])
                if prev_agg["total"]
                else 0.0,
            )
        )

    prev_stat = _prev_stat_for("prev")
    long_prev_stat = _prev_stat_for("long_prev")

    # 摘录:窗口内每个 triple 取最新 subtask 的 answer_content。
    # 优先用 BrandMention 行的 delivery / thinking(因为 Subtask 没这两
    # 列);Subtask 行没匹配到 BrandMention 的孤儿,delivery / thinking 走
    # None fallback,仍能命中一个 compound key(以 Subtask.platform 为
    # base code,默认 web/fast)。LEFT JOIN to Task —— 生产数据总有匹配
    # Task 行,历史 fixture 走外连接兜底。
    excerpt_stmt = (
        select(
            Subtask.platform,
            Subtask.subtask_id,
            Subtask.answer_content,
            Subtask.updated_at,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            BrandMention.rank_position,
        )
        .outerjoin(Task, Task.task_id == Subtask.task_id)
        .outerjoin(
            BrandMention,
            and_(
                BrandMention.subtask_id == Subtask.subtask_id,
                BrandMention.is_self.is_(True),
                BrandMention.prompt == prompt.prompt,
            ),
        )
        .where(
            (Task.project_id.is_(None) | (Task.project_id == project.id)),
            Subtask.prompt == prompt.prompt,
            Subtask.updated_at >= start,
            Subtask.updated_at < end,
        )
        .order_by(Subtask.platform, Subtask.updated_at.desc())
    )
    excerpt_rows = db.execute(excerpt_stmt).all()

    latest_by_triple: dict[str, PlatformExcerpt] = {}
    for r in excerpt_rows:
        delivery = r.delivery_mode or "web"
        thinking = bool(r.thinking_mode)
        triple_key = compound_key(r.platform, delivery, thinking)
        # 若 toolbar 切档过滤,只保留被选中的档位摘录(保持分子 / 分母
        # 口径一致:工具栏勾了哪几条,右卡片就显示哪几条 excerpt)。
        if (
            selected_triples is not None
            and (r.platform, delivery, thinking) not in selected_triples
        ):
            continue
        if triple_key in latest_by_triple:
            continue
        text = r.answer_content or ""
        excerpt = text[:200]
        if not excerpt:
            continue
        latest_by_triple[triple_key] = PlatformExcerpt(
            excerpt=excerpt,
            rank=r.rank_position,
            run_id=r.subtask_id,
        )

    return QuestionProductAnalyticsOut(
        project_id=project.id,
        prompt_id=prompt.id,
        start=start,
        end=end,
        platforms=platforms_out,
        prev=prev_stat,
        long_prev=long_prev_stat,
        excerpts=latest_by_triple,
    )


@router.get(
    "/projects/{project_id}/questions/{prompt_id}/product-analytics",
    response_model=QuestionProductAnalyticsOut,
)
def questions_product_analytics(
    project_id: int,
    prompt_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    platforms: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
) -> QuestionProductAnalyticsOut:
    """单问题产品分析:platform 统计 + prev + long_prev + 6 平台摘录。

    与 summary 的差别:返回单问题而非整个项目;与 status-changes 的差别:不扫
    全项目竞品明细。spec §4.2 要求核心 SQL ≤ 3 条(不含鉴权与项目存在性查询)。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    prompt = _get_project_prompt_or_404(
        db, project_id=project.id, prompt_id=prompt_id
    )
    win_start_dt, win_end_dt = _resolve_window_inline(days, start, end)
    selected_triples = parse_platforms_param(platforms)

    return _compute_question_product_analytics(
        db,
        project,
        prompt,
        start=win_start_dt,
        end=win_end_dt,
        selected_triples=selected_triples,
    )


def _compute_question_competitor_analytics(
    db: Session,
    project: Project,
    prompt: ProjectPrompt,
    *,
    start: datetime,
    end: datetime,
    selected_triples: set[tuple[str, str, bool]] | None = None,
) -> QuestionCompetitorAnalyticsOut:
    """单问题竞品分析:按 brand × triple 聚合,SQL 预算 ≤ 2。

    与产品分析的差别:产品分析走 ``is_self=true`` + per-triple stats +
    prev/long_prev;这里按 brand × triple 聚合,既包括自身品牌也包括
    竞品,自身品牌始终排在最前,方便对比。只取当前窗口(竞品面板不显示
    prev delta,UI 在 OverviewTab 已经有 delta 行)。

    SQL 预算 = 2 条核心 SELECT:
      1) brand aggregation:扫 ``BrandMention``,在 Python 中按
         (is_self, brand, triple) 汇总 ranks。triple = (platform_code,
         delivery_mode, is_thinking),与产品分析同口径 —— 竞品矩阵的
         「各模型中的品牌位次」列展开到 compound key,不再合并 fast/think
         或 web/mobile。
      2) excerpts:每个 triple 取窗口内最新 Subtask + 对应
         (is_self=false) rank,join ``Task`` 用 project_id 防御
         (同一 prompt 文本可能跨项目存在)。

    ``selected_triples`` 跟产品分析同口径:None = 全选,空 set = 视为「全
    部未选」直接返回空响应,避免 SQL IN () 语法错。
    """
    if selected_triples is not None and not selected_triples:
        return QuestionCompetitorAnalyticsOut(
            project_id=project.id,
            prompt_id=prompt.id,
            start=start,
            end=end,
            brands=[],
            excerpts={},
        )

    agg_stmt = (
        select(
            BrandMention.is_self,
            BrandMention.brand,
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            BrandMention.rank_position,
        ).where(
            BrandMention.project_id == project.id,
            BrandMention.prompt == prompt.prompt,
            BrandMention.created_at >= start,
            BrandMention.created_at < end,
        )
    )
    if selected_triples is not None:
        agg_stmt = agg_stmt.where(
            tuple_(
                BrandMention.platform,
                BrandMention.delivery_mode,
                BrandMention.thinking_mode,
            ).in_(selected_triples)
        )
    rows = db.execute(agg_stmt).all()

    grouped: dict[
        tuple[bool, str, str, str, bool], list[int | None]
    ] = defaultdict(list)
    total_per_brand: dict[tuple[bool, str], int] = defaultdict(int)
    for r in rows:
        triple = (r.platform, r.delivery_mode, bool(r.thinking_mode))
        grouped[(r.is_self, r.brand, *triple)].append(r.rank_position)
        total_per_brand[(r.is_self, r.brand)] += 1

    by_brand: dict[
        tuple[bool, str], dict[str, list[int | None]]
    ] = defaultdict(dict)
    for (is_self, brand, plat, delivery, is_thinking), ranks in grouped.items():
        by_brand[(is_self, brand)][
            compound_key(plat, delivery, is_thinking)
        ] = ranks

    # Fixed palette for the competitor panel — same slot cycle as the
    # analytics endpoint's competitor matrix so the visual layout is
    # stable across windows. Self brand gets the reserved primary blue
    # so the operator can spot it instantly; competitors cycle the rest.
    _COMP_COLORS = ("#ff6b1a", "#52c41a", "#722ed1", "#13c2c2")
    _SELF_COLOR = "#1a55e8"

    brands_out: list[CompetitorBrandStat] = []
    # Self brand always wins the first slot; competitors follow by
    # total mentions desc (ties broken by brand for stable
    # order across windows).
    self_keys = [k for k in by_brand.keys() if k[0]]
    comp_keys = [k for k in by_brand.keys() if not k[0]]
    self_keys.sort(key=lambda k: k[1])
    comp_keys.sort(
        key=lambda k: (
            -(total_per_brand[k]),
            k[1],
        ),
    )
    sorted_keys: list[tuple[bool, str]] = [*self_keys, *comp_keys]

    for slot, (is_self, brand) in enumerate(sorted_keys):
        triples_map = by_brand[(is_self, brand)]
        all_ranks = [r for rs in triples_map.values() for r in rs if r is not None]
        matched = len(all_ranks)
        total = total_per_brand[(is_self, brand)]
        comp_slot = max(0, slot - len(self_keys))
        color = _SELF_COLOR if is_self else _COMP_COLORS[comp_slot % len(_COMP_COLORS)]
        brands_out.append(
            CompetitorBrandStat(
                brand=brand,
                is_self=is_self,
                color=color,
                mention_rate=(matched / total) if total else 0.0,
                top1_rate=(sum(1 for r in all_ranks if r == 1) / total) if total else 0.0,
                top3_rate=(sum(1 for r in all_ranks if r <= 3) / total) if total else 0.0,
                avg_rank=(sum(all_ranks) / len(all_ranks)) if all_ranks else None,
                model_ranks={
                    plat_key: min((r for r in ranks if r is not None), default=None)
                    for plat_key, ranks in triples_map.items()
                },
            )
        )

    # 摘录:竞品面板也按 triple 拆,SQL 一次 join Task 限定项目。
    # 用 BrandMention 行的 delivery / thinking 拼 compound key;Subtask 行
    # 没匹配 BrandMention 的孤儿走 default web/fast。
    excerpt_stmt = (
        select(
            Subtask.platform,
            Subtask.answer_content,
            Subtask.subtask_id,
            Subtask.updated_at,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            BrandMention.rank_position,
        )
        .outerjoin(Task, Task.task_id == Subtask.task_id)
        .outerjoin(
            BrandMention,
            and_(
                BrandMention.subtask_id == Subtask.subtask_id,
                BrandMention.is_self.is_(False),
                BrandMention.prompt == prompt.prompt,
            ),
        )
        .where(
            (Task.project_id.is_(None) | (Task.project_id == project.id)),
            Subtask.prompt == prompt.prompt,
            Subtask.updated_at >= start,
            Subtask.updated_at < end,
        )
        .order_by(Subtask.platform, Subtask.updated_at.desc())
    )
    excerpt_rows = db.execute(excerpt_stmt).all()

    latest_by_triple: dict[str, PlatformExcerpt] = {}
    for r in excerpt_rows:
        delivery = r.delivery_mode or "web"
        thinking = bool(r.thinking_mode)
        if (
            selected_triples is not None
            and (r.platform, delivery, thinking) not in selected_triples
        ):
            continue
        triple_key = compound_key(r.platform, delivery, thinking)
        if triple_key in latest_by_triple:
            continue
        excerpt = (r.answer_content or "")[:200]
        if not excerpt:
            continue
        latest_by_triple[triple_key] = PlatformExcerpt(
            excerpt=excerpt,
            rank=r.rank_position,
            run_id=r.subtask_id,
        )

    return QuestionCompetitorAnalyticsOut(
        project_id=project.id,
        prompt_id=prompt.id,
        start=start,
        end=end,
        brands=brands_out,
        excerpts=latest_by_triple,
    )


@router.get(
    "/projects/{project_id}/questions/{prompt_id}/competitor-analytics",
    response_model=QuestionCompetitorAnalyticsOut,
)
def questions_competitor_analytics(
    project_id: int,
    prompt_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    platforms: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
) -> QuestionCompetitorAnalyticsOut:
    """单问题竞品分析:按 brand × platform 聚合,SQL 预算 ≤ 2。

    旧 ``/questions/analytics?view=competitor`` 路径已删除(见 Task 13)。
    本端点只服务「竞品分析」子面板,不返回 self-brand 行。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    prompt = _get_project_prompt_or_404(
        db, project_id=project.id, prompt_id=prompt_id
    )
    win_start_dt, win_end_dt = _resolve_window_inline(days, start, end)
    selected_triples = parse_platforms_param(platforms)

    return _compute_question_competitor_analytics(
        db,
        project,
        prompt,
        start=win_start_dt,
        end=win_end_dt,
        selected_triples=selected_triples,
    )


@router.get(
    "/projects/{project_id}/questions/status-changes",
    response_model=QuestionStatusChangesOut,
)
def questions_status_changes(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    platforms: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Classify each question into one of 4 sets for the 稳定与掉落 pane.

    Window handling matches :func:`_resolve_window_inline` (same
    ``start``/``end``/``days`` semantics). ``is_self=true`` rows are
    the only ones considered — the operator's own brand is what the
    project monitors. Paused prompts (``status != monitoring``) are
    filtered out entirely: a paused question can never be "stable" or
    "dropped" because the scheduler isn't asking it.

    Four sets (NOT a 2x2 cross-tab):
      - ``stable``: prev_window had a mention AND current_window has
        at least one mention → kept being mentioned.
      - ``drops``: per (prompt, triple) loss-of-mention events。triple =
        ``${platform_code}__${delivery_mode}__${thinking}`` 与 Overview
        同口径,fast/think 与 web/mobile 不再合并。
      - ``never_listed``: no mention in either window.
      - ``listed``: at least one mention in the current window
        (regardless of prev).

    Drops carry a ``reason`` for the UI badge: "从排名 N 跌出 Top3"
    when the rank went from in-range to out-of-range, "从上榜掉出"
    when the mention disappeared entirely.

    ``platforms`` query param 是 toolbar 切档,与 Overview / summary /
    product-analytics 同口径。空集 → 直接返回空响应。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    # Window resolution — copy the same shape as `_resolve_window_inline`.
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        win_start, win_end = start, end
    else:
        window_days = days if days is not None else 15
        if window_days <= 0 or window_days > 90:
            raise HTTPException(400, "days must be between 1 and 90")
        today = now_local().date()
        win_start = today - timedelta(days=window_days - 1)
        win_end = today
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    length_days = (win_end - win_start).days + 1
    prev_end_dt = datetime.combine(win_start - timedelta(days=1), time.max)
    prev_start_dt = datetime.combine(
        win_start - timedelta(days=length_days), time.min
    )

    selected_triples = parse_platforms_param(platforms)
    if selected_triples is not None and not selected_triples:
        # 「全部未选」直接返回空响应,与 summary / product / competitor 同款
        return QuestionStatusChangesOut(
            project_id=project_id,
            start=win_start.isoformat(),
            end=win_end.isoformat(),
            stable=[],
            drops=[],
            never_listed=[],
            listed=[],
        )

    # Pull the catalogue — monitoring prompts only, in the operator's
    # configured order.
    prompt_rows = db.execute(
        select(
            ProjectPrompt.id,
            ProjectPrompt.prompt,
            ProjectPrompt.category,
        )
        .where(
            ProjectPrompt.project_id == project_id,
            ProjectPrompt.status == "monitoring",
        )
        .order_by(ProjectPrompt.sort)
    ).all()
    prompt_meta: dict[str, dict] = {
        prompt: {"id": pid, "category": cat}
        for pid, prompt, cat in prompt_rows
    }

    # Per-(prompt, triple) presence in each window, plus the best
    # rank observed。GROUP BY 加上 delivery_mode / thinking_mode 后,
    # 「同一 modelCode 但不同档位」不再合并:快思 / 网页 / 手机 各自独
    # 立成行,与 Overview 同口径。triple 拼成 ``compound_key`` 字符串
    # 给 UI,沿用前端 parseOverviewKey 解码展示。
    presence_stmt = (
        select(
            BrandMention.prompt,
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
            func.max(
                case(
                    (
                        and_(
                            BrandMention.created_at >= prev_start_dt,
                            BrandMention.created_at <= prev_end_dt,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("in_prev"),
            func.max(
                case(
                    (
                        and_(
                            BrandMention.created_at >= win_start_dt,
                            BrandMention.created_at <= win_end_dt,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("in_cur"),
            # Best (smallest) rank per window — used by drops to
            # describe the rank transition. Null when no rank rows.
            func.min(
                case(
                    (
                        and_(
                            BrandMention.created_at >= prev_start_dt,
                            BrandMention.created_at <= prev_end_dt,
                            BrandMention.rank_position.is_not(None),
                        ),
                        BrandMention.rank_position,
                    ),
                    else_=None,
                )
            ).label("best_prev_rank"),
            func.min(
                case(
                    (
                        and_(
                            BrandMention.created_at >= win_start_dt,
                            BrandMention.created_at <= win_end_dt,
                            BrandMention.rank_position.is_not(None),
                        ),
                        BrandMention.rank_position,
                    ),
                    else_=None,
                )
            ).label("best_cur_rank"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.is_self.is_(True),
        )
        .group_by(
            BrandMention.prompt,
            BrandMention.platform,
            BrandMention.delivery_mode,
            BrandMention.thinking_mode,
        )
    )
    if selected_triples is not None:
        presence_stmt = presence_stmt.where(
            tuple_(
                BrandMention.platform,
                BrandMention.delivery_mode,
                BrandMention.thinking_mode,
            ).in_(selected_triples)
        )
    presence_rows = db.execute(presence_stmt).all()

    # Per-prompt current / prev triple list — for the 上榜 quadrant the
    # UI shows the triples that drove the mention,展开到 compound key,
    # 让「上榜 N 个模型档位」与 Overview / 模型对比表口径对齐。
    cur_triples: dict[str, set[str]] = {}
    prev_triples: dict[str, set[str]] = {}
    for prompt, plat, delivery, is_thinking, in_prev, in_cur, _bp, _bc in presence_rows:
        triple_key = compound_key(plat, delivery, bool(is_thinking))
        if in_cur:
            cur_triples.setdefault(prompt or "(空问题)", set()).add(triple_key)
        if in_prev:
            prev_triples.setdefault(prompt or "(空问题)", set()).add(triple_key)

    # Build the 4 sets.
    stable: list[QuestionStableItem] = []
    drops: list[DropEvent] = []
    listed: list[QuestionStableItem] = []
    never_listed: list[QuestionStableItem] = []

    # Track which prompts have already been emitted into listed/
    # stable so the loop below doesn't double-emit.
    emitted: set[str] = set()
    # Per-prompt triple count for stable sort (most-mentioned first)。
    # 注意:这里用 triple 数,与 ProjectPlatform 配的档位数对齐(改前是
    # platform 数,与 Overview 错位)。
    stable_mentions: dict[str, int] = {}
    listed_mentions: dict[str, int] = {}

    for prompt, meta in prompt_meta.items():
        in_cur_set = cur_triples.get(prompt, set())
        in_prev_set = prev_triples.get(prompt, set())
        if in_cur_set and in_prev_set:
            stable.append(
                QuestionStableItem(
                    prompt_id=meta["id"],
                    prompt=prompt,
                    category=meta["category"],
                    platforms=sorted(in_cur_set),
                )
            )
            stable_mentions[prompt] = len(in_cur_set)
            emitted.add(prompt)
        if in_cur_set:
            listed.append(
                QuestionStableItem(
                    prompt_id=meta["id"],
                    prompt=prompt,
                    category=meta["category"],
                    platforms=sorted(in_cur_set),
                )
            )
            listed_mentions[prompt] = len(in_cur_set)
            emitted.add(prompt)

    # Drops — per (prompt, triple) row that was in prev but is
    # either missing in current or fell out of Top-3。
    for (
        prompt,
        plat,
        delivery,
        is_thinking,
        in_prev,
        in_cur,
        best_prev,
        best_cur,
    ) in presence_rows:
        if not in_prev or in_cur:
            continue
        meta = prompt_meta.get(prompt or "(空问题)")
        if not meta:
            continue
        if best_prev is None:
            # Prev had a mention without a rank — can't describe a
            # rank transition. Fall back to "掉出" wording.
            reason = "从上榜掉出"
        elif best_cur is None:
            reason = f"从排名 {best_prev} 跌出 Top3"
        else:
            reason = f"从排名 {best_prev} 跌出 Top3"
        triple_key = compound_key(plat, delivery, bool(is_thinking))
        drops.append(
            DropEvent(
                prompt_id=meta["id"],
                prompt=prompt,
                category=meta["category"],
                triple=triple_key,
                delivery_mode=delivery,
                thinking_mode=bool(is_thinking),
                dropped_day=win_end.isoformat(),
                from_rank=best_prev,
                to_rank=best_cur,
                reason=reason,
            )
        )

    # never_listed — catalogue prompts that never appeared in either
    # window. Sort by configured order (already ordered, but
    # convert set to list for stable JSON output).
    for prompt, meta in prompt_meta.items():
        if prompt in emitted:
            continue
        if not cur_triples.get(prompt) and not prev_triples.get(prompt):
            never_listed.append(
                QuestionStableItem(
                    prompt_id=meta["id"],
                    prompt=prompt,
                    category=meta["category"],
                    platforms=[],
                )
            )

    # Sort for stable UI rendering。dropped_day → triple → prompt_id,
    # 同档位的多条 drop 按 prompt 顺序。
    stable.sort(key=lambda x: (-stable_mentions.get(x.prompt, 0), x.prompt_id))
    listed.sort(key=lambda x: (-listed_mentions.get(x.prompt, 0), x.prompt_id))
    drops.sort(key=lambda x: (x.dropped_day, x.triple, x.prompt_id))
    never_listed.sort(key=lambda x: x.prompt_id)

    return QuestionStatusChangesOut(
        project_id=project_id,
        start=win_start.isoformat(),
        end=win_end.isoformat(),
        stable=stable,
        drops=drops,
        never_listed=never_listed,
        listed=listed,
    )


@router.get(
    "/projects/{project_id}/brand-mentions/summary",
    response_model=BrandMentionSummary,
)
def brand_mentions_summary(
    project_id: int,
    days: int = 15,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """KPI roll-up for the overview tab.

    Only counts the *monitored* brand (``is_self=true``) so the cards
    render "your brand's mentions" rather than "everyone's mentions".
    """
    from datetime import timedelta

    from app.models.common import now_local

    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    cutoff = now_local() - timedelta(days=days)
    base = select(BrandMention).where(
        BrandMention.project_id == project_id,
        BrandMention.is_self.is_(True),
        BrandMention.created_at >= cutoff,
    )
    rows = db.scalars(base).all()
    if not rows:
        return BrandMentionSummary(
            project_id=project_id,
            total_mentions=0,
            top1_rate=0.0,
            top3_rate=0.0,
            coverage=0,
            avg_sentiment=None,
            pending_count=0,
            failed_count=0,
        )
    total_mentions = sum(r.is_mention for r in rows)
    n = len(rows)
    top1 = sum(1 for r in rows if r.rank_position == 1)
    top3 = sum(1 for r in rows if r.rank_position is not None and r.rank_position <= 3)
    # sentiment is stored as a label string; translate to float for the
    # UI's color buckets (>=0.7 green / >=0.5 orange / else red).
    sentiment_values = [
        _SENTIMENT_TO_FLOAT[r.sentiment]
        for r in rows
        if r.sentiment in _SENTIMENT_TO_FLOAT
    ]
    avg_sentiment = (
        sum(sentiment_values) / len(sentiment_values) if sentiment_values else None
    )
    pending_count = sum(1 for r in rows if r.extract_status.value == "pending")
    failed_count = sum(1 for r in rows if r.extract_status.value == "failed")
    coverage = len({(r.prompt, r.platform) for r in rows})
    return BrandMentionSummary(
        project_id=project_id,
        total_mentions=total_mentions,
        top1_rate=top1 / n if n else 0.0,
        top3_rate=top3 / n if n else 0.0,
        coverage=coverage,
        avg_sentiment=avg_sentiment,
        pending_count=pending_count,
        failed_count=failed_count,
    )


# --------------------------------------------------------------------------
# Competitor analysis (data tab → 竞品分析)
# --------------------------------------------------------------------------


# Thin shell — actual computation lives in
# ``app.services.competitor_analysis.compute_competitor_analysis``.
@router.get(
    "/projects/{project_id}/competitor-analysis",
    response_model=CompetitorAnalysisOut,
)
def competitor_analysis(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    # UI 「全局工具栏 → 模型」筛选:逗号分隔 compound key(每个 entry 已
    # 带 ``${code}__${delivery}__${thinking}``)。空 / 缺省 = 不筛。
    platforms: str | None = None,
    # UI 「全局工具栏 → 问题」筛选:逗号分隔的 ``ProjectPrompt.id``。
    # 空 / 缺省 = 不筛。
    prompt_ids: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    selected_triples = parse_platforms_param(platforms)
    # BrandMention 按 prompt 文本存,所以把 ``prompt_ids`` 解析成
    # ``ProjectPrompt.prompt`` 文本后再传进 service;空集合(全部 id 解
    # 析不到)保留空数组 —— 比回退到 None 更安全:前端筛选应用后即便
    # prompt 已被删,也明确返回 0 行,而不是静默回退到「全部」。
    selected_prompt_texts: list[str] | None = None
    pid_list = parse_prompt_ids_param(prompt_ids)
    if pid_list is not None:
        text_rows = db.execute(
            select(ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.id.in_(pid_list),
            )
        ).all()
        selected_prompt_texts = [t for (t,) in text_rows]
    return compute_competitor_analysis(
        db=db,
        project_id=project_id,
        project=project,
        days=days,
        start=start,
        end=end,
        selected_triples=selected_triples,
        selected_prompt_texts=selected_prompt_texts,
    )


# --------------------------------------------------------------------------
# Citation analysis (data tab → 引用源分析)
# --------------------------------------------------------------------------


def _classify_citation(host: str) -> str:
    """Map a citation host string to one of the ui-sample category labels.

    The host is pre-normalized (lowercase, scheme stripped) — this
    function only does substring matching. The first matching rule
    wins; fallback is "其他". Pure function so the unit tests can call
    it without a DB.
    """
    if not host:
        return "其他"
    h = host.lower()
    for type_name, needles in _CITATION_DOMAIN_RULES:
        for n in needles:
            if n in h:
                return type_name
    return "其他"


@router.get(
    "/projects/{project_id}/citation-analysis",
    response_model=CitationAnalysisOut,
)
def citation_analysis(
    project_id: int,
    days: int = 15,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Windowed aggregate of citations the AI models linked in their answers.

    The UI on docs/ui-sample/index.html #tab-citation shows per-URL rows
    with type, citation count and rank position. We pull every
    ``geo_subtasks.citation_list_json`` in the last ``days`` days
    (default 15, max 90 — the same ceiling the 竞品分析 tab uses),
    explode each list into (subtask, rank, url, site, title) rows,
    and aggregate by URL.

    Per Molizhishu API contract: ``referenceList`` is the *complete*
    pool of references the model had available, while ``citationList``
    is the *subset* the model actually cited in the answer body. This
    endpoint therefore reads ``citationList`` — counting every
    reference would inflate the metrics with sources the operator's
    audience never saw. On non-yuanbao platforms ``citationList``
    comes back as plain URL strings; on yuanbao it's a list of
    ``{url, site, title, ...}`` dicts. The handler accepts both.

    The secondary tabs (全部 / 官方网站 / 新闻网站 / 自媒体) and the
    filter bar (模型 / 业务排名 / 关键词) are the only axis the UI
    owns beyond the time selector.

    Domain classification is a small substring table on the host
    substring (see ``_CITATION_DOMAIN_RULES`` in schemas.project). The
    classifier is deliberately conservative — anything that doesn't
    match a known category falls into "其他". This is much cheaper
    than calling out to a third-party DR / traffic API and keeps the
    entire response deterministic.
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    win_start, win_end = _resolve_competitor_window(days, None, None)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = db.execute(
        select(
            Subtask.subtask_id,
            Subtask.platform,
            Subtask.citation_list_json,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    ).all()

    # Per-URL aggregation. We keep two parallel dicts:
    #   buckets[url] -> {site, title, count, sum_rank, n_rank, platforms, first, last}
    #   total_citations -> (subtask, citation) pair count
    total_citations = 0
    buckets: dict[str, dict] = {}
    for subtask_id, platform, cites, created_at in rows:
        items = cites if isinstance(cites, list) else []
        if not items:
            continue
        for idx, item in enumerate(items):
            # citation_list_json shape is platform-dependent:
            #   - yuanbao returns {url, site, title, summary, index, ...}
            #   - deepseek / doubao / hunyuan / qianwen / wenxinyiyan
            #     return a flat list of URL strings
            # Treat both as the same row — the dict carries site/title,
            # the string carries just the URL.
            if isinstance(item, dict):
                url = item.get("url") or item.get("link")
                if not isinstance(url, str) or not url.strip():
                    continue
                site = item.get("site") or ""
                if not isinstance(site, str):
                    site = ""
                title = item.get("title") or ""
                if not isinstance(title, str):
                    title = ""
            elif isinstance(item, str):
                url = item
                site = ""
                title = ""
            else:
                continue
            url = url.strip()
            total_citations += 1
            cur = buckets.get(url)
            if cur is None:
                cur = {
                    "site": site,
                    "title": title,
                    "count": 0,
                    "sum_rank": 0,
                    "n_rank": 0,
                    "platforms": set(),
                    "first_seen": created_at,
                    "last_seen": created_at,
                }
                buckets[url] = cur
            # Last write wins for title (we don't store a history).
            if title:
                cur["title"] = title
            if site and not cur["site"]:
                cur["site"] = site
            cur["count"] += 1
            cur["sum_rank"] += idx
            cur["n_rank"] += 1
            if platform:
                cur["platforms"].add(platform)
            if created_at < cur["first_seen"]:
                cur["first_seen"] = created_at
            if created_at > cur["last_seen"]:
                cur["last_seen"] = created_at

    items: list[CitationOut] = []
    type_counts: dict[str, int] = {}
    for url, cur in buckets.items():
        host = cur["site"] or url
        type_name = _classify_citation(host)
        type_counts[type_name] = type_counts.get(type_name, 0) + cur["count"]
        items.append(
            CitationOut(
                url=url,
                site=cur["site"],
                title=cur["title"] or None,
                type=type_name,
                count=cur["count"],
                avg_rank=(cur["sum_rank"] / cur["n_rank"]) if cur["n_rank"] else None,
                platforms=sorted(cur["platforms"]),
                first_seen=cur["first_seen"],
                last_seen=cur["last_seen"],
            )
        )
    items.sort(key=lambda c: c.count, reverse=True)

    return CitationAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days,
        total_citations=total_citations,
        unique_urls=len(buckets),
        type_counts=type_counts,
        items=items,
    )


# --------------------------------------------------------------------------
# Source preferences (data tab → 信源偏好 → 全部信源)
# --------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/source-preferences",
    response_model=SourcePreferenceOut,
)
def source_preferences(
    project_id: int,
    days: int = 15,
    start: date | None = Query(
        None,
        description=(
            "自定义窗口起点(YYYY-MM-DD),与 ``end`` 同进同出,优先于 ``days``。"
            "toolbar 「自定义」范围时使用。"
        ),
    ),
    end: date | None = Query(
        None,
        description="自定义窗口终点(YYYY-MM-DD),与 ``start`` 同进同出。",
    ),
    models: str | None = Query(
        None,
        description=(
            "逗号分隔的 compound platform 列表(如 qianwen__web__fast,baiduai__web__fast),"
            "用于补齐 by_model_top:用户在 dropdown 选了 N 个但窗口内某些 platform 没数据时,"
            "也返回对应空卡片,UI 视觉对齐 dropdown。省略时不补齐。"
        ),
    ),
    prompts: str | None = Query(
        None,
        description=(
            "逗号分隔的 ``ProjectPrompt.id`` 列表(全局工具栏 → 问题 筛选)。"
            "空 / 缺省 = 不筛;空集合(全部 id 解析不到)显式返回 0 行。"
        ),
    ),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Per-URL aggregation of ``Subtask.reference_list_json`` in the window.

    跟 :func:`citation_analysis` 共用窗口口径(Task.project_id + Task.created_local_at),
    但读的是模型完整可用的信源池,而不是回答正文里实际引用的子集。返回 5 块:
    kpi / type_counts / platform_slices / top_sources(前 50)/ trend(每日 set diff)。
    spec §后端设计 + docs/superpowers/specs/2026-08-19-source-preferences-tab-design.md。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    # toolbar 日期下拉:preset 走 days,自定义走 start/end。service 内部
    # 统一解析(start/end 优先),endpoint 不重复校验。
    selected = [m.strip() for m in (models or "").split(",") if m.strip()] or None

    # toolbar 「问题」筛选:把 ``ProjectPrompt.id`` 解析成 ``prompt`` 文本,
    # service 按 ``Subtask.prompt IN (...)`` 过滤(Subtask 按 prompt 文本
    # 存,无 prompt_id 外键)。空集合(全部 id 解析不到)保留空数组 —— 比
    # 回退到 None 更安全:前端筛选应用后即便 prompt 已被删,也明确返回
    # 0 行,而不是静默回退到「全部」。
    selected_prompt_texts: list[str] | None = None
    pid_list = parse_prompt_ids_param(prompts)
    if pid_list is not None:
        text_rows = db.execute(
            select(ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.id.in_(pid_list),
            )
        ).all()
        selected_prompt_texts = [t for (t,) in text_rows]

    try:
        return compute_source_preferences(
            db=db, project_id=project_id, days=days, start=start, end=end,
            selected_platforms=selected,
            selected_prompt_texts=selected_prompt_texts,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get(
    "/projects/{project_id}/source-detail",
    response_model=SourceDetailOut,
)
def source_detail(
    project_id: int,
    days: int = 15,
    start: date | None = Query(
        None,
        description="自定义窗口起点(YYYY-MM-DD),与 ``end`` 同进同出,优先于 ``days``。",
    ),
    end: date | None = Query(
        None,
        description="自定义窗口终点(YYYY-MM-DD),与 ``start`` 同进同出。",
    ),
    models: str | None = Query(
        None,
        description=(
            "逗号分隔的 compound platform 列表(如 qianwen__web__fast),"
            "过滤 SQL 与信源明细列表;省略 = 不筛。"
        ),
    ),
    prompts: str | None = Query(
        None,
        description=(
            "逗号分隔的 ``ProjectPrompt.id`` 列表(全局工具栏 → 问题 筛选)。"
            "空 / 缺省 = 不筛;空集合(全部 id 解析不到)显式返回 0 行。"
        ),
    ),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """信源明细页 —— 一次返回窗口内全部 unique URL,前端做类型筛选 / 关键词
    搜索 / 排序 + 选中 → iframe 预览。字段口径与 ``source-preferences`` 的
    top_sources 一致,只是没有 50 上限且不做 KPI / 趋势聚合。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    selected = [m.strip() for m in (models or "").split(",") if m.strip()] or None

    selected_prompt_texts: list[str] | None = None
    pid_list = parse_prompt_ids_param(prompts)
    if pid_list is not None:
        text_rows = db.execute(
            select(ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.id.in_(pid_list),
            )
        ).all()
        selected_prompt_texts = [t for (t,) in text_rows]

    try:
        return compute_source_detail(
            db=db, project_id=project_id, days=days, start=start, end=end,
            selected_platforms=selected,
            selected_prompt_texts=selected_prompt_texts,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get(
    "/projects/{project_id}/source-video",
    response_model=VideoSourceOut,
)
def source_video(
    project_id: int,
    days: int = 15,
    start: date | None = Query(
        None,
        description="自定义窗口起点(YYYY-MM-DD),与 ``end`` 同进同出,优先于 ``days``。",
    ),
    end: date | None = Query(
        None,
        description="自定义窗口终点(YYYY-MM-DD),与 ``start`` 同进同出。",
    ),
    models: str | None = Query(
        None,
        description=(
            "逗号分隔的 compound platform 列表(如 qianwen__web__fast),"
            "过滤 SQL 与视频类信源聚合;省略 = 不筛。"
        ),
    ),
    prompts: str | None = Query(
        None,
        description=(
            "逗号分隔的 ``ProjectPrompt.id`` 列表(全局工具栏 → 问题 筛选)。"
            "空 / 缺省 = 不筛;空集合(全部 id 解析不到)显式返回 0 行。"
        ),
    ),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """视频类信源 sub-tab —— 仅统计 host 命中「视频平台」白名单
    (抖音 / B 站 / 快手 / 西瓜 / YouTube / 优酷 / 腾讯视频 / 新浪视频)
    的引用,按视频平台分桶 + 按模型聚合,供顶部平台卡片网格 + 底部
    ranking chart 使用。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    selected = [m.strip() for m in (models or "").split(",") if m.strip()] or None

    selected_prompt_texts: list[str] | None = None
    pid_list = parse_prompt_ids_param(prompts)
    if pid_list is not None:
        text_rows = db.execute(
            select(ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.id.in_(pid_list),
            )
        ).all()
        selected_prompt_texts = [t for (t,) in text_rows]

    try:
        return compute_source_video(
            db=db, project_id=project_id, days=days, start=start, end=end,
            selected_platforms=selected,
            selected_prompt_texts=selected_prompt_texts,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get(
    "/projects/{project_id}/source-self",
    response_model=SourceSelfOut,
)
def source_self(
    project_id: int,
    days: int = 15,
    start: date | None = Query(
        None,
        description="自定义窗口起点(YYYY-MM-DD),与 ``end`` 同进同出,优先于 ``days``。",
    ),
    end: date | None = Query(
        None,
        description="自定义窗口终点(YYYY-MM-DD),与 ``start`` 同进同出。",
    ),
    models: str | None = Query(
        None,
        description=(
            "逗号分隔的 compound platform 列表(如 qianwen__web__fast),"
            "过滤 SQL 与自有文章聚合;省略 = 不筛。"
        ),
    ),
    prompts: str | None = Query(
        None,
        description=(
            "逗号分隔的 ``ProjectPrompt.id`` 列表(全局工具栏 → 问题 筛选)。"
            "空 / 缺省 = 不筛;空集合(全部 id 解析不到)显式返回 0 行。"
        ),
    ),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """自有文章引用分析 sub-tab —— 仅统计 host 命中「自媒体」分类
    (抖音 / B 站 / 快手 / 西瓜 / YouTube / 优酷 / 腾讯视频 / 新浪视频)
    的引用,提供 KPI + 按模型分布 + 信源列表 + 运营建议。

    跟「视频类信源」共用同一份底层数据(都基于「自媒体」分类的 host),
    差异只在聚合维度:本接口按 model + URL 维度,视频类信源按 video platform 维度。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    selected = [m.strip() for m in (models or "").split(",") if m.strip()] or None

    selected_prompt_texts: list[str] | None = None
    pid_list = parse_prompt_ids_param(prompts)
    if pid_list is not None:
        text_rows = db.execute(
            select(ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.id.in_(pid_list),
            )
        ).all()
        selected_prompt_texts = [t for (t,) in text_rows]

    try:
        return compute_source_self(
            db=db, project_id=project_id, days=days, start=start, end=end,
            selected_platforms=selected,
            selected_prompt_texts=selected_prompt_texts,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# --------------------------------------------------------------------------
# Overview tab (docs/ui-sample #tab-overview)
# --------------------------------------------------------------------------

# A custom range wider than this is rejected: the daily buckets stop being
# readable and the query stops being cheap.
OVERVIEW_MAX_DAYS = 62
OVERVIEW_PRESET_DAYS = (7, 15, 30, 60)


def _overview_window(
    days: int, start: date | None, end: date | None
) -> tuple[date, date]:
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(400, "start and end must be provided together")
        if end < start:
            raise HTTPException(400, "end must not be earlier than start")
        if (end - start).days + 1 > OVERVIEW_MAX_DAYS:
            raise HTTPException(400, f"range must not exceed {OVERVIEW_MAX_DAYS} days")
        return start, end
    if days not in OVERVIEW_PRESET_DAYS:
        raise HTTPException(400, f"days must be one of {OVERVIEW_PRESET_DAYS}")
    today = now_local().date()
    return today - timedelta(days=days - 1), today


def _rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def _delta_pct(value: float, prev: float) -> float | None:
    """Growth vs the previous window; None when there is no baseline."""
    if prev == 0:
        return None
    return (value - prev) / prev


class _OverviewWindow:
    """One time window's contribution to the overview tab — every number
    comes from ``geo_brand_mentions`` rows.

    Older versions joined ``geo_subtasks`` / ``geo_tasks`` for KPI
    denominators (``mention_rate`` = subtask-level, ``answer_count`` =
    subtasks with non-empty ``answer_content``). That mixed two tables
    whose cardinalities can drift apart (a subtask without a brand-
    mention row, or a brand-mention row whose task was deleted), so the
    cards read inconsistently under different filter combinations.
    """

    def __init__(
        self,
        db: Session,
        project_id: int,
        start: date,
        end: date,
        # ``selected_triples`` 是 UI 「全局工具栏 → 模型」筛选的最终口径
        # —— 每个 entry 是 ``(platform_code, delivery_mode, is_think)`` 三
        # 元组,由 GlobalToolbar 的 compound key ``${code}__${delivery}__${thinking}``
        # 解析而来。None = 不筛(全平台);空集合 = 「全不选」,SQLAlchemy
        # ``tuple_(...).in_(())`` 渲染成 ``1 != 1`` 自动返回 0 行;非空集
        # 合 → 按三元组精确匹配 BrandMention 行。带 delivery / thinking
        # 是关键:旧版只按 platform_code 过滤会让「只勾快速 / 只勾 PC」
        # 错带同 code 的思考 / 移动档位,与工具栏 UI 口径不一致。
        selected_triples: set[tuple[str, str, bool]] | None = None,
        prompt_texts: list[str] | None = None,
        thinking_modes: list[bool] | None = None,
        delivery_modes: list[str] | None = None,
    ) -> None:
        self.days = [
            start + timedelta(days=i) for i in range((end - start).days + 1)
        ]
        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)

        # ``selected_triples`` 已在前置 router 层区分 None(全选) vs 空集
        # (显式未选),_OverviewWindow 不再二次回退,跟 prompt_filter 的
        # 「空集合保留空 list」语义对齐。
        platform_filter = selected_triples
        # ``prompt_texts`` 是 UI 「全局工具栏 → 问题」筛选的最终口径 —— 后端
        # 在 router 层已经把 ``prompt_ids`` 解析成对应的 prompt 文本。None
        # 视为不筛;空数组视为「全部 id 都解析不到 / 全部 prompt 已删」,保留
        # 为空 list,SQL IN () 自然返回 0 行,避免静默回退到不筛。
        prompt_filter = None if prompt_texts is None else prompt_texts

        # 模式 / 终端(历史参数,GlobalToolbar 已不发送)。``thinking_mode``
        # / ``delivery_mode`` 已经在 BrandMention 行上落桶,直接拿持久化
        # 列做 IN 过滤即可,不依赖 Subtask。空列表 → 不筛(全选语义)。
        thinking_filter: list[bool] | None = (
            thinking_modes if thinking_modes else None
        )
        delivery_filter: list[str] | None = (
            delivery_modes if delivery_modes else None
        )

        # 单条 SELECT,所有 KPI / sparkline / 趋势 / 排行 / 模型维度都
        # 消费这一份 ``self.mentions``。窗口按 ``BrandMention.created_at``
        # 过滤(抽取流水线记录到 mention 的时间),与 Subtask / Task 解耦;
        # 抽取通常在提问后秒级触发,与「问题被问到」基本同步。``is_self``
        # 在这一层就锁死,后面所有 KPI 都只看项目自品牌行,排除竞品行。
        rows_stmt = (
            select(BrandMention)
            .where(
                BrandMention.project_id == project_id,
                BrandMention.is_self.is_(True),
                BrandMention.created_at >= lo,
                BrandMention.created_at <= hi,
            )
        )
        if platform_filter is not None:
            if platform_filter:
                rows_stmt = rows_stmt.where(
                    tuple_(
                        BrandMention.platform,
                        BrandMention.delivery_mode,
                        BrandMention.thinking_mode,
                    ).in_(platform_filter)
                )
            else:
                rows_stmt = rows_stmt.where(literal(False))
        if prompt_filter is not None:
            rows_stmt = rows_stmt.where(BrandMention.prompt.in_(prompt_filter))
        if thinking_filter is not None:
            rows_stmt = rows_stmt.where(
                BrandMention.thinking_mode.in_(thinking_filter)
            )
        if delivery_filter is not None:
            rows_stmt = rows_stmt.where(
                BrandMention.delivery_mode.in_(delivery_filter)
            )
        self.mentions: list[BrandMention] = list(db.execute(rows_stmt).scalars())

        # 每行归属到窗口里的具体一天 —— 直接用 ``created_at`` 落到 ``days``
        # 桶里。WHERE 已经把窗口外的行挡掉了,理论上 ``row_day`` 必在 days
        # 内,但保留 ``if d in by_day`` 的防御性写法,跟未来窗口语义变化
        # 解耦。
        self.row_day: dict[int, date] = {
            m.id: m.created_at.date() for m in self.mentions
        }

    def kpis(self) -> dict[str, tuple[float, list[float]]]:
        """Window totals + per-day sparkline. Every number is row-level
        on ``self.mentions``:

        - ``mention_rate``: ``is_mention > 0`` 行 / 全部 self 行
        - ``top1_rate`` / ``top3_rate``: rank 命中行 / ``is_mention > 0`` 行
        - ``correct_rate``: ``is_correct = True`` 行 / 全部 self 行
        - ``question_count``: 窗口内 ``(task_id, prompt)`` 去重数
        - ``answer_count``: 窗口内 ``subtask_id`` 去重数

        分子分母同源 → 不同筛选组合下数字之间不会再有口径漂移。
        """
        by_day: dict[date, list[BrandMention]] = {d: [] for d in self.days}
        for m in self.mentions:
            d = self.row_day.get(m.id)
            if d in by_day:
                by_day[d].append(m)

        n_mentions_total = sum(m.is_mention for m in self.mentions)
        n_self_rows = max(len(self.mentions), 1)
        n_mentions_denom = max(n_mentions_total, 1)

        def _topn_by_day(predicate):
            return [
                _rate(
                    sum(1 for m in by_day[d] if predicate(m)),
                    max(sum(1 for m in by_day[d] if m.is_mention), 1),
                )
                for d in self.days
            ]

        return {
            "mention_rate": (
                _rate(n_mentions_total, n_self_rows),
                [
                    _rate(
                        sum(m.is_mention for m in by_day[d]),
                        max(len(by_day[d]), 1),
                    )
                    for d in self.days
                ],
            ),
            "total_mentions": (
                float(n_mentions_total),
                [float(sum(m.is_mention for m in by_day[d])) for d in self.days],
            ),
            "top1_rate": (
                _rate(
                    sum(1 for m in self.mentions
                        if m.is_mention and m.rank_position == 1),
                    n_mentions_denom,
                ),
                _topn_by_day(
                    lambda m: m.is_mention and m.rank_position == 1
                ),
            ),
            "top3_rate": (
                _rate(
                    sum(
                        1 for m in self.mentions
                        if m.is_mention
                        and m.rank_position is not None
                        and m.rank_position <= 3
                    ),
                    n_mentions_denom,
                ),
                _topn_by_day(
                    lambda m: m.is_mention
                    and m.rank_position is not None
                    and m.rank_position <= 3
                ),
            ),
            "correct_rate": (
                _rate(
                    sum(1 for m in self.mentions if m.is_correct),
                    n_self_rows,
                ),
                [
                    _rate(
                        sum(1 for m in by_day[d] if m.is_correct),
                        max(len(by_day[d]), 1),
                    )
                    for d in self.days
                ],
            ),
            "question_count": (
                float(len({
                    (m.task_id, m.prompt) for m in self.mentions
                })),
                [
                    float(len({
                        (m.task_id, m.prompt) for m in by_day[d]
                    }))
                    for d in self.days
                ],
            ),
            "answer_count": (
                float(len({m.subtask_id for m in self.mentions})),
                [float(len({m.subtask_id for m in by_day[d]})) for d in self.days],
            ),
        }


@router.get("/projects/{project_id}/overview", response_model=ProjectOverviewOut)
def project_overview(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    # UI 「全局工具栏 → 模型」筛选:逗号分隔的 modelCode 列表(对应
    # ``Subtask.platform`` / ``BrandMention.platform``)。空 / 缺省 = 不筛,
    # 走原口径(全部 model)。
    platforms: str | None = None,
    # UI 「全局工具栏 → 问题」筛选:逗号分隔的 ``ProjectPrompt.id`` 列表。
    # 空 / 缺省 = 不筛(全部问题)。与 ``platforms`` 同时收紧 KPI 分母与
    # 分子,确保窗口内未选问题的数据整体不进入计算。
    prompt_ids: str | None = None,
    # UI 「全局工具栏 → 模式」筛选:逗号分隔的 ``true``/``false`` 列表。
    # 空 / 缺省 = 不筛。``true`` = 思考桶 (Subtask.mode IN
    # 'reasoning'/'reasoning_search'),``false`` = 快速桶
    # ('standard'/'search'/'web')。同步收紧分子与分母。
    thinking_mode: str | None = None,
    # UI 「全局工具栏 → 终端」筛选:逗号分隔的 ``web``/``mobile`` 列表。
    # 空 / 缺省 = 不筛。``mobile`` 由 ``Subtask.platform`` 以
    # ``_mobile`` 结尾派生。
    delivery_mode: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Everything the 首屏概览 tab renders: 4 KPI cards + trend/model sub-panes.

    The 4 KPI cards mirror docs/更新版UI #tab-overview: 总提及率 / Top1 / Top3
    / 正确率. Per-day sparklines come from the same windowed buckets as
    the count card.

    ``start``/``end`` (inclusive, local dates) drive the 自定义 range and
    win over ``days``; without them the window is the last ``days`` days
    ending today.

    ``platforms`` 是逗号分隔的 compound key 列表(每项
    ``${modelCode}__${delivery}__${thinking}``,如 ``qianwen__web__fast``),
    由 GlobalToolbar.applyModels 直接透传 staged 集合的合成 key。空字符
    串 / 缺省视为「不筛」(全平台);非空 → 按 ``(platform, delivery_mode,
    thinking_mode)`` 三元组精确匹配,确保「只勾快速 / 只勾 PC」不会把
    同 modelCode 的思考 / 移动档位错带进来。传入时同时收紧 KPI 分母
    与分子,确保窗口内未选档位的数据整体不进入计算。

    ``prompt_ids`` 是逗号分隔的 ``ProjectPrompt.id`` 列表;后端按项目把
    id 解析成对应的 ``prompt`` 文本,直接过滤 BrandMention 行。

    所有数字(KPI / trend / ranking / model_dimensions) 都从
    ``geo_brand_mentions`` 行级口径算,不 JOIN ``geo_subtasks`` /
    ``geo_tasks``,与工具栏 UI 的口径一致。

    ``thinking_mode`` / ``delivery_mode`` 是历史参数,GlobalToolbar 已不
    再发送(模型 compound key 已携带完整三元组),保留是为不破坏旧路径;
    后端不再消费,只是不抛错。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    # 解码 comma-separated compound key 列表,每个 entry 切成
    # ``(platform, delivery, is_think)`` 三元组,与 ProjectPlatform /
    # BrandMention 的桶列对齐。非法 entry(不是合法 compound key 形
    # 式,如旧 raw modelCode)静默忽略。None = 「全选」走原口径;空集
    # 合 = 「全不选」,SQLAlchemy ``tuple_(...).in_(())`` 渲染成
    # ``1 != 1`` 自动返回 0 行,跟 prompt_ids 「显式未选」语义对齐。
    selected_triples: set[tuple[str, str, bool]] | None = None
    if platforms is not None:
        parsed = [p.strip() for p in platforms.split(",") if p.strip()]
        triples: set[tuple[str, str, bool]] = set()
        for entry in parsed:
            parts = entry.split("__")
            if len(parts) != 3:
                continue
            platform_str, delivery, thinking = parts
            if delivery not in ("web", "mobile"):
                continue
            if thinking not in ("fast", "think"):
                continue
            triples.add((platform_str, delivery, thinking == "think"))
        selected_triples = triples

    # 解码 prompt_ids:根据项目把 id 解析成对应 prompt 文本(BrandMention
    # 按文本存)。项目下 prompt 文本 unique,所以 IN-list 不会有歧义。
    prompt_filter: list[str] | None = None
    if prompt_ids is not None:
        parsed_ids = [
            int(p) for p in prompt_ids.split(",") if p.strip().isdigit()
        ]
        if parsed_ids:
            text_rows = db.execute(
                select(ProjectPrompt.prompt).where(
                    ProjectPrompt.project_id == project_id,
                    ProjectPrompt.id.in_(parsed_ids),
                )
            ).all()
            texts = [t for (t,) in text_rows]
            prompt_filter = texts or []
            # 空集合(全部 id 都解析不到)保留空数组 —— 比回退到 None
            # 更安全:前端筛选应用后即便 prompt 已被删,也明确返回 0,
            # 而不是静默回退到「全部」让用户误以为没生效。

    # thinking_mode / delivery_mode 是历史参数,GlobalToolbar 已不发送
    # (模型 compound key 已携带完整三元组)。保留是为不破坏旧路径——
    # 底层走 BrandMention 的持久化列 IN 过滤,不再 JOIN Subtask,与
    # overview 「纯走 BrandMention」口径一致。非法 token 静默忽略;空
    # 集合视为不筛(全选语义)。
    thinking_filter: list[bool] | None = None
    if thinking_mode is not None:
        parsed: list[bool] = []
        for t in thinking_mode.split(","):
            s = t.strip().lower()
            if s == "true":
                parsed.append(True)
            elif s == "false":
                parsed.append(False)
        thinking_filter = parsed or None

    delivery_filter: list[str] | None = None
    if delivery_mode is not None:
        parsed_d = [
            t.strip()
            for t in delivery_mode.split(",")
            if t.strip() in ("web", "mobile")
        ]
        delivery_filter = parsed_d or None

    win_start, win_end = _overview_window(days, start, end)
    span = (win_end - win_start).days + 1
    cur = _OverviewWindow(
        db,
        project_id,
        win_start,
        win_end,
        selected_triples,
        prompt_filter,
        thinking_filter,
        delivery_filter,
    )
    prev = _OverviewWindow(
        db,
        project_id,
        win_start - timedelta(days=span),
        win_start - timedelta(days=1),
        selected_triples,
        prompt_filter,
        thinking_filter,
        delivery_filter,
    )
    cur_kpis, prev_kpis = cur.kpis(), prev.kpis()

    def card(key: str) -> OverviewKpi:
        value, spark = cur_kpis[key]
        prev_value = prev_kpis[key][0]
        return OverviewKpi(
            value=value,
            prev_value=prev_value,
            delta_pct=_delta_pct(value, prev_value),
            spark=spark,
        )

    # Legend order follows the project's configured platforms so a platform
    # with no data in the window still shows up as a flat line.
    # 每个 ProjectPlatform row = 一个 (platform_code × delivery_mode ×
    # thinking_mode) 档,与 docs/模型名字.txt 的 4 档展开对齐:同一逻辑
    # 模型的「网页-快速」「网页-思考」「手机-快速」「手机-思考」是 4 个
    # 独立的 chart series / rank 行 / model-dimension 行。compound key
    # 用 ``row.platform_code`` 而不是 ``row.platform``:mobile 行的
    # ``platform`` 是 web code(``baiduai``),``platform_code`` 才是真正
    # 落到 Subtask / BrandMention 的 code(``baidu_mobile``)。后端
    # 选 triple 必须跟 GlobalToolbar.rowKeyOf 用同一列 —— 否则 mobile
    # 档的 ProjectPlatform row 会被 selected_triples 误过滤掉。
    def _overview_key(row: ProjectPlatform) -> str:
        thinking = "think" if row.thinking_mode else "fast"
        return f"{row.platform_code}__{row.delivery_mode.value}__{thinking}"

    pp_rows = list(
        db.execute(
            select(ProjectPlatform)
            .where(ProjectPlatform.project_id == project_id)
            .order_by(ProjectPlatform.id)
        ).scalars()
    )

    # Chart series key 只来自配置的 ProjectPlatform row,跟 GlobalToolbar
    # 「全选 / 子集」一一对应:全选 N 行 → N 条 series。窗口里出现的
    # orphan mention(平台已下线 / 配置被改过)不进入 trend,ranking 同理,
    # 避免「全选 8 个 = chart 11 条」的工具栏 / 图表不一致。
    seen: set[str] = set()
    keys: list[str] = []
    for row in pp_rows:
        key = _overview_key(row)
        if key in seen:
            continue
        # ``selected_triples`` 是 (platform_code, delivery_mode, is_think)
        # 三元组集合。ProjectPlatform row 走 ``(row.platform_code,
        # row.delivery_mode.value, row.thinking_mode)`` 三元组精确匹配
        # —— 「只勾快速」时千问-网页-思考 这类同 platform_code 不同档位
        # 的 row 自然排除,与 KPI 分子 / 分母过滤口径一致。用
        # ``platform_code`` 而非 ``platform``:mobile 行的 ``platform``
        # 是 web code,而 selected_triples 里的 code 是真正的 API code
        # (mobile 行是 ``baidu_mobile`` / ``qianwen_mobile`` 等)。
        if selected_triples is not None:
            triple = (
                row.platform_code,
                row.delivery_mode.value,
                row.thinking_mode,
            )
            if triple not in selected_triples:
                continue
        seen.add(key)
        keys.append(key)

    # 每个 chart key = 一个 ProjectPlatform row,所有 KPI / 分桶口径从
    # ``cur.mentions`` 这份行级数据里取:
    #   - trend     : 每日 is_mention 行求和
    #   - ranking   : top1 = rank==1 行 / 全部 mention 行(口径与 KPI top1 一致)
    #   - model_dim:
    #       mention_rate = mention 行 / 全部 self 行(对应 KPI mention_rate)
    #       top{1,2,3}   = rank 命中行 / mention 行(对应 KPI top1/top3)
    # 所有分母都来自 BrandMention,不再依赖 Subtask。
    trend: list[TrendSeries] = []
    ranking: list[PlatformRank] = []
    model_dimensions: list[ModelDimension] = []
    for key in keys:
        platform_str, delivery, thinking = key.split("__")
        is_think = thinking == "think"
        rows = [
            m
            for m in cur.mentions
            if m.platform == platform_str
            and (m.delivery_mode if m.delivery_mode else "web") == delivery
            and (m.thinking_mode is True) == is_think
        ]
        per_day = {d: 0 for d in cur.days}
        for m in rows:
            day = cur.row_day.get(m.id)
            if day in per_day:
                per_day[day] += m.is_mention
        trend.append(
            TrendSeries(platform=key, data=[per_day[d] for d in cur.days])
        )

        # ranking 用「mention 行」(is_mention>0)做分母:这条 top1 率的口径
        # 等于「品牌被提到时排第 1 的占比」,与 KPI top1_rate 完全对齐。
        mention_rows = [m for m in rows if m.is_mention]
        n_mentions_key = max(len(mention_rows), 1)
        top1 = sum(1 for m in mention_rows if m.rank_position == 1)
        ranking.append(
            PlatformRank(
                platform=key,
                top1_rate=_rate(top1, n_mentions_key),
                sample=len(mention_rows),
            )
        )

        # 模型维度 4 指标:
        #   - mention_rate = is_mention 行 / 该 key 全部 self 行
        #     (「该平台的所有 mention 中,真正命中的占比」)
        #   - top{1,2,3}   = rank 命中行 / is_mention 行
        #     (「命中的 mention 中,排名位置达标的占比」)
        # 分母都用 BrandMention 行,不再走 Subtask。
        n_rows_key = max(len(rows), 1)
        model_dimensions.append(
            ModelDimension(
                platform=key,
                mention_rate=_rate(
                    sum(m.is_mention for m in rows), n_rows_key
                ),
                top1_rate=_rate(top1, n_mentions_key),
                top2_rate=_rate(
                    sum(
                        1
                        for m in mention_rows
                        if m.rank_position is not None and m.rank_position <= 2
                    ),
                    n_mentions_key,
                ),
                top3_rate=_rate(
                    sum(
                        1
                        for m in mention_rows
                        if m.rank_position is not None and m.rank_position <= 3
                    ),
                    n_mentions_key,
                ),
                sample=len(rows),
            )
        )
    ranking.sort(key=lambda r: (r.top1_rate, r.sample), reverse=True)

    return ProjectOverviewOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=span,
        labels=[d.strftime("%m-%d") for d in cur.days],
        mention_rate=card("mention_rate"),
        top1_rate=card("top1_rate"),
        top3_rate=card("top3_rate"),
        correct_rate=card("correct_rate"),
        total_mentions=card("total_mentions"),
        question_count=card("question_count"),
        answer_count=card("answer_count"),
        trend=trend,
        ranking=ranking,
        model_dimensions=model_dimensions,
        pending_count=sum(
            1 for m in cur.mentions if m.extract_status.value == "pending"
        ),
        failed_count=sum(
            1 for m in cur.mentions if m.extract_status.value == "failed"
        ),
    )


# --------------------------------------------------------------------------
# 自有文章引用分析(独立一级页面,表格视图)
# --------------------------------------------------------------------------

_OWN_ARTICLES_MAX_BYTES = 5 * 1024 * 1024


@router.get(
    "/projects/{project_id}/own-articles",
    response_model=OwnArticleListOut,
)
def list_own_articles(
    project_id: int,
    days: int = Query(15),
    start: date | None = Query(None),
    end: date | None = Query(None),
    models: str | None = Query(None),
    prompts: str | None = Query(None),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """项目自有文章列表 + 引用统计。

    - 引用次数 / 引用模型 / 最近引用 = 后端 join ``geo_subtasks.reference_list_json``
      (全信源池,不只是回答正文里 cite 过的子集)在 ``days`` / ``start..end`` /
      ``models`` / ``prompts`` 过滤范围内的聚合结果。
    - 排序:``publish_date DESC, id DESC`` —— 有发布日期的按新到旧;
      无发布日期的(URL 列表批量导入未指定日期)兜底按 id 倒序。
      MySQL 下 ``DESC`` 自然让 NULL 排最后,无需 ``NULLS LAST``。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    selected = [m.strip() for m in (models or "").split(",") if m.strip()] or None

    selected_prompt_texts: list[str] | None = None
    pid_list = parse_prompt_ids_param(prompts)
    if pid_list is not None:
        text_rows = db.execute(
            select(ProjectPrompt.prompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.id.in_(pid_list),
            )
        ).all()
        selected_prompt_texts = [t for (t,) in text_rows]

    try:
        stats = own_articles.compute_cite_stats(
            db=db, project_id=project_id, days=days, start=start, end=end,
            selected_platforms=selected,
            selected_prompt_texts=selected_prompt_texts,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    articles = db.execute(
        select(OwnArticle)
        .where(OwnArticle.project_id == project_id)
        # MySQL: ``ORDER BY x DESC`` 默认 NULL 排最后,无需 ``.nulls_last()``
        # (SQLAlchemy 2 的 nulls_last() 直接拼成 ``NULLS LAST``,MySQL 1064 语法错)。
        .order_by(OwnArticle.publish_date.desc(), OwnArticle.id.desc())
    ).scalars().all()

    items: list[OwnArticleOut] = []
    for a in articles:
        s = stats.get(own_articles.normalize_url(a.url), {})
        last = s.get("last_cited")
        last_str = last.strftime("%Y-%m-%d %H:%M") if last else "—"
        items.append(OwnArticleOut(
            id=a.id,
            url=a.url,
            title=a.title,
            publish_date=a.publish_date,
            remind=a.remind,
            created_at=a.created_at,
            cited=bool(s),
            cite_count=s.get("count", 0),
            cite_models=sorted(s.get("models") or []),
            last_cited=last_str,
        ))
    return OwnArticleListOut(items=items, total=len(items))


@router.post(
    "/projects/{project_id}/own-articles/import/preview",
    response_model=OwnArticleImportPreview,
)
async def preview_own_articles_import(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """xlsx 预览 —— 解析 + 校验 + 与 DB diff,不入库。

    xlsx 列固定 3 列:URL / 标题 / 发布日期(首行为表头)。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    content = await _read_xlsx(file)
    return own_articles.preview_import(db, project_id, content)


@router.post(
    "/projects/{project_id}/own-articles/import",
    response_model=OwnArticleImportResult,
)
async def import_own_articles(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """xlsx 应用 —— 单事务 upsert。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    content = await _read_xlsx(file)
    return own_articles.apply_import(db, project_id, content)


@router.post(
    "/projects/{project_id}/own-articles/{article_id}/remind",
    response_model=OwnArticleOut,
)
def toggle_own_article_remind(
    project_id: int,
    article_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """切换单条自有文章的「引用提醒」boolean。

    - 命中:翻转 ``remind``,返回最新 Out(不附 cite 统计 —— toggle 走
      局部刷新,前端拿到 id 后再走 list 接口取最新 stats)。
    - 找不到对应项目下的文章 → 404。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    a = db.get(OwnArticle, article_id)
    if a is None or a.project_id != project_id:
        raise HTTPException(404, "article not found")
    a.remind = not a.remind
    db.commit()
    return OwnArticleOut.model_validate(a)


@router.delete(
    "/projects/{project_id}/own-articles/{article_id}",
    status_code=204,
)
def delete_own_article(
    project_id: int,
    article_id: int,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """删除单条自有文章声明(不影响历史 citation_list_json 数据)。"""
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    a = db.get(OwnArticle, article_id)
    if a is None or a.project_id != project_id:
        raise HTTPException(404, "article not found")
    db.delete(a)
    db.commit()
    return None


async def _read_xlsx(file: UploadFile) -> bytes:
    """校验扩展名 + 大小 + 可解析性 —— 任何失败都抛 400 而非 500。"""
    name = (file.filename or "").lower()
    if not name.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="only .xlsx files supported")
    content = await file.read()
    if len(content) > _OWN_ARTICLES_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 5MB)")
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        import openpyxl
        openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True).close()
    except Exception as exc:  # BadZipFile / InvalidFileException / zipfile 各种
        raise HTTPException(status_code=400, detail=f"invalid .xlsx: {exc}") from exc
    return content
