import client from "./client";

/** 三张 sheet 的 key —— 与后端 `SHEET_KEYS` 对齐。 */
export type ImportSheetKey = "answers" | "competitors" | "citations";

export interface ImportErrorSample {
  row: number;
  context: Record<string, string>;
}

/** 同一 (sheet, code) 的错误聚合。 */
export interface ImportErrorGroup {
  sheet: string;
  code: string;
  message: string;
  row_count: number;
  distinct: string[];
  samples: ImportErrorSample[];
}

export interface ImportWarning {
  code: string;
  message: string;
}

/** 对账条的一行：外部列 -> 平台内部字段。 */
export interface MappingRow {
  source: string;
  target: string;
  note: string;
}

export interface SheetPreview {
  key: ImportSheetKey;
  title: string;
  total_rows: number;
  importable_rows: number;
  blocked_rows: number;
  subtasks: number;
  /** 这一张是否被勾选导入 —— 未勾选的 sheet 不参与校验，不该报「阻断」。 */
  selected: boolean;
  sample: Record<string, string>[];
}

export interface ImportTotals {
  total_rows: number;
  importable_rows: number;
  blocked_rows: number;
  tasks: number;
  subtasks: number;
  brand_mentions: number;
  citations: number;
}

export interface ImportPreview {
  project_id: number;
  project_name: string;
  project_brand: string;
  file_name: string;
  sheets: SheetPreview[];
  warnings: ImportWarning[];
  mapping: MappingRow[];
  errors: ImportErrorGroup[];
  totals: ImportTotals;
  missing_sheets: string[];
}

export interface ImportResult {
  /** 本次导入所属批次（内容哈希 × 项目）—— 前端拿它跳到导入历史。 */
  batch_id: string;
  tasks_created: number;
  tasks_updated: number;
  subtasks_created: number;
  subtasks_updated: number;
  brand_mentions_written: number;
  brand_mentions_updated: number;
  citations_written: number;
  runs_written: number;
  skipped_rows: number;
  errors: ImportErrorGroup[];
}

/**
 * 解析 + 校验 + 聚合，不写库。
 *
 * `sheets` 传当前勾选的 sheet —— 后端按这个口径算「可导入」，
 * 页面上的数字才跟实际要写入的量一致（切勾选要重新预览）。
 */
export async function previewImportData(
  projectId: number,
  file: File,
  sheets?: ImportSheetKey[],
): Promise<ImportPreview> {
  const fd = new FormData();
  fd.append("file", file);
  const query = sheets && sheets.length ? `?sheets=${sheets.join(",")}` : "";
  const { data } = await client.post<ImportPreview>(
    `/projects/${projectId}/imports/preview${query}`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

/** 解析 + 校验 + 单事务落库。`sheets` 为空表示三张全导。 */
export async function applyImportData(
  projectId: number,
  file: File,
  sheets: ImportSheetKey[],
): Promise<ImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const query = sheets.length ? `?sheets=${sheets.join(",")}` : "";
  const { data } = await client.post<ImportResult>(
    `/projects/${projectId}/imports/apply${query}`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}


export type ImportBatchStatus = "success" | "partial" | "failed";

export interface ImportBatchSummary {
  id: string;
  file_name: string;
  status: ImportBatchStatus;
  totals: Record<string, number>;
  /** 同一批次被导入过几次。 */
  attempts: number;
  /** 本批次覆盖的监控日期。 */
  dates: string[];
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface ImportBatchListOut {
  items: ImportBatchSummary[];
  total: number;
}

/** 撤销这次导入会少掉多少数据。 */
export interface DeleteImpact {
  tasks: number;
  subtasks: number;
  brand_mentions: number;
  runs: number;
}

export interface ImportBatchDetail extends ImportBatchSummary {
  customer_id: number;
  file_hash: string;
  file_size: number;
  selected_sheets: string[];
  errors: ImportErrorGroup[];
  warnings: string[];
  delete_impact: DeleteImpact;
}

/** 批次列表 —— 按最近导入时间倒序。 */
export async function listImportBatches(
  projectId: number,
): Promise<ImportBatchListOut> {
  const { data } = await client.get<ImportBatchListOut>(
    `/projects/${projectId}/imports/batches`,
  );
  return data;
}

/** 批次详情 —— 含完整错误清单与撤销影响统计。 */
export async function getImportBatch(
  projectId: number,
  batchId: string,
): Promise<ImportBatchDetail> {
  const { data } = await client.get<ImportBatchDetail>(
    `/projects/${projectId}/imports/batches/${batchId}`,
  );
  return data;
}

/** 撤销一次导入 —— 硬删它写入的全部行，不可撤销。 */
export async function deleteImportBatch(
  projectId: number,
  batchId: string,
): Promise<void> {
  await client.delete(`/projects/${projectId}/imports/batches/${batchId}`);
}
