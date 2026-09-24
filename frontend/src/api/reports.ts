import client from "./client";

/** One row in the report list. */
export interface Report {
  id: number;
  project_id: number;
  template_id: string;
  title: string;
  /** Human-readable scope summary (period + model count + prompt count),
   *  assembled at generate time. Never null — empty string is the
   *  "未指定" sentinel for legacy rows. */
  scope_text: string;
  /** Public-share token. Generated at report creation, never reissued.
   *  Anyone with the URL ``/public/reports/{share_token}`` can view
   *  the report without authentication. */
  share_token: string;
  /** Operator-edited narrative content. Keys are template-defined;
   *  values are the operator's prose. Empty object means nothing
   *  edited yet (default after generation). */
  manual_overrides: Record<string, string | null>;
  /** Whether the public URL is accessible. False = draft state. */
  is_published: boolean;
  period_start: string;
  period_end: string;
  baseline_date: string | null;
  baseline_rate: number | null;
  generated_by_id: number;
  generated_by_name: string;
  generated_at: string;
}

export interface ReportListOut {
  items: Report[];
}

/** List reports for a single project, newest first. */
export async function listReports(projectId: number): Promise<ReportListOut> {
  const res = await client.get<ReportListOut>("/reports", {
    params: { project_id: projectId },
  });
  return res.data;
}

/** Build the public-share URL for a report. Returned value is the
 *  same one baked into ``Report.share_token`` at generate time. */
export function publicReportUrl(shareToken: string): string {
  return `${window.location.origin}/public/reports/${shareToken}`;
}

/** Request body for ``POST /api/reports``. */
export interface GenerateReportIn {
  project_id: number;
  template_id: string;
  period_start: string;
  period_end: string;
  baseline_date?: string | null;
  baseline_rate?: number | null;
  /** Raw ``Subtask.platform`` values (``doubao`` / ``doubao_mobile`` ...).
   *  ``undefined`` = no filter. */
  platform_codes?: string[] | null;
  /** ``ProjectPrompt.id`` list. ``undefined`` = no filter. */
  prompts?: number[] | null;
}

/** Generate a new report. Backend writes HTML to disk and returns the
 *  metadata row. */
export async function generateReport(
  payload: GenerateReportIn,
): Promise<Report> {
  const res = await client.post<Report>("/reports", payload);
  return res.data;
}

/** Open / preview a report. Returns the HTML string with auth header
 *  attached; caller is responsible for rendering it. */
export async function fetchReportHtml(reportId: number): Promise<string> {
  const res = await client.get<string>(`/reports/${reportId}/html`, {
    responseType: "text",
  });
  return res.data;
}

/** Preview page payload — structured snapshot, not HTML. The preview
 *  page React-renders this with the SPA's visual tokens, instead of
 *  parsing the HTML file on disk (see plan §3.5). */
export interface ReportMeta {
  id: number;
  project_id: number;
  template_id: string;
  title: string;
  manual_overrides: Record<string, string | null>;
  is_published: boolean;
  scope_text: string;
  share_token: string;
  period_start: string;
  period_end: string;
  baseline_date: string | null;
  baseline_rate: number | null;
  generated_by_id: number;
  generated_by_name: string;
  generated_at: string;
}

