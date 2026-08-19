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

export interface ProjectOut {
  id: number;
  customer_id: number;
  name: string;
  code: string;
  status: "active" | "disabled";
  description: string | null;
  schedule_enabled: boolean;
  slots: SlotOut[];
  next_run_at: string | null;
  brand: string | null;
  aliases: string[] | null;
  category_taxonomy: string[] | null;
  prompts_count: number;
  created_at: string;
  updated_at: string;
}

// ``mode`` is the LLM mode forwarded to the remote — only the four values
// docs/api/submit-task.md §平台 lists are accepted. ``delivery_mode`` is
// frontend-only (the live remote has no surface field); it's stored locally
// but NOT in the submit payload.
export type LlmMode = "standard" | "reasoning" | "search" | "reasoning_search";

export interface ProjectPlatform {
  platform: string;
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
  slots: SlotOut[];
  next_run_at: string | null;
  last_run: RunSummary | null;
}

export interface ScheduleRunOut {
  id: number;
  project_id: number;
  slot_index: number;
  trigger_type: "cron" | "manual";
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
  brand_canonical: string;
  is_self: boolean;
  mention_count: number;
  rank_position: number | null;
  // "positive" / "neutral" / "negative" — the API-pass refactor writes
  // the Molizhishu label directly; the dashboard KPI layer translates
  // to a float average for the color buckets.
  sentiment_score: string | null;
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
  status?: "active" | "disabled";
  q?: string;
}

export const listProjects = (params: ListProjectsParams) =>
  client.get<ProjectList>("/projects", { params }).then((r) => r.data);

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
  params: { days?: number; start?: string; end?: string; platform?: string; preview_chars?: number } = {},
) =>
  client
    .get<PromptAnswerList>(`/projects/${projectId}/prompts/${promptId}/answers`, {
      params,
    })
    .then((r) => r.data);

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
    brand_canonical?: string;
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
  platform: string;
  matched: number;
  total: number;
  best_rank: number | null;
  avg_sentiment: number | null;
  recommend_yes: boolean;
  // Populated when ``view=competitor`` — the dominant competitor
  // brand that drove the aggregation for this (prompt, platform).
  brand_canonical?: string | null;
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
  brand_canonical: string;
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
}

export interface QuestionStableItem {
  prompt_id: number;
  prompt: string;
  category: string | null;
  platforms: string[];
}

export interface DropEvent {
  prompt_id: number;
  prompt: string;
  category: string | null;
  platform: string;
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
 * 稳定与掉落面板 — 服务端把每个 (prompt, platform) 划入 4 个独立集合:
 *   - ``stable``: 上一窗口 + 当前窗口都有提及
 *   - ``drops``: 上一窗口有,当前窗口掉出 Top-3 或消失(per 事件)
 *   - ``never_listed``: 双窗口都没出现过
 *   - ``listed``: 当前窗口至少被一个模型提过
 */
export const getQuestionStatusChanges = (
  projectId: number,
  params: { days?: number; start?: string; end?: string } = {},
) =>
  client
    .get<QuestionStatusChangesOut>(
      `/projects/${projectId}/questions/status-changes`,
      { params },
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
      { params },
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
      { params },
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
      { params },
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

/** ``start``/``end`` are inclusive ``YYYY-MM-DD`` and win over ``days``. */
export const getProjectOverview = (
  projectId: number,
  params: { days?: number; start?: string; end?: string } = {},
) =>
  client
    .get<ProjectOverview>(`/projects/${projectId}/overview`, { params })
    .then((r) => r.data);

// ------------------------------------------------------------------
// Competitor analysis (data tab → 竞品分析)
// ------------------------------------------------------------------

export interface CompetitorKpi {
  brand_canonical: string;
  name: string;
  aliases: string[] | null;
  is_self: boolean;
  mention_count: number;
  mention_rate: number;
  top3_rate: number;
  recommend_rate: number;
  avg_sentiment: number | null;
  avg_rank: number | null;
  /** 15-day sparkline, zero-filled, ordered oldest → newest. */
  spark: number[];
  /** Top1 提及率(= rank_position=1 且 mention_count>0 的次数 / total_subtasks) */
  top1_rate: number;
  /** 情感三档占比(分母 = mention_count>0 的样本数) */
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
  brand_canonical: string;
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
  platform: string;
  self_mention_rate: number;
  competitor_avg_mention_rate: number;
}

export interface ModelDiff {
  platform: string;
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

/** 竞品分析 — 近 15 天默认。``start``/``end`` (inclusive ``YYYY-MM-DD``) win over ``days``. */
export const getCompetitorAnalysis = (
  projectId: number,
  params: { days?: number; start?: string; end?: string } = {},
) =>
  client
    .get<CompetitorAnalysisOut>(
      `/projects/${projectId}/competitor-analysis`,
      { params },
    )
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
}

export function getSourcePreferences(
  projectId: number,
  days = 15,
): Promise<SourcePreferenceOut> {
  return client
    .get<SourcePreferenceOut>(
      `/projects/${projectId}/source-preferences`,
      { params: { days } },
    )
    .then((r) => r.data);
}
