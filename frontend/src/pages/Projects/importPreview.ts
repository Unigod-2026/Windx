import type { ImportErrorGroup, ImportTotals, SheetPreview } from "../../api/imports";

export type SheetTone = "ok" | "warn" | "error";

/** 分区状态：有阻断 → error；没数据 → warn；否则 ok。 */
export function sheetTone(
  sheet: SheetPreview,
  errorGroups: ImportErrorGroup[],
): SheetTone {
  const blocked = errorGroups
    .filter((g) => g.sheet === sheet.title)
    .reduce((sum, g) => sum + g.row_count, 0);
  if (blocked > 0) return "error";
  if (sheet.total_rows === 0) return "warn";
  return "ok";
}

export function toneLabel(tone: SheetTone): string {
  if (tone === "error") return "有阻断";
  if (tone === "warn") return "无数据";
  return "通过";
}

/** 错误文案：原话 + 影响范围，不写「数据格式错误」这类空话。 */
export function describeErrorGroup(group: ImportErrorGroup): string {
  const scope = group.distinct.length
    ? `${group.row_count} 行，涉及 ${group.distinct.length} 个不同取值`
    : `${group.row_count} 行`;
  return `${group.message}（${scope}）`;
}

export function describeTotals(totals: ImportTotals): string {
  return `共解析 ${totals.total_rows} 条，可导入 ${totals.importable_rows} 条，阻断 ${totals.blocked_rows} 条`;
}

/**
 * 从 axios 错误里取出后端给的**可操作**文案。
 *
 * axios 的 `err.message` 是 "Request failed with status code 400" 这种
 * 废话，后端的 `detail` 才是人话（"请到项目「编辑」里的『监控模型』补充"）。
 * 仓库既有写法见 OwnArticlesImportModal.tsx / List.tsx / SettingsPane.tsx。
 */
export function apiErrorText(err: unknown, fallback = "操作失败"): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    // FastAPI 的 422 校验错误是对象数组
    return detail
      .map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d))
      .join("；");
  }
  const msg = (err as Error)?.message;
  if (msg && !/^Request failed with status code/.test(msg)) return msg;
  return fallback;
}
