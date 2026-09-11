/**
 * 平台(模型)目录 —— 展示名、卡片配色与图表配色的统一入口。
 *
 * 主数据源是 ``WIZARD_MODELS``(前端 wizard 编辑器唯一认可的模型清单,
 * 与 /api/business/system/models 返回的 modelCode 一一对应)。它本来就
 * 区分 ``value``(web code,如 ``qianwen``)与 ``mobileCode``(mobile code,
 * 如 ``qianwen_mobile``),这里据此自动加「网页版 / 移动版」后缀,让
 * OverviewTab 的 trend 图例、Top1 排行横轴、model dimension 子图、
 * tooltip 等所有展示位置一致。
 *
 * ``PLATFORM_CATALOG`` 保留作为历史 fallback:之前那里登记的
 * ``wenxinyiyan`` / ``hunyuan`` / ``doubao_mobile``(抖音豆包)等
 * WIZARD_MODELS 未覆盖的 code 仍能查到,避免回归。新接入 / 改名的
 * 模型优先在 ``WIZARD_MODELS`` 维护,PLATFORM_CATALOG 不再扩展。
 */

import { WIZARD_MODELS } from "./wizardConfig";

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

/** 在 ``WIZARD_MODELS`` 里按 ``value``(web code)或 ``mobileCode`` 查模型,
 *  返回 ``{name, color, mobile}``,便于渲染时挂「网页版 / 移动版」后缀。
 *  找不到时返回 ``undefined``,由调用方走 ``PLATFORM_CATALOG`` 兜底。 */
function wizardByCode(code: string) {
  const web = WIZARD_MODELS.find((m) => m.value === code);
  if (web) return { entry: web, mobile: false };
  const mobile = WIZARD_MODELS.find((m) => m.mobileCode === code);
  if (mobile) return { entry: mobile, mobile: true };
  return undefined;
}

/** ``platformLabel`` 输出供 OverviewTab 各图表 / tooltip 使用的展示名:
 *  - WIZARD_MODELS 命中的 code:`<name> 网页版` / `<name> 移动版`,
 *    让用户清楚这条 series 对应哪一档设备;
 *  - PLATFORM_CATALOG 兜底(老 code):用历史 ``name``(不再加后缀,
 *    因为 catalog 本来就没区分 web / mobile,加上反而误导);
 *  - 都找不到:原样回传 code,避免静默丢失。 */
export function platformLabel(raw: string): string {
  const w = wizardByCode(raw);
  if (w) return `${w.entry.name} ${w.mobile ? "移动版" : "网页版"}`;
  const meta = PLATFORM_CATALOG.find((m) => m.key === platformToKey(raw));
  if (meta) return meta.name;
  return raw;
}

// Unknown platforms cycle the prototype palette so a newly supported model
// still gets a stable colour instead of falling back to echarts defaults.
const FALLBACK_PALETTE = ["#1a55e8", "#ff6b1a", "#52c41a", "#722ed1", "#13c2c2", "#eb2f96", "#faad14"];

/** ``platformColor`` 取色优先级:WIZARD_MODELS.color > PLATFORM_CATALOG.chartColor > FALLBACK_PALETTE。
 *  WIZARD_MODELS 命中的 web 与 mobile 同色 —— 与模型卡片编辑器的同色
 *  规则一致,避免同一逻辑模型在 trend / ranking 里出现两种颜色。 */
export function platformColor(raw: string, index = 0): string {
  const w = wizardByCode(raw);
  if (w) return w.entry.color;
  const meta = PLATFORM_CATALOG.find((m) => m.key === platformToKey(raw));
  if (meta) return meta.chartColor;
  return FALLBACK_PALETTE[index % FALLBACK_PALETTE.length];
}
