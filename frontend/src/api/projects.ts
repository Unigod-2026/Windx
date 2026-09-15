import client from "./client";

export interface SlotOut {
  slot_index: number;
  hour: number;
  minute: number;
}

export interface RunSummary {
  id: number;
  status: "queued" | "running" | "success" | "failed" | "skipped";
  triggered_at: string;
  finished_at: string | null;
}

/** 项目「形态信息」(与 wizard 提交流程的 WizardSemantic 同形,
 *  active/disabled 行的 modal 也读这个字段反推 wizard state)。 */
export interface SemanticInfo {
  selling_points: string[];
  website: string | null;
  phone: string | null;
  address: string | null;
  email: string | null;
  wechat_service: string | null;
  wechat_official: string | null;
  xiaohongshu: string | null;
  douyin: string | null;
  weibo: string | null;
  custom: string | null;
}

export interface ProjectOut {
  id: number;
  customer_id: number;
  name: string;
  code: string;
  /** Lifecycle status. ``pending`` and ``rejected`` are the new wizard
   *  workflow values introduced in the 20260908_0002 migration —
   *  pre-existing rows are ``active`` / ``disabled``. */
  status: "pending" | "active" | "rejected" | "disabled";
  description: string | null;
  schedule_enabled: boolean;
  // v4 weekly schedule: per-mode map keyed by ``"fast"`` / ``"think"``.
  // Replaces the old ``monitor_freq`` / ``monitor_days`` pair so a project
  // can monitor fast / think platforms on independent weekly cadences.
  // Each value carries the same shape (``freq`` UI hint + ``days``
  // ISO weekday keys); an empty / missing key means "this mode is not
  // scheduled".
  monitor_schedule: Partial<Record<WizardMode, WizardMonitorEntry>>;
  slots: SlotOut[];
  next_run_at: string | null;
  brand: string | null;
  aliases: string[] | null;
  category_taxonomy: string[] | null;
  prompts_count: number;
  created_at: string;
  updated_at: string;
  // ===== Review workflow metadata (post 20260908_0002) =====
  review_note: string | null;
  submitted_by: number | null;
  submitted_at: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  approved_by: number | null;
  approved_at: string | null;
  /** 形态信息(联系方式等),与 wizard ``WizardPayload.semantic`` 同形;
   *  active/disabled 行的 modal 反推 wizard state 时也读这个。 */
  semantic_json: SemanticInfo | null;
  /** Verbatim wizard payload JSON, kept on the row for audit + edit-pending
   *  rehydrate. UI only renders this on the 待审核 page. */
  wizard_payload_json: string | null;
}

// ``mode`` is the LLM mode forwarded to the remote — only the four values
// https://github.com/molizhishu/molizhishu-api-pub/blob/main/docs/api/submit-task.md
// §平台 lists are accepted. ``delivery_mode`` is
// frontend-only (the live remote has no surface field); it's stored locally
// but NOT in the submit payload.
export type LlmMode = "standard" | "reasoning" | "search" | "reasoning_search";

export interface ProjectPlatform {
  /** 逻辑模型名(永远是 WIZARD_MODELS 的 ``value``,例如 ``qianwen``),
   * 不随 web/mobile 变 — UI 用它分组。 */
  platform: string;
  /** 远端 API 平台代码:web = ``value``,mobile = ``mobileCode``(例如
   * ``qianwen`` / ``qianwen_mobile``)。scheduler 原样转发给模力 API。
   * PUT 时不传会被后端用 ``platform`` 兜底,但显式传值更稳。 */
  platform_code?: string;
  mode: LlmMode;
  delivery_mode: "web" | "mobile";
  thinking_mode: boolean;
  screenshot: number;
  sort?: number;
  id?: number;
}

export interface ProjectDetailOut extends ProjectOut {
  prompts: PromptOut[];
  keywords: string[];
  platforms: ProjectPlatform[];
  sentiment_enabled: boolean;
  region_strategy: "fixed" | "national_random";
  region_codes: string[] | null;
}

export interface PromptOut {
  id: number;
  prompt: string;
  category: string | null;
  status: "monitoring" | "paused" | "archived";
  sort: number;
}

export interface PromptInPayload {
  prompt: string;
  category?: string | null;
  status?: "monitoring" | "paused" | "archived";
}

export type CompetitorOrigin = "manual" | "auto_discovered";
export type CompetitorStatus = "confirmed" | "pending" | "dismissed";

export interface ProjectList {
  items: ProjectOut[];
  total: number;
  page: number;
  size: number;
}

export interface ScheduleOut {
  project_id: number;
  schedule_enabled: boolean;
  // Per-mode map; empty object when the schedule is disabled.
  monitor_schedule: Partial<Record<WizardMode, WizardMonitorEntry>>;
  slots: SlotOut[];
  next_run_at: string | null;
  last_run: RunSummary | null;
}

export interface ScheduleRunOut {
  id: number;
  project_id: number;
  slot_index: number;
  trigger_type: "cron" | "manual";
  /** ``"fast"`` / ``"think"`` for cron-driven runs, ``""`` for manual
   *  triggers. The dashboard splits runs by mode in the UI; the
   *  scheduler uses it to compute mode-aware cooldown keys. */
  mode: string;
  status: "queued" | "running" | "success" | "failed" | "skipped";
  triggered_at: string;
  started_at: string | null;
  finished_at: string | null;
  task_id: string | null;
  error_message: string | null;
  success_count: number;
  failed_count: number;
  partial_count: number;
  total_count: number;
}

export interface ScheduleRunList {
  items: ScheduleRunOut[];
  total: number;
  page: number;
  size: number;
}

export interface ProjectTaskOut {
  task_id: string;
  status: string;
  total_items: number | null;
  completed_items: number | null;
  failed_items: number | null;
  project_id: number | null;
  schedule_run_id: number | null;
  created_local_at: string | null;
  remote_completed_at: string | null;
}

export interface ProjectTaskList {
  items: ProjectTaskOut[];
  total: number;
  page: number;
  size: number;
}

export interface SubtaskOut {
  subtask_id: string;
  task_id: string;
  platform: string | null;
  mode: string | null;
  prompt: string | null;
  status: string | null;
  error_message: string | null;
  page_screenshot: string | null;
}

export interface SubtaskList {
  items: SubtaskOut[];
  total: number;
}

