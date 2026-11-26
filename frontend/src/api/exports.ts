import client from "./client";

/** 导出任务摘要 —— 列表和创建接口都返回它。 */
export interface ExportTaskSummary {
  id: number;
  project_id: number;
  status: string;
  file_name: string | null;
  file_size: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** 文件过了保留期被清理 → 显示「文件已过期」而不是「下载」。 */
  file_expired: boolean;
}

/** 任务详情 —— 额外带回提交时的筛选快照(「重试」要用)。 */
export interface ExportTaskDetail extends ExportTaskSummary {
  params: Record<string, unknown>;
}

export interface ExportTaskList {
  items: ExportTaskSummary[];
  total: number;
}

/**
 * 提交导出时的筛选条件。
 *
 * `platforms` / `prompt_ids` 传 null 表示「不筛」—— 对应工具栏上
 * 「全选」的状态,后端按不筛处理。
 */
export interface ExportParamsPayload {
  date_range: { start?: string; end?: string; days?: number };
  platforms: string[] | null;
  prompt_ids: number[] | null;
}

export async function createExport(
  projectId: number,
  params: ExportParamsPayload,
): Promise<ExportTaskSummary> {
  const res = await client.post(`/projects/${projectId}/exports`, params);
  return res.data;
}

export async function listExports(
  projectId: number,
): Promise<ExportTaskList> {
  const res = await client.get(`/projects/${projectId}/exports`);
  return res.data;
}

export async function getExport(taskId: number): Promise<ExportTaskDetail> {
  const res = await client.get(`/exports/${taskId}`);
  return res.data;
}

export async function deleteExport(taskId: number): Promise<void> {
  await client.delete(`/exports/${taskId}`);
}

/**
 * 下载 xlsx。
 *
 * 走 axios 而不是 window.open —— 下载端点要 Authorization 头,
 * window.open 带不了。拿 blob → createObjectURL → 造 <a download> 触发
 * → 立刻 revoke。
 */
export async function downloadExport(
  taskId: number,
  fileName: string,
): Promise<void> {
  const res = await client.get(`/exports/${taskId}/download`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(res.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
