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
