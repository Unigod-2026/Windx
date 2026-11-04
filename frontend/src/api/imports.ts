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
