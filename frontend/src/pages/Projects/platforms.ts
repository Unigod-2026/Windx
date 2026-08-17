/**
 * 平台(模型)目录 —— 展示名、卡片配色与图表配色的唯一来源。
 *
 * ``chartColor`` 取自 docs/ui-sample 的 ``--model-1..7`` 调色板,
 * 与原型 legend 的顺序对齐(豆包蓝 / 元宝橙 / 通义绿 / Kimi 紫 …)。
 */

export interface ModelCardMeta {
  key: string;
  name: string;
  logo: string;
  bg: string;
  fg: string;
  chartColor: string;
}

export const PLATFORM_CATALOG: ModelCardMeta[] = [
  { key: "doubao", name: "豆包", logo: "豆", bg: "#1e40af", fg: "#ffffff", chartColor: "#1a55e8" },
  { key: "yuanbao", name: "元宝", logo: "元", bg: "#dc2626", fg: "#ffffff", chartColor: "#ff6b1a" },
  { key: "deepseek", name: "DeepSeek", logo: "D", bg: "#0891b2", fg: "#ffffff", chartColor: "#13c2c2" },
  { key: "wenxinyiyan", name: "百度文心", logo: "文", bg: "#2563eb", fg: "#ffffff", chartColor: "#eb2f96" },
  { key: "qianwen", name: "通义千问", logo: "通", bg: "#7c3aed", fg: "#ffffff", chartColor: "#52c41a" },
  { key: "hunyuan", name: "腾讯混元", logo: "混", bg: "#059669", fg: "#ffffff", chartColor: "#faad14" },
  { key: "doubao_mobile", name: "抖音豆包", logo: "抖", bg: "#0f172a", fg: "#ffffff", chartColor: "#4d80f0" },
  { key: "kimi", name: "Kimi", logo: "K", bg: "#0f172a", fg: "#ffffff", chartColor: "#722ed1" },
  { key: "quark", name: "夸克", logo: "夸", bg: "#7c3aed", fg: "#ffffff", chartColor: "#9254de" },
  { key: "zhipu", name: "智谱清言", logo: "智", bg: "#ea580c", fg: "#ffffff", chartColor: "#fa8c16" },
  { key: "meta", name: "秘塔AI", logo: "M", bg: "#1f2937", fg: "#ffffff", chartColor: "#595959" },
];

// Map legacy / display-name strings (e.g. "豆包", "DeepSeek") back to the
// API key the Molizhishu backend expects. Falls back to the lowercased
// input so unknown platforms still render rather than vanishing.
const LEGACY_PLATFORM_KEYS: Record<string, string> = {
  "豆包": "doubao",
  "元宝": "yuanbao",
  "deepseek": "deepseek",
  "doubao": "doubao",
  "yuanbao": "yuanbao",
  "kimi": "kimi",
  "qianwen": "qianwen",
  "quark": "quark",
  "baiduai": "baiduai",
  "weibo_zhisou": "weibo_zhisou",
  "wenxinyiyan": "wenxinyiyan",
  "doubao_mobile": "doubao_mobile",
};

export function platformToKey(raw: string): string {
  const found = PLATFORM_CATALOG.find((m) => m.key === raw);
  if (found) return found.key;
  if (LEGACY_PLATFORM_KEYS[raw]) return LEGACY_PLATFORM_KEYS[raw];
  return raw.toLowerCase();
}

export function platformMeta(raw: string): ModelCardMeta | undefined {
  return PLATFORM_CATALOG.find((m) => m.key === platformToKey(raw));
}

export function platformLabel(raw: string): string {
  return platformMeta(raw)?.name ?? raw;
}

// Unknown platforms cycle the prototype palette so a newly supported model
// still gets a stable colour instead of falling back to echarts defaults.
const FALLBACK_PALETTE = ["#1a55e8", "#ff6b1a", "#52c41a", "#722ed1", "#13c2c2", "#eb2f96", "#faad14"];

export function platformColor(raw: string, index = 0): string {
  return platformMeta(raw)?.chartColor ?? FALLBACK_PALETTE[index % FALLBACK_PALETTE.length];
}