export interface ReportSnapshot {
  project: { id: number; name: string; brand: string | null };
  period: { start: string; end: string };
  baseline: { date: string | null; rate: number | null };
  title: string;
  generated_by: string;
  generated_at: string;
  daily_mention_rate: Array<{
    date: string;
    total: number;
    mentioned: number;
    rate: number;
  }>;
  platform_breakdown: Array<{
    platform_code: string;
    platform_label: string;
    current_total: number;
    current_mentioned: number;
    current_rate: number;
    previous_total: number;
    previous_mentioned: number;
    previous_rate: number;
    delta_pp: number;
  }>;
  // ---- Added in 2026-09-24 full-template refactor ----
  /** Section 三.2 — one-line summary per platform. */
  platform_summary?: Array<{
    platform_code: string;
    platform_label: string;
    note: string;
  }>;
  /** Section 三.3 — prompt × platform matrix. Each row is one prompt;
   *  per_platform is { platform_code: was_mentioned }. */
  prompt_platform_matrix?: Array<{
    prompt_id: number;
    prompt_text: string;
    per_platform: Record<string, boolean>;
  }>;
  /** Section 二 — operator-written prose, four blocks. */
  weekly_summary?: {
    core_finding: string | null;
    platform_dynamic: string | null;
    content_result: string | null;
    scene_coverage: string | null;
  };
  /** Section 五 — each bucket's array may be empty. */
  weekly_changes?: {
    new_mentions: Array<{ prompt_id: number; prompt_text: string }>;
    increased: Array<{
      prompt_id: number;
      prompt_text: string;
      from: number;
      to: number;
    }>;
    decreased: Array<{
      prompt_id: number;
      prompt_text: string;
      from: number;
      to: number;
    }>;
    lost_mentions: Array<{ prompt_id: number; prompt_text: string }>;
  };
  /** Section 五.1 — prompts with zero mentions across the window. */
  zero_mention_prompts?: Array<{
    prompt_id: number;
    prompt_text: string;
  }>;
  /** Section 四 — content ops. Always ``null`` until the content-ops
   *  data source ships. */
  content_ops?: unknown | null;
  /** Section 5.3 — operator-input attribution. ``null`` until the
   *  operator workflow ships. */
  attribution?: string | null;
}

export interface ReportSnapshotOut {
  meta: ReportMeta;
  template_id: string;
  snapshot: ReportSnapshot;
  /** Set to ``true`` when the public URL is reached but the operator
   *  hasn't published the report yet. ``undefined`` means the
   *  report is published and ``snapshot`` is populated. */
  unpublished?: true;
  /** Present only when ``unpublished === true``. Echoes the
   *  share_token and basic metadata so the public page can render
   *  a friendly "尚未发布" notice without a second round-trip. */
  share_token?: string;
  title?: string;
  period_start?: string;
  period_end?: string;
}

export async function getReportSnapshot(id: number): Promise<ReportSnapshotOut> {
  const res = await client.get<ReportSnapshotOut>(`/reports/${id}`);
  return res.data;
}

/** Public, no-auth fetch — uses a dedicated axios instance without the
 *  Authorization interceptor so the request doesn't leak our session
 *  token. Endpoint is gated only by ``share_token`` in the URL. */
export async function getPublicReportSnapshot(
  shareToken: string,
): Promise<ReportSnapshotOut> {
  const res = await client.get<ReportSnapshotOut>(
    `/public/reports/${shareToken}`,
  );
  return res.data;
}

/** One row from ``GET /api/reports/templates`` — display metadata for
 *  a template that's both registered in code AND configured in
 *  ``report_settings.json``. */
export interface ReportTemplate {
  id: string;
  name: string;
  description: string | null;
}

export interface ReportTemplateListOut {
  items: ReportTemplate[];
}

/** Fetch the templates available to generate. Auth required (the
 *  generation UI is behind RequireAuth; the public preview page does
 *  not call this). */
export async function listTemplates(): Promise<ReportTemplateListOut> {
  const res = await client.get<ReportTemplateListOut>("/reports/templates");
  return res.data;
}

/** The project's currently-configured baseline. Returned to the
 *  generate modal so it can pre-fill the required baseline fields.
 *  Both fields are null when no baseline has ever been set. */
export interface ProjectBaseline {
  project_id: number;
  baseline_date: string | null;
  baseline_rate: number | null;
}

export async function getProjectBaseline(
  projectId: number,
): Promise<ProjectBaseline> {
  const res = await client.get<ProjectBaseline>(
    `/reports/projects/${projectId}/baseline`,
  );
  return res.data;
}

/** Save operator-edited narrative content as draft. */
export async function updateReport(
  id: number,
  manualOverrides: Record<string, string | null>,
): Promise<Report> {
  const res = await client.patch<Report>(`/reports/${id}`, {
    manual_overrides: manualOverrides,
  });
  return res.data;
}

/** Publish: makes the public URL accessible. The router enforces
 *  that every template field has a non-empty value. */
export async function publishReport(id: number): Promise<Report> {
  const res = await client.post<Report>(`/reports/${id}/publish`);
  return res.data;
}

/** Unpublish: hides the public URL again. ``manual_overrides`` is
 *  preserved so re-publishing restores the same content. */
export async function unpublishReport(id: number): Promise<Report> {
  const res = await client.post<Report>(`/reports/${id}/unpublish`);
  return res.data;
}