export interface PromptAnswerOut {
  subtask_id: string;
  task_id: string;
  platform: string | null;
  mode: string | null;
  status: string | null;
  error_message: string | null;
  created_local_at: string | null;
  /** Sliced to ``preview_chars`` characters (default 200). The full text
   *  lives behind :class:`PromptAnswerDetailOut` and is only fetched when
   *  the operator opens 展开全部. */
  answer_content: string | null;
  /** Total length of the original answer (before slicing). Used to render
   *  the "展开全部 (N 字)" affordance without a second fetch. */
  answer_length: number;
  /** True when ``answer_content`` was truncated for this row. */
  truncated: boolean;
  /** 自有品牌(``is_self=true``)在该回答里的位次 — 数据真源是 LLM 抽取返回的
   *  ``raw.allRankings``,由后端 ``_find_competitor_rank`` 写入
   *  ``BrandMention.rank_position``。UI 在 raw sub-tab 每张卡片底部显示
   *  「品牌第 N 位」徽章。 */
  self_rank: number | null;
  /** LLM 抽取的自身品牌情感倾向:"positive" / "neutral" / "negative" / null。 */
  self_sentiment: string | null;
  /** 本回答里的全品牌排名(LLM ``raw.allRankings``)—— 数据真源在
   *  ``geo_subtasks.raw_result_json`` 上,后端 list 端点一次性带回。UI 在 raw
   *  sub-tab 每张卡片底部按 allRankings 顺序缩略展示,hover Tooltip 看完整
   *  列表。无数据时为 null(抽取失败 / 平台未返回)。 */
  all_rankings: Array<{ name: string; rank: number }> | null;
}

/** Single-subtask full payload, fetched on demand for 展开全部. Adds the
 *  heavy fields the list intentionally omits — full text, page screenshot,
 *  and the structured-payload JSON. */
export interface PromptAnswerDetailOut extends PromptAnswerOut {
  page_screenshot: string | null;
  // Structured payload from the AI backend — shape varies by upstream.
  reference_list: Array<Record<string, unknown>> | null;
  // Most platforms return plain URL strings; yuanbao returns structured
  // citation objects ({url, title, site, icon, index, summary}). Match
  // reference_list: accept anything shaped like a record.
  citation_list: Array<string | Record<string, unknown>> | null;
  reasoning_process: unknown | null;
  media_content: Array<Record<string, unknown>> | null;
  recommended_questions: Array<string | Record<string, unknown>> | null;
}

export interface PromptAnswerList {
  items: PromptAnswerOut[];
  total: number;
}

/** Response wrapper for :func:`getSubtaskDetail` — the route returns the
 *  detail object directly, so the wrapper is just a type-level marker. */
export type PromptAnswerDetail = PromptAnswerDetailOut;

export interface TriggerOut {
  run_id: number;
  /** 当项目同时存在 fast 和 think 平台行时,后端会拆成两个 ScheduleRun,这是第二个 run 的 id;单模式项目为 null。 */
  think_run_id: number | null;
  status: "queued" | "skipped";
}

export interface ProjectCreatePayload {
  name: string;
  code: string;
  description?: string | null;
  sentiment_enabled?: boolean;
  region_strategy?: "fixed" | "national_random";
  region_codes?: string[] | null;
  brand?: string | null;
  aliases?: string[] | null;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string | null;
  status?: "active" | "disabled";
  sentiment_enabled?: boolean;
  region_strategy?: "fixed" | "national_random";
  region_codes?: string[] | null;
  brand?: string | null;
  aliases?: string[] | null;
  category_taxonomy?: string[] | null;
  category_renames?: Record<string, string> | null;
  /** 「语义监控」卡片内容(核心卖点 / 官网 / 微信 / 自定义 等)。
   *  写入 ``geo_projects.semantic_json``;空对象/null 表示清空。 */
  semantic_json?: SemanticInfo | null;
}

export interface SlotIn {
  hour: number;
  minute: number;
}

export interface ScheduleUpdatePayload {
  slots: SlotIn[];
  schedule_enabled?: boolean;
}

export interface ScheduleStatusUpdatePayload {
  status: "enabled" | "disabled";
}

export interface PlatformsUpdatePayload {
  platforms: ProjectPlatform[];
}

export interface CompetitorOut {
  id: number;
  project_id: number;
  name: string;
  note: string | null;
  aliases: string[] | null;
  sort: number;
  origin: CompetitorOrigin;
  status: CompetitorStatus;
  created_at: string;
  updated_at: string;
}

export interface CompetitorList {
  items: CompetitorOut[];
  total: number;
}

export interface CompetitorPayload {
  name: string;
  note?: string | null;
  aliases?: string[] | null;
  origin?: CompetitorOrigin;
  status?: CompetitorStatus;
}

export interface PromptsUpdatePayload {
  prompts: PromptInPayload[];
}

export interface KeywordsUpdatePayload {
  keywords: string[];
}

// ------------------------------------------------------------------
// Brand mentions (drives overview tab + per-question drill-down)
// ------------------------------------------------------------------

export type ExtractStatus = "pending" | "success" | "failed" | "skipped";

export interface BrandMentionOut {
  id: number;
  subtask_id: string;
  project_id: number;
  customer_id: number;
  prompt: string | null;
  platform: string | null;
  brand: string;
  is_self: boolean;
  is_mention: number;
  rank_position: number | null;
  // "positive" / "neutral" / "negative" — the API-pass refactor writes
  // the Molizhishu label directly; the dashboard KPI layer translates
  // to a float average for the color buckets.
  sentiment: string | null;
  is_recommended: boolean | null;
  // Self rows carry a single snippet from the API's mentionContext.
  concern_hits_json: Array<{ text: string }> | null;
  extract_status: ExtractStatus;
  extract_error: string | null;
  created_at: string;
}

export interface BrandMentionList {
  items: BrandMentionOut[];
  total: number;
}

export interface BrandMentionSummary {
  project_id: number;
  total_mentions: number;
  top1_rate: number;
  top3_rate: number;
  coverage: number;
  avg_sentiment: number | null;
  pending_count: number;
  failed_count: number;
}

