import client from "./client";

/** 字典单条 (host, media_name, category)。 */
export interface MediaDictionaryEntry {
  host: string;
  media_name: string;
  category: string;
}

export type MediaDictionaryInvalidReason =
  | "empty_host"
  | "invalid_host"
  | "empty_name"
  | "empty_category"
  | "duplicate_in_file";

export interface MediaDictionaryInvalidRow {
  row: number;
  raw_host: string;
  reason: MediaDictionaryInvalidReason;
}

export interface MediaDictionaryImportPreview {
  entries: MediaDictionaryEntry[];
  new_hosts: string[];
  update_hosts: string[];
  invalid_rows: MediaDictionaryInvalidRow[];
}

export interface MediaDictionaryImportResult {
  inserted: number;
  updated: number;
  skipped: number;
  total_in_dictionary: number;
}

export interface MediaDictionaryListOut {
  items: MediaDictionaryEntry[];
  total: number;
}

/** 解析 + diff 现有 DB,不写库。返回合法行 + new/update 分桶 + 无效行。 */
export async function previewMediaDictionaryImport(
  file: File,
): Promise<MediaDictionaryImportPreview> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await client.post<MediaDictionaryImportPreview>(
    "/admin/media-dictionary/preview",
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

/** 解析 + upsert(单事务)。返回 inserted / updated / 总数。 */
export async function importMediaDictionary(
  file: File,
): Promise<MediaDictionaryImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await client.post<MediaDictionaryImportResult>(
    "/admin/media-dictionary/import",
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

/** 字典全表(按 category, host 排序),带 total。 */
export async function listMediaDictionary(): Promise<MediaDictionaryListOut> {
  const { data } = await client.get<MediaDictionaryListOut>(
    "/admin/media-dictionary",
  );
  return data;
}
