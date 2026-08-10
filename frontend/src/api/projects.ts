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
  created_at: string;
  updated_at: string;
}

export interface ProjectPlatform {
  platform: string;
  mode: string;
  delivery_mode: "web" | "mobile";
  thinking_mode: boolean;
  screenshot: number;
  sort?: number;
  id?: number;
}

export interface ProjectDetailOut extends ProjectOut {
  prompts: string[];
  keywords: string[];
  platforms: ProjectPlatform[];
  sentiment_enabled: boolean;
  region_strategy: "fixed" | "national_random";
  region_codes: string[] | null;
}

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
  task_id: number | null;
  error_message: string | null;
}

export interface ScheduleRunList {
  items: ScheduleRunOut[];
  total: number;
  page: number;
  size: number;
}

export interface ProjectTaskOut {
  id: number;
  task_id: string;
  status: string;
  total_items: number | null;
  completed_items: number | null;
  failed_items: number | null;
  project_id: number | null;
  schedule_run_id: number | null;
  created_local_at: string | null;
}

export interface ProjectTaskList {
  items: ProjectTaskOut[];
  total: number;
  page: number;
  size: number;
}

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
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string | null;
  status?: "active" | "disabled";
  sentiment_enabled?: boolean;
  region_strategy?: "fixed" | "national_random";
  region_codes?: string[] | null;
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
  sort: number;
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
}

export interface PromptsUpdatePayload {
  prompts: string[];
}

export interface KeywordsUpdatePayload {
  keywords: string[];
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

export const putPrompts = (id: number, prompts: string[]) =>
  client
    .put<{ ok: boolean; count: number }>(`/projects/${id}/prompts`, { prompts })
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