export interface ListProjectsParams {
  page?: number;
  size?: number;
  customer_id?: number;
  /** Pre-20260908_0002 surface only accepted ``active`` / ``disabled``.
   *  The merged-table API now exposes ``pending`` / ``rejected`` too; the
   *  wire value is forwarded verbatim so the project list and the
   *  pending-review list both hit ``GET /api/projects`` with different
   *  filters. */
  status?: "active" | "disabled" | "pending" | "rejected";
  /** 「监控项目」列表按调度开关过滤:启用=正在跑,停用=暂停调度。
   *  与 status 独立 —— status=active 的项目里也可能有 schedule_enabled=false。 */
  schedule_enabled?: boolean;
  q?: string;
}

export const listProjects = (params: ListProjectsParams) =>
  client.get<ProjectList>("/projects", { params }).then((r) => r.data);

export interface LlmPricingOut {
  cost_per_call: number;
  currency: string;
  unit: string;
}

export const getLlmPricing = () =>
  client.get<LlmPricingOut>("/config/llm-pricing").then((r) => r.data);

export const getProject = (id: number) =>
  client.get<ProjectDetailOut>(`/projects/${id}`).then((r) => r.data);

export const createProject = (customerId: number, data: ProjectCreatePayload) =>
  client
    .post<ProjectOut>(`/customers/${customerId}/projects`, data)
    .then((r) => r.data);

export const updateProject = (id: number, data: ProjectUpdatePayload) =>
  client.put<ProjectOut>(`/projects/${id}`, data).then((r) => r.data);

export const deleteProject = (id: number) =>
  client.delete(`/projects/${id}`).then((r) => r.data);

export const getSchedule = (id: number) =>
  client.get<ScheduleOut>(`/projects/${id}/schedule`).then((r) => r.data);

export const updateSchedule = (id: number, data: ScheduleUpdatePayload) =>
  client.put<ScheduleOut>(`/projects/${id}/schedule`, {
    schedule_enabled: data.schedule_enabled ?? false,
    slots: data.slots,
  }).then((r) => r.data);

// v4 weekly schedule shape — separate from `updateSchedule` because the
// slot-based `ScheduleUpdatePayload` is still used by BatchQuestionModal
// and the two wire shapes are not interchangeable on the backend.
export interface WeeklyScheduleUpdate {
  schedule_enabled: boolean;
  // Per-mode map; ``null`` / missing key means "don't touch this mode".
  monitor_schedule: Partial<Record<WizardMode, WizardMonitorEntry | null>>;
}

export const putWeeklySchedule = (id: number, data: WeeklyScheduleUpdate) =>
  client
    .put<ScheduleOut>(`/projects/${id}/schedule`, data)
    .then((r) => r.data);

export const toggleSchedule = (id: number, scheduleEnabled: boolean) =>
  client
    .put<ScheduleOut>(`/projects/${id}/schedule/status`, {
      status: scheduleEnabled ? "enabled" : "disabled",
    })
    .then((r) => r.data);

export const triggerRun = (id: number) =>
  client.post<TriggerOut>(`/projects/${id}/schedule/trigger`).then((r) => r.data);

export const listRuns = (
  id: number,
  params: { page?: number; size?: number; status?: string } = {},
) =>
  client
    .get<ScheduleRunList>(`/projects/${id}/runs`, { params })
    .then((r) => r.data);

export const getTasks = (
  id: number,
  params: { page?: number; size?: number; status?: string } = {},
) =>
  client
    .get<ProjectTaskList>(`/projects/${id}/tasks`, { params })
    .then((r) => r.data);

export const getTaskSubtasks = (projectId: number, taskId: string) =>
  client
    .get<SubtaskList>(`/projects/${projectId}/tasks/${taskId}/subtasks`)
    .then((r) => r.data);

/** All AI answers generated for a single project prompt, newest first.
 *  ``days`` is the default preset; ``start``/``end`` (inclusive YYYY-MM-DD)
 *  win over ``days`` when provided. ``platform`` narrows to one model so
 *  the 查看原文 modal only shows the row that was clicked. The list
 *  payload is intentionally lightweight: ``answer_content`` is sliced
 *  to ``preview_chars`` (default 200) and the structured-payload JSON
 *  columns are stripped — see :class:`PromptAnswerDetailOut` and
 *  :func:`getSubtaskDetail` for the on-demand full payload. */
export const listPromptAnswers = (
  projectId: number,
  promptId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    /** Legacy single-model filter (raw modelCode). Used by QuestionTab
     *  查看原文 modal; 新代码请用 platforms. */
    platform?: string;
    /** Toolbar 「模型」多选 —— compound key 列表
     *  (`<base>__<delivery>__<thinking>`,例 `deepseek__web__fast`)。
     *  后端先按 platform_code SQL IN 收窄,再按 compound key 在 Python 里
     *  post-filter(同 base 不同档位的子集)。传空数组 = 显式「筛 0 个」,
     *  后端直接返回空集。 */
    platforms?: string[];
    preview_chars?: number;
  } = {},
) => {
  const { platforms, ...rest } = params;
  const queryParams: Record<string, unknown> = { ...rest };
  if (platforms !== undefined) {
    queryParams.platforms = platforms;
  }
  return client
    .get<PromptAnswerList>(`/projects/${projectId}/prompts/${promptId}/answers`, {
      params: queryParams,
      paramsSerializer: {
        indexes: null, // axios ≥1.x: 序列化成 ?platforms=a&platforms=b
      },
    })
    .then((r) => r.data);
};

/** Single-subtask full payload, fetched when the operator opens
 *  展开全部 on a list-row card. Returns the untruncated ``answer_content``,
 *  ``page_screenshot``, and all structured-payload JSON (references,
 *  citations, reasoning trace, media, recommended questions). */
export const getSubtaskDetail = (subtaskId: string) =>
  client
    .get<PromptAnswerDetail>(`/subtasks/${subtaskId}`)
    .then((r) => r.data);

export const putPrompts = (id: number, prompts: PromptInPayload[]) =>
  client
    .put<{ ok: boolean; count: number; dropped_categories?: string[] }>(
      `/projects/${id}/prompts`,
      { prompts },
    )
    .then((r) => r.data);

export const putKeywords = (id: number, keywords: string[]) =>
  client
    .put<{ ok: boolean; count: number }>(`/projects/${id}/keywords`, { keywords })
    .then((r) => r.data);

export const putPlatforms = (id: number, platforms: ProjectPlatform[]) =>
  client
    .put<{ ok: boolean; count: number }>(`/projects/${id}/platforms`, {
      platforms,
    })
    .then((r) => r.data);

