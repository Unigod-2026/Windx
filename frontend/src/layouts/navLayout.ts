/**
 * 左侧导航的项目分组 —— 抽成独立模块是为了能在 vitest（node 环境）里
 * 直接断言分组结构，不必 import antd / react-router。
 */

export type ProjectTabKey =
  | "overview"
  | "question"
  | "competitor"
  | "source"
  | "self-articles"
  | "citation"
  | "answer"
  | "report"
  | "import"
  | "settings";

export const PROJECT_GROUP_LAYOUT: { title: string; keys: ProjectTabKey[] }[] = [
  {
    title: "数据洞察",
    keys: ["overview", "question", "competitor", "source", "self-articles", "citation"],
  },
  { title: "数据中心", keys: ["answer", "report", "import"] },
  { title: "系统", keys: ["settings"] },
];

export function groupTitleOf(key: ProjectTabKey): string {
  return PROJECT_GROUP_LAYOUT.find((g) => g.keys.includes(key))?.title ?? "";
}
