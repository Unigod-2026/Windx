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
  sentiment_score: number | null;
  is_recommended: boolean | null;
  concern_hits_json: string[] | null;
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
}

export interface QuestionPrevStat {
  total: number;
  matched: number;
  top1_rate: number;
  top3_rate: number;
  mention_rate: number;
  rank_avg: number | null;
}

export interface QuestionAnalyticsItem {
  prompt_id: number;
  prompt: string;
  category: string | null;
  status: string;
  total: number;
  matched: number;
  top1_rate: number;
  top3_rate: number;
  mention_rate: number;
  rank_avg: number | null;
  coverage: number;
  platforms: QuestionPlatformStat[];
  prev: QuestionPrevStat | null;
}

export interface QuestionAnalyticsOut {
  project_id: number;
  start: string;
  end: string;
  items: QuestionAnalyticsItem[];
}

/**
 * 问题提及分析 — 服务端聚合,前端只渲染。
 *
 * 历史:之前前端用 ``listBrandMentions`` 拉明细再做 useMemo 聚合,
 * 但明细接口 size 上限 100,15 天窗口下常常拿不到完整数据,
 * 导致提及率 / 提及次数 / 模型覆盖 等 KPI 飘。新接口直接走
 * ``GROUP BY (prompt[, platform])`` 算出准确值。
 */
export const getQuestionsAnalytics = (
  projectId: number,
  params: { days?: number; start?: string; end?: string } = {},
) =>
  client
    .get<QuestionAnalyticsOut>(
      `/projects/${projectId}/questions/analytics`,
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

export interface ProjectOverview {
  project_id: number;
  start: string;
  end: string;
  days: number;
  labels: string[];
  total_mentions: OverviewKpi;
  top1_rate: OverviewKpi;
  top3_rate: OverviewKpi;
  question_count: OverviewKpi;
  answer_count: OverviewKpi;
  trend: OverviewTrendSeries[];
  ranking: OverviewPlatformRank[];
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
  /** 7-day sparkline, zero-filled, ordered oldest → newest. */
  spark: number[];
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

export type ConcernTagCls =
  | "brand"
  | "positive"
  | "negative"
  | "warn"
  | "default";

export interface ConcernTag {
  text: string;
  weight: number;
  cls: ConcernTagCls;
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
  concern_tags: ConcernTag[];
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