export const listCompetitors = (projectId: number) =>
  client
    .get<CompetitorList>(`/projects/${projectId}/competitors`)
    .then((r) => r.data);

export const createCompetitor = (projectId: number, payload: CompetitorPayload) =>
  client
    .post<CompetitorOut>(`/projects/${projectId}/competitors`, payload)
    .then((r) => r.data);

export const updateCompetitor = (
  projectId: number,
  competitorId: number,
  payload: CompetitorPayload,
) =>
  client
    .put<CompetitorOut>(
      `/projects/${projectId}/competitors/${competitorId}`,
      payload,
    )
    .then((r) => r.data);

export const deleteCompetitor = (projectId: number, competitorId: number) =>
  client
    .delete(`/projects/${projectId}/competitors/${competitorId}`)
    .then((r) => r.data);

export const listBrandMentions = (
  projectId: number,
  params: {
    page?: number;
    size?: number;
    is_self?: boolean;
    brand?: string;
    days?: number;
    start?: string;
    end?: string;
  } = {},
) =>
  client
    .get<BrandMentionList>(`/projects/${projectId}/brand-mentions`, { params })
    .then((r) => r.data);

export const getBrandMentionsSummary = (projectId: number, days = 15) =>
  client
    .get<BrandMentionSummary>(
      `/projects/${projectId}/brand-mentions/summary`,
      { params: { days } },
    )
    .then((r) => r.data);

export interface QuestionPlatformStat {
  /**
   * Compound key ``${platform_code}__${delivery}__${thinking}`` —— 1 行
   * = 1 个 (platform_code, delivery_mode, thinking_mode) 三元组,与
   * ProjectPlatform 行一一对应。fast/think 与 web/mobile 不再合并,跟
   * Overview 的 trend / ranking / model_dimensions 同口径。
   */
  platform: string;
  delivery_mode?: "web" | "mobile";
  thinking_mode?: boolean;
  matched: number;
  total: number;
  best_rank: number | null;
  avg_sentiment: number | null;
  recommend_yes: boolean;
  // Populated when ``view=competitor`` — the dominant competitor
  // brand that drove the aggregation for this (prompt, triple).
  brand?: string | null;
  // Per-triple prev-window numbers,模型对比表行内环比 pill 用。
  prev_matched?: number;
  prev_total?: number;
  prev_top1_rate?: number;
  prev_top3_rate?: number;
  prev_mention_rate?: number;
}

export interface QuestionPrevStat {
  total: number;
  matched: number;
  top1_rate: number;
  top3_rate: number;
  mention_rate: number;
  rank_avg: number | null;
}

export interface PlatformExcerpt {
  excerpt: string | null;
  rank: number | null;
  run_id: string | null;
}

export interface CategoryStat {
  category: string | null;
  prompt_count: number;
  mention_rate: number;
  top1_rate: number;
  top3_rate: number;
}

export interface CompetitorBrandStat {
  brand: string;
  is_self: boolean;
  color: string;
  mention_rate: number;
  top1_rate: number;
  top3_rate: number;
  avg_rank: number | null;
  model_ranks: Record<string, number | null>;
}

export interface QuestionCompetitorOut {
  prompt_id: number;
  brands: CompetitorBrandStat[];
}

export interface QuestionSummaryItem {
  prompt_id: number;
  prompt: string;
  category: string | null;
  status: string;
  total: number;
  matched: number;
  mention_rate: number;
  top1_rate: number;
  top3_rate: number;
  rank_avg: number | null;
  coverage: number;
}

export interface QuestionSummaryOut {
  project_id: number;
  start: string;
  end: string;
  items: QuestionSummaryItem[];
  category_summary: CategoryStat[];
}

export interface QuestionProductAnalyticsOut {
  project_id: number;
  prompt_id: number;
  start: string;
  end: string;
  platforms: QuestionPlatformStat[];
  prev: QuestionPrevStat | null;
  long_prev: QuestionPrevStat | null;
  excerpts: Partial<Record<string, PlatformExcerpt | null>>;
}

export interface QuestionCompetitorAnalyticsOut {
  project_id: number;
  prompt_id: number;
  start: string;
  end: string;
  brands: CompetitorBrandStat[];
  excerpts: Partial<Record<string, PlatformExcerpt | null>>;
}

export interface QuestionWindowParams {
  days?: number;
  start?: string;
  end?: string;
  /** Toolbar 切档 —— compound key 列表,逗号分隔 */
  platforms?: string[];
}

export interface QuestionStableItem {
  prompt_id: number;
  prompt: string;
  category: string | null;
  /**
   * 列出该 prompt 在当前窗口被提及的所有档位 —— 元素是 compound key
   * ``${platform_code}__${delivery}__${thinking}``,与 ProjectPlatform
   * 行一一对应。改前是 raw modelCode,改后 ``platformLabel`` 直接渲染。
   */
  platforms: string[];
}

export interface DropEvent {
  prompt_id: number;
  prompt: string;
  category: string | null;
  /**
   * Compound key ``${platform_code}__${delivery}__${thinking}``,与
   * Overview / 模型对比表 / 摘录 同口径。改前是 raw modelCode;
   * 改后前端用 ``platformLabel(triple)`` 直接渲染「千问-网页-快速」格式。
   */
  triple: string;
  delivery_mode?: "web" | "mobile";
  thinking_mode?: boolean;
  dropped_day: string;
  from_rank: number | null;
  to_rank: number | null;
  reason: string | null;
}

export interface QuestionStatusChangesOut {
  project_id: number;
  start: string;
  end: string;
  stable: QuestionStableItem[];
  drops: DropEvent[];
  never_listed: QuestionStableItem[];
  listed: QuestionStableItem[];
}

/**
 * 稳定与掉落面板 — 服务端把每个 (prompt, triple) 划入 4 个独立集合:
 *   - ``stable``: 上一窗口 + 当前窗口都有提及
 *   - ``drops``: 上一窗口有,当前窗口掉出 Top-3 或消失(per 事件)
 *   - ``never_listed``: 双窗口都没出现过
 *   - ``listed``: 当前窗口至少被一个模型提过
 */
