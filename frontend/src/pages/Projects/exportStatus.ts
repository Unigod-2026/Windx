/**
 * 导出任务状态 → 中文文案 + antd Tag 颜色。
 *
 * 写法与 importPreview.ts 的 batchStatusLabel / batchStatusTone 保持一致
 * (同一个「状态 → 展示」的位置),但色值语义不同:导出任务多一个「进行中」,
 * 用蓝色 —— 绿色是「已完成」,红色是「失败」,别混。
 */

export function exportStatusLabel(status: string): string {
  if (status === "pending") return "排队中";
  if (status === "running") return "生成中";
  if (status === "success") return "已完成";
  return "生成失败";
}

export function exportStatusTone(status: string): "blue" | "green" | "red" {
  if (status === "pending" || status === "running") return "blue";
  if (status === "success") return "green";
  return "red";
}

/** 任务是否还在跑 —— 决定前端要不要继续轮询。 */
export function isExportActive(status: string): boolean {
  return status === "pending" || status === "running";
}
