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
import type { ProjectPlatform } from "../../api/projects";

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
  const aliased = PLATFORM_CODE_ALIASES[code] ?? code;
  const web = WIZARD_MODELS.find((m) => m.value === aliased);
  if (web) return { entry: web, mobile: false };
  const mobile = WIZARD_MODELS.find((m) => m.mobileCode === aliased);
  if (mobile) return { entry: mobile, mobile: true };
  return undefined;
}

/** OverviewTab trend / ranking / model-dimension 的 ``platform`` 字段是
 *  后端拼的 compound key —— ``${platform_code}__${delivery_mode}__${thinking}``
 *  (例 ``qianwen__web__fast`` / ``kimi__mobile__think``)。拆分后用
 *  ``wizardByCode`` 拿 name + color,再补终端 / 模式档位,渲染对齐
 *  docs/模型名字.txt 的「<name>-<终端>-<模式>」格式。 */
const OVERVIEW_KEY_RE = /^(.+?)__(web|mobile)__(fast|think)$/;

export function parseOverviewKey(raw: string):
  | { code: string; delivery: "web" | "mobile"; thinking: "fast" | "think" }
  | null {
  const m = OVERVIEW_KEY_RE.exec(raw);
  if (!m) return null;
  return { code: m[1], delivery: m[2] as "web" | "mobile", thinking: m[3] as "fast" | "think" };
}

/** ``Subtask`` 直出的 ``(platform, mode)`` → compound key,与后端
 *  ``_compound_platform`` 同款逻辑(见 backend source_preferences.py)。
 *  ``Subtask.platform`` 是 raw ``platform_code``(mobile 档带 ``_mobile`` 后缀),
 *  ``mode`` 是 Molizhishu 直返回的 ``search`` / ``reasoning_search`` / ``web`` 等。
 *  喂给 ``platformLabel`` 即可走 compound 路径渲染成「千问-网页-快速」对齐
 *  docs/模型名字.txt —— 不再用 fallback 路径输出「千问 网页版 · search」。 */
export function compoundKeyFor(
  platform: string | null | undefined,
  mode: string | null | undefined,
): string {
  const raw = platform || "unknown";
  const delivery: "web" | "mobile" = raw.endsWith("_mobile") ? "mobile" : "web";
  const base = delivery === "mobile" ? raw.slice(0, -"_mobile".length) : raw;
  const thinking: "fast" | "think" = mode === "reasoning_search" ? "think" : "fast";
  return `${base}__${delivery}__${thinking}`;
}

/** 只取模型中文/英文展示名(不含「-网页版-快速」后缀),跟「终端 / 模式」
 *  chip 配合使用 —— 头部已经是「网页版」「快速」chip,就不再在标题文本里
 *  重复同样的 -网页-快速 后缀,避免视觉冗余。找不到时回退 raw code。 */
export function modelNameFor(
  platform: string | null | undefined,
  mode: string | null | undefined,
): string {
  const compound = parseOverviewKey(compoundKeyFor(platform, mode));
  const code = compound?.code ?? platform ?? "?";
  const w = wizardByCode(code);
  if (w) return w.entry.name;
  const meta = platformMeta(code);
  if (meta) return meta.name;
  return code;
}

/** ``ProjectPlatform`` row → compound key,与后端 ``_compound_platform`` 拼出的
 *  key 完全一致(``${base}__${delivery}__${thinking}``,其中 ``base`` 是剥掉
 *  ``_mobile`` 后缀的 ``platform_code``)。GlobalToolbar 拼 dropdown 选项、
 *  AllSources 拼全集回填都用同一函数,避免漂移。
 *
 *  ``platform_code`` 在 mobile 档形如 ``qianwen_mobile`` / ``baidu_mobile``,
 *  直接拼接会产出 ``qianwen_mobile__mobile__fast`` —— 后端却把 ``_mobile``
 *  后缀当作 delivery 信号,产出 ``qianwen__mobile__fast``。两侧格式不一致
 *  会让 post-filter 用 ``_compound_platform(plat, mode) in selected_set``
 *  做相等判断时,行被全丢(by_model_top 出现 3 张空 mobile 卡、勾部分档
 *  时显示数量对不上)。所以前端这边也要先剥 ``_mobile``,再按 delivery
 *  拼,与后端 ``_compound_platform`` 对齐。 */
export function rowKeyOfPlatform(r: ProjectPlatform): string {
  const rawCode = r.platform_code ?? r.platform;
  const code = rawCode.endsWith("_mobile")
    ? rawCode.slice(0, -"_mobile".length)
    : rawCode;
  const delivery = r.delivery_mode;
  const thinking = r.thinking_mode ? "think" : "fast";
  return `${code}__${delivery}__${thinking}`;
}

const DELIVERY_LABEL: Record<"web" | "mobile", string> = {
  web: "网页",
  mobile: "手机",
};
const THINKING_LABEL: Record<"fast" | "think", string> = {
  fast: "快速",
  think: "思考",
};

// 后端 ``_compound_platform`` 把 ``baidu_mobile`` 剥成 ``baidu`` 写入 compound key,
// 但 WIZARD_MODELS 的 ``value`` 是 ``baiduai``(前后缀不一致的历史命名),
// 导致 ``wizardByCode("baidu")`` 查不到中文名,fallback 显示 raw ``baidu-手机-快速``。
// 这里把剥离后的 base code 回填成能在 WIZARD_MODELS 里命中的 code,保证
// ``platformLabel`` 与工具栏 dropdown 显示对齐(都展示「文心-手机-快速」)。
const PLATFORM_CODE_ALIASES: Record<string, string> = {
  baidu: "baiduai",
};

/** ``platformLabel`` 输出供 OverviewTab 各图表 / tooltip 使用的展示名:
 *  - compound key(后端 trend / ranking / model_dimensions 发来的):
 *    ``<name>-<终端>-<模式>``,严格对齐 docs/模型名字.txt;
 *  - WIZARD_MODELS 命中的 raw code:`<name> 网页版` / `<name> 移动版`,
 *    兼容老路径(直接拿 modelCode 调用 platformLabel 的场景);
 *  - PLATFORM_CATALOG 兜底(老 code):用历史 ``name``(不再加后缀,
 *    因为 catalog 本来就没区分 web / mobile,加上反而误导);
 *  - 都找不到:原样回传 code,避免静默丢失。 */
export function platformLabel(raw: string): string {
  const compound = parseOverviewKey(raw);
  if (compound) {
    const w = wizardByCode(compound.code);
    if (w) {
      return `${w.entry.name}-${DELIVERY_LABEL[compound.delivery]}-${THINKING_LABEL[compound.thinking]}`;
    }
    // compound 形式但 base code 不在 WIZARD_MODELS:仍按格式渲染,让
    // 后端来的未知 code 也走统一布局而不是只剩 code 字符串。
    return `${compound.code}-${DELIVERY_LABEL[compound.delivery]}-${THINKING_LABEL[compound.thinking]}`;
  }
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
  // compound key → 拆出 base code,与 WIZARD_MODELS / PLATFORM_CATALOG 同色
  const compound = parseOverviewKey(raw);
  const base = compound ? compound.code : raw;
  const w = wizardByCode(base);
  if (w) return w.entry.color;
  const meta = PLATFORM_CATALOG.find((m) => m.key === platformToKey(base));
  if (meta) return meta.chartColor;
  return FALLBACK_PALETTE[index % FALLBACK_PALETTE.length];
}