export const getQuestionStatusChanges = (
  projectId: number,
  params: QuestionWindowParams = {},
) =>
  client
    .get<QuestionStatusChangesOut>(
      `/projects/${projectId}/questions/status-changes`,
      {
        params: {
          ...params,
          platforms: params.platforms ? params.platforms.join(",") : undefined,
        },
      },
    )
    .then((r) => r.data);

/** 问题列表摘要 — 轻量聚合(每个 prompt 一行 + 分类汇总)。
 *  用作「问题表格」首屏渲染,避免一次性加载完整 analytics。 */
export const getQuestionSummary = (
  projectId: number,
  params: QuestionWindowParams = {},
) =>
  client
    .get<QuestionSummaryOut>(
      `/projects/${projectId}/questions/summary`,
      {
        params: {
          ...params,
          platforms: params.platforms ? params.platforms.join(",") : undefined,
        },
      },
    )
    .then((r) => r.data);

/** 单问题产品视角 — 4 张 KPI 卡 + 模型对比表 + excerpt。
 *  替代之前在 QuestionTab 内的 client-side useMemo 重算。 */
export const getQuestionProductAnalytics = (
  projectId: number,
  promptId: number,
  params: QuestionWindowParams = {},
) =>
  client
    .get<QuestionProductAnalyticsOut>(
      `/projects/${projectId}/questions/${promptId}/product-analytics`,
      {
        params: {
          ...params,
          platforms: params.platforms ? params.platforms.join(",") : undefined,
        },
      },
    )
    .then((r) => r.data);

/** 单问题竞品视角 — 各竞品 brand 在该问题的提及率 / 排名分布 + excerpt。 */
export const getQuestionCompetitorAnalytics = (
  projectId: number,
  promptId: number,
  params: QuestionWindowParams = {},
) =>
  client
    .get<QuestionCompetitorAnalyticsOut>(
      `/projects/${projectId}/questions/${promptId}/competitor-analytics`,
      {
        params: {
          ...params,
          platforms: params.platforms ? params.platforms.join(",") : undefined,
        },
      },
    )
    .then((r) => r.data);

export interface OverviewKpi {
  value: number;
  prev_value: number;
  delta_pct: number | null;
  spark: number[];
}

export interface OverviewTrendSeries {
  platform: string;
  data: number[];
}

export interface OverviewPlatformRank {
  platform: string;
  top1_rate: number;
  sample: number;
}

/** Per-platform rollup used by the 模型维度 sub-pane (2×2 grid).
 *  Mirrors the same shape as CompetitorKpi so the same chart helpers
 *  can render either dataset later if we want. ``sample`` is the raw
 *  subtask count for the platform in the window. */
export interface OverviewModelDimension {
  platform: string;
  mention_rate: number;
  top1_rate: number;
  top2_rate: number;
  top3_rate: number;
  sample: number;
}

export interface ProjectOverview {
  project_id: number;
  start: string;
  end: string;
  days: number;
  labels: string[];
  // 4 KPI cards (mirrors docs/更新版UI #tab-overview)
  mention_rate: OverviewKpi;
  top1_rate: OverviewKpi;
  top3_rate: OverviewKpi;
  correct_rate: OverviewKpi;
  // Detail numbers fed into each card's KPI-meta block
  total_mentions: OverviewKpi;
  question_count: OverviewKpi;
  answer_count: OverviewKpi;
  trend: OverviewTrendSeries[];
  ranking: OverviewPlatformRank[];
  model_dimensions: OverviewModelDimension[];
  pending_count: number;
  failed_count: number;
}

/** ``start``/``end`` are inclusive ``YYYY-MM-DD`` and win over ``days``.
 *  ``platforms`` 是 UI 「全局工具栏 → 模型」筛选的 modelCode 列表;
 *  ``prompt_ids`` 是 UI 「全局工具栏 → 问题」筛选的 ProjectPrompt.id 列表;
 *  ``thinking_mode`` 是 UI 「全局工具栏 → 模式」分桶(true/false);
 *  ``delivery_mode`` 是 UI 「全局工具栏 → 终端」分桶(web/mobile)。
 *  空数组 / 缺省 = 不筛,与后端原口径一致。 */
export const getProjectOverview = (
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    platforms?: string[];
    prompt_ids?: number[];
    thinking_mode?: ("fast" | "think")[];
    delivery_mode?: ("web" | "mobile")[];
  } = {},
) =>
  client
    .get<ProjectOverview>(`/projects/${projectId}/overview`, {
      params: {
        ...params,
        // platforms 区分 null (「全选」→ 不传) vs [] (「全不选」→ 传空字符串,
// 后端 SQLAlchemy in_([]) 渲染成 `1 != 1`,返回 0 行,语义对齐 prompt_ids)。
platforms: params.platforms ? params.platforms.join(",") : undefined,
        prompt_ids: params.prompt_ids?.length ? params.prompt_ids.join(",") : undefined,
        thinking_mode: params.thinking_mode?.length
          ? params.thinking_mode
              .map((m) => (m === "fast" ? "false" : "true"))
              .join(",")
          : undefined,
        delivery_mode: params.delivery_mode?.length
          ? params.delivery_mode.join(",")
          : undefined,
      },
    })
    .then((r) => r.data);

// ------------------------------------------------------------------
// Competitor analysis (data tab → 竞品分析)
// ------------------------------------------------------------------

export interface CompetitorKpi {
  brand: string;
  name: string;
  aliases: string[] | null;
  is_self: boolean;
  is_mention: number;
  mention_rate: number;
  top3_rate: number;
  recommend_rate: number;
  avg_sentiment: number | null;
  avg_rank: number | null;
  /** 15-day sparkline, zero-filled, ordered oldest → newest. */
  spark: number[];
  /** Top1 提及率(= rank_position=1 且 is_mention>0 的次数 / total_subtasks) */
  top1_rate: number;
  /** 情感三档占比(分母 = is_mention>0 的样本数) */
  sentiment_positive: number;
  sentiment_neutral: number;
  sentiment_negative: number;
  /** 环比 vs 同长度上一窗口;窗口太短或无数据为 null */
  mention_rate_delta: number | null;
  top1_rate_delta: number | null;
  top3_rate_delta: number | null;
  sentiment_delta: number | null;
}

export interface CompetitorTrendSeries {
  brand: string;
  name: string;
  is_self: boolean;
  color: string;
  data: number[];
}

export interface CompetitorTrendBlock {
  labels: string[];
  series: CompetitorTrendSeries[];
}

export interface QuadrantPoint {
  /** Compound key: ``${platform_code}__${delivery_mode}__${thinking}``。 */
  platform: string;
  delivery_mode: "web" | "mobile" | null;
  thinking_mode: boolean | null;
  self_mention_rate: number;
  competitor_avg_mention_rate: number;
}

export interface ModelDiff {
  /** Compound key: ``${platform_code}__${delivery_mode}__${thinking}``。
   *  2026-09 起按 triple 拆,与 Overview / 问题提及分析 tab 口径一致;
   *  前端用 ``platformLabel`` 渲染展示名。 */
  platform: string;
  delivery_mode: "web" | "mobile" | null;
  thinking_mode: boolean | null;
  self_mention_rate: number;
  self_top1_rate: number;
  self_top3_rate: number;
  competitor_mention_rate: number;
  competitor_top1_rate: number;
  competitor_top3_rate: number;
}

export interface DiffCore {
  labels: string[];
  self: number[];
  competitor_avg: number[];
}

export interface CompetitorAnalysisOut {
  project_id: number;
  start: string;
  end: string;
  days: number;
  total_subtasks: number;
  self_brand: CompetitorKpi | null;
  competitors: CompetitorKpi[];
  trend: CompetitorTrendBlock;
  diff_core: DiffCore;
  diff_model: ModelDiff[];
  diff_quadrant: QuadrantPoint[];
  previous_window_start: string | null;
  previous_window_end: string | null;
}

/** 竞品分析 — 近 15 天默认。``start``/``end`` (inclusive ``YYYY-MM-DD``) win over ``days``。
 *  ``platforms`` 是 toolbar 的模型筛选(逗号分隔的 compound key,每个 key 已带
 *  ``${code}__${delivery}__${thinking}``);``prompt_ids`` 是 toolbar 的问题筛选。 */
export const getCompetitorAnalysis = (
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    platforms?: string[];
    prompt_ids?: number[];
  } = {},
) =>
  client
    .get<CompetitorAnalysisOut>(`/projects/${projectId}/competitor-analysis`, {
      params: {
        days: params.days,
        start: params.start,
        end: params.end,
        platforms: params.platforms?.join(","),
        prompt_ids: params.prompt_ids?.join(","),
      },
    })
    .then((r) => r.data);

// ------------------------------------------------------------------
// Citation analysis (data tab → 引用源分析)
// ------------------------------------------------------------------

export interface CitationOut {
  url: string;
  site: string;
  title: string | null;
  /** Domain classifier bucket from the backend. Known labels match
   * ``CITATION_TYPE_KEYS`` in ``app/schemas/project.py``; unknown ones
   * fall back to "其他". */
  type: string;
  count: number;
  avg_rank: number | null;
  platforms: string[];
  first_seen: string;
  last_seen: string;
}

export interface CitationAnalysisOut {
  project_id: number;
  start: string;
  end: string;
  days: number;
  total_citations: number;
  unique_urls: number;
  /** type → total citation rows (so the secondary tabs can render the
   * counts without re-aggregating). */
  type_counts: Record<string, number>;
  items: CitationOut[];
}

/** 引用源分析 — 窗口可调(7/15/30 天,后端上限 90)。 */
export const getCitationAnalysis = (
  projectId: number,
  params: { days?: number } = {},
) =>
  client
    .get<CitationAnalysisOut>(
      `/projects/${projectId}/citation-analysis`,
      { params },
    )
    .then((r) => r.data);

export interface SourcePreferenceKpi {
  total_references: number;
  unique_urls: number;
  cross_platform_urls: number;
  avg_refs_per_subtask: number;
  total_subtasks: number;
}

export interface SourceTypeSlice {
  type: string;
  count: number;
}

export interface SourcePlatformSlice {
  platform: string;
  total_refs: number;
  unique_urls: number;
}

export interface SourceTrendDay {
  date: string;
  new_urls: number;
  lost_urls: number;
}

export interface SourcePreferenceItem {
  url: string;
  site: string;
  title: string | null;
  type: string;
  count: number;
  platforms: string[];
  first_seen: string;
  last_seen: string;
}

export interface SourceMediaTop {
  /** 媒体名(取自 reference_list_json.site,中文显示名)。 */
  media_name: string;
  count: number;
  type: string;
  sample_url: string;
  sample_title: string | null;
}

export interface SourceByModelTop {
  /** Compound key ``<code>__<delivery>__<thinking>``,对齐
   *  GlobalToolbar 模型 dropdown 的取值(如 ``qianwen__web__fast``)。 */
  platform: string;
  items: SourceMediaTop[];
}

export interface SourceStableItem {
  url: string;
  site: string;
  title: string | null;
  type: string;
  count: number;
  model_count: number;
  total_models: number;
  first_seen: string;
  last_seen: string;
}

export interface SourceTrendPlatform {
  platform: string;
  days: SourceTrendDay[];
}

export interface SourceSuggestion {
  icon: "focus" | "chart-line" | "swap" | "warning";
  title: string;
  content: string;
}

export interface SourcePreferenceOut {
  project_id: number;
  start: string;
  end: string;
  days: number;
  kpi: SourcePreferenceKpi;
  type_counts: SourceTypeSlice[];
  platform_slices: SourcePlatformSlice[];
  top_sources: SourcePreferenceItem[];
  trend: SourceTrendDay[];
  by_model_top: SourceByModelTop[];
  stable_sources: SourceStableItem[];
  trend_by_platform: SourceTrendPlatform[];
  suggestions: SourceSuggestion[];
}

export interface SourceDetailItem {
  url: string;
  site: string;
  title: string | null;
  type: string;
  count: number;
  platforms: string[];
  first_seen: string;
  last_seen: string;
}

export interface SourceDetailOut {
  project_id: number;
  start: string;
  end: string;
  items: SourceDetailItem[];
  total: number;
}

export interface VideoPlatformSlice {
  name: string;
  color: string;
  count: number;
  unique_urls: number;
  platforms: Record<string, number>;
  sources: string[];
}

export interface VideoSourceOut {
  project_id: number;
  start: string;
  end: string;
  total: number;
  platforms: VideoPlatformSlice[];
  by_model: SourcePlatformSlice[];
}

export interface SourceSelfKpi {
  unique_sources: number;
  total_citations: number;
  model_count: number;
  top_source_count: number;
}

export interface SourceSelfItem {
  url: string;
  site: string;
  title: string | null;
  count: number;
  platforms: string[];
}

export interface SourceSelfOut {
  project_id: number;
  start: string;
  end: string;
  kpi: SourceSelfKpi;
  by_model: SourcePlatformSlice[];
  items: SourceSelfItem[];
  suggestions: SourceSuggestion[];
}

/** 跟 :func:`getQuestionSummary` 同款日期范围参数对象 —— ``days`` 是默认预设;
 *  ``start``/``end``(inclusive YYYY-MM-DD)优先,对应 toolbar 「自定义」窗口。
 *  ``models``(逗号分隔的 compound key 列表)跟 GlobalToolbar dropdown 选中态
 *  对齐,用于补齐 by_model_top 空卡片。 */
export function getSourcePreferences(
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    models?: string[] | null;
    prompts?: number[] | null;
  } = {},
): Promise<SourcePreferenceOut> {
  const { days, start, end, models, prompts } = params;
  return client
    .get<SourcePreferenceOut>(
      `/projects/${projectId}/source-preferences`,
      {
        params: {
          days,
          start,
          end,
          ...(models && models.length ? { models: models.join(",") } : {}),
          ...(prompts && prompts.length ? { prompts: prompts.join(",") } : {}),
        },
      },
    )
    .then((r) => r.data);
}

/** 信源明细 sub-tab —— 后端一次返回窗口内全部 unique URL,
 *  前端做类型筛选 / 关键词搜索 / 排序 + 选中 → iframe 预览。 */
export function getSourceDetail(
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    models?: string[] | null;
    prompts?: number[] | null;
  } = {},
): Promise<SourceDetailOut> {
  const { days, start, end, models, prompts } = params;
  return client
    .get<SourceDetailOut>(
      `/projects/${projectId}/source-detail`,
      {
        params: {
          days,
          start,
          end,
          ...(models && models.length ? { models: models.join(",") } : {}),
          ...(prompts && prompts.length ? { prompts: prompts.join(",") } : {}),
        },
      },
    )
    .then((r) => r.data);
}

/** 视频类信源 sub-tab —— 后端只统计命中视频平台白名单(抖音 / B 站 /
 *  快手 / 西瓜 / YouTube / 优酷 / 腾讯视频 / 新浪视频)的引用,按视频
 *  平台分桶 + 按模型聚合,前端渲染顶部平台卡片网格 + 底部 ranking chart。*/
export function getVideoSources(
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    models?: string[] | null;
    prompts?: number[] | null;
  } = {},
): Promise<VideoSourceOut> {
  const { days, start, end, models, prompts } = params;
  return client
    .get<VideoSourceOut>(
      `/projects/${projectId}/source-video`,
      {
        params: {
          days,
          start,
          end,
          ...(models && models.length ? { models: models.join(",") } : {}),
          ...(prompts && prompts.length ? { prompts: prompts.join(",") } : {}),
        },
      },
    )
    .then((r) => r.data);
}

/** 自有文章引用分析 sub-tab —— 后端只统计 host 命中「自媒体」分类
 *  (抖音 / B 站 / 快手 等)的引用,提供 KPI + 按模型分布 + 信源列表 +
 *  运营建议。数据源与 source-video 共用,但聚合维度不同 —— 这里按
 *  model + URL 维度,视频类信源按 video platform 维度。*/
export function getSelfArticles(
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    models?: string[] | null;
    prompts?: number[] | null;
  } = {},
): Promise<SourceSelfOut> {
  const { days, start, end, models, prompts } = params;
  return client
    .get<SourceSelfOut>(
      `/projects/${projectId}/source-self`,
      {
        params: {
          days,
          start,
          end,
          ...(models && models.length ? { models: models.join(",") } : {}),
          ...(prompts && prompts.length ? { prompts: prompts.join(",") } : {}),
        },
      },
    )
    .then((r) => r.data);
}

// ------------------------------------------------------------------
// 自有文章引用分析(独立一级页面,表格视图)
//
// 对应 index.html:1293-1326 的 7 列表格:文章 / 发布日期 / 是否被引用 /
// 引用次数 / 引用模型 / 最近引用 / 引用提醒。每行 remind toggle;顶部有
// 「导入 URL 列表」xlsx 批量导入按钮。
// ------------------------------------------------------------------

export interface OwnArticleIn {
  url: string;
  title: string;
  publish_date: string | null;
}

export interface OwnArticleOut {
  id: number;
  url: string;
  title: string;
  publish_date: string | null;
  remind: boolean;
  created_at: string;
  cited: boolean;
  cite_count: number;
  cite_models: string[];
  last_cited: string;
}

export interface OwnArticleListOut {
  items: OwnArticleOut[];
  total: number;
}

export type OwnArticleInvalidReason =
  | "empty_url"
  | "invalid_url"
  | "duplicate_in_file";

export interface OwnArticleInvalidRow {
  row: number;
  raw_url: string;
  reason: OwnArticleInvalidReason;
}

export interface OwnArticleImportPreview {
  entries: OwnArticleIn[];
  new_urls: string[];
  update_urls: string[];
  invalid_rows: OwnArticleInvalidRow[];
}

export interface OwnArticleImportResult {
  inserted: number;
  updated: number;
  skipped: number;
  total_in_project: number;
}

export function getOwnArticles(
  projectId: number,
  params: {
    days?: number;
    start?: string;
    end?: string;
    models?: string[] | null;
    prompts?: number[] | null;
  } = {},
): Promise<OwnArticleListOut> {
  const { days, start, end, models, prompts } = params;
  return client
    .get<OwnArticleListOut>(`/projects/${projectId}/own-articles`, {
      params: {
        days,
        start,
        end,
        ...(models && models.length ? { models: models.join(",") } : {}),
        ...(prompts && prompts.length ? { prompts: prompts.join(",") } : {}),
      },
    })
    .then((r) => r.data);
}

function _postOwnArticlesFile(
  projectId: number,
  suffix: string,
  file: File,
): Promise<unknown> {
  const fd = new FormData();
  fd.append("file", file);
  return client
    .post(`/projects/${projectId}/own-articles/${suffix}`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
}

export function previewOwnArticlesImport(
  projectId: number,
  file: File,
): Promise<OwnArticleImportPreview> {
  return _postOwnArticlesFile(projectId, "import/preview", file) as Promise<OwnArticleImportPreview>;
}

export function importOwnArticles(
  projectId: number,
  file: File,
): Promise<OwnArticleImportResult> {
  return _postOwnArticlesFile(projectId, "import", file) as Promise<OwnArticleImportResult>;
}

export function toggleOwnArticleRemind(
  projectId: number,
  articleId: number,
): Promise<OwnArticleOut> {
  return client
    .post<OwnArticleOut>(
      `/projects/${projectId}/own-articles/${articleId}/remind`,
    )
    .then((r) => r.data);
}

export function deleteOwnArticle(
  projectId: number,
  articleId: number,
): Promise<void> {
  return client.delete<void>(`/projects/${projectId}/own-articles/${articleId}`).then(() => undefined);
}

// ------------------------------------------------------------------
// Wizard / review workflow (post 20260908_0002)
// ------------------------------------------------------------------

export type WizardDevice = "pc" | "mobile";
export type WizardMode = "fast" | "think";
export type WizardFreq = "w1" | "w2" | "wn";
export type WizardDay = "1" | "2" | "3" | "4" | "5" | "6" | "7";
export type WizardGeoMode = "national_random" | "fixed";
export type WizardSentiment = "on" | "off";

export interface WizardQuestion {
  text: string;
  category: string;
  tag: string | null;
}

export interface WizardBrand {
  name: string;
  product: string | null;
  aliases: string[];
}

export interface WizardCompetitor {
  name: string;
  product: string | null;
  aliases: string[];
}

/** Per-mode schedule entry — the inner shape of ``monitor_schedule``
 *  on the project row and the inner shape of each ``schedules`` value
 *  in the wizard payload. ``freq`` is the same UI hint it was in v2
 *  (``w1`` / ``w2`` / ``wn``); ``days`` are the ISO weekday keys. */
export interface WizardMonitorEntry {
  freq: WizardFreq;
  days: WizardDay[];
}

export interface WizardMonitor {
  /** PC / mobile — controls which ``ProjectPlatform`` rows the wizard
   *  expands on submit (web vs mobile surface). */
  devices: WizardDevice[];
  /** 快速 / 思考 — controls which ``ProjectPlatform`` rows the wizard
   *  expands on submit (thinking_mode flag). Both modes can ship the
   *  same platform as two rows so one batch covers both. */
  modes: WizardMode[];
  /** Per-mode schedule map; each value is either a fully-filled
   *  ``WizardMonitorEntry`` or ``null`` when the wizard wants to keep
   *  this mode's previous configuration unchanged. Missing key is the
   *  same as ``null``. Independent of ``modes``: a project may pick a
   *  platform in 思考 mode but only schedule 快速 mode. */
  schedules: Partial<Record<WizardMode, WizardMonitorEntry | null>>;
}

export interface WizardGeo {
  mode: WizardGeoMode;
  region_code: string | null;
}

export interface WizardSemantic extends SemanticInfo {}

/** 待审核 modal 的「每张模型卡」配置。``code`` 是网页版
 *  (``doubao``) 或移动版 (``doubao_mobile``) 的 modelCode,两个
 *  surface 各自一张卡,所以快速 / 思考 / 截图是逐卡独立的。
 *  ``modes`` 每项落一条 ProjectPlatform 行(think → thinking_mode)。 */
export interface WizardModelConfig {
  code: string;
  modes: WizardMode[];
  screenshot: boolean;
}

export interface WizardPayload {
  questions: WizardQuestion[];
  brand: WizardBrand;
  competitors: WizardCompetitor[];
  models: string[];
  /** 仅 待审核 modal 提交时非空。非空时后端忽略
   *  ``models × monitor.devices`` 的笛卡尔展开,直接按这里的 code 落行。 */
  models_config: WizardModelConfig[];
  monitor: WizardMonitor;
  categories: string[];
  geo: WizardGeo;
  sentiment: WizardSentiment;
  semantic: WizardSemantic;
}

export interface WizardSubmissionPayload {
  /** Required for super_admin; ignored for customer_admin (always forced
   *  to their own tenant on the server side). */
  customer_id?: number | null;
  payload: WizardPayload;
  /** When true the server keeps the project's existing
   *  ``schedule_enabled`` value instead of recomputing it from
   *  ``monitor.days``. Used by the active/disabled edit modal — the
   *  enable flag lives on the list-page Switch and must not flip as a
   *  side-effect of editing wizard fields. PENDING submissions leave
   *  this unset. */
  preserve_schedule_enabled?: boolean;
  /** Project row ``name`` (UI: "监控名称"). Not part of WizardPayload
   *  because the wizard has no top-level name field — wizard submit
   *  initialises ``name = brand.name``. PENDING can't reach this field
   *  via ``PUT /projects/{id}`` (lifecycle rule blocks business fields),
   *  so the draft endpoint accepts it here as a side flag. */
  name?: string | null;
}

/** Submit a new wizard run as ``status=PENDING``. Returns the created
 *  ``ProjectOut`` so the caller can navigate straight to the pending
 *  project id. */
export const submitWizardProject = (body: WizardSubmissionPayload) =>
  client.post<ProjectOut>("/projects", body).then((r) => r.data);

/** Overwrite the wizard payload of an existing PENDING row. */
export const putWizardDraft = (projectId: number, body: WizardSubmissionPayload) =>
  client
    .put<ProjectOut>(`/projects/${projectId}/draft`, body)
    .then((r) => r.data);

/** Super admin approves a pending submission. PENDING → ACTIVE. */
export const approveProject = (projectId: number) =>
  client
    .post<ProjectOut>(`/projects/${projectId}/approve`)
    .then((r) => r.data);

/** Super admin rejects a pending submission. PENDING → REJECTED. The
 *  ``review_note`` is shown back on the list page as a tooltip. */
export const rejectProject = (projectId: number, reviewNote: string) =>
  client
    .post<ProjectOut>(`/projects/${projectId}/reject`, {
      review_note: reviewNote,
    })
    .then((r) => r.data);

/** Hard-delete a PENDING submission (customer_admin: own tenant only). */
export const withdrawProject = (projectId: number) =>
  client.delete(`/projects/${projectId}/withdraw`).then((r) => r.data);
