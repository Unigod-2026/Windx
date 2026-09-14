// 新建项目向导的可编辑选项 —— 集中在这里,方便后期调整;
// 改这里会同时影响 NewProjectWizard 的下拉选项与默认值。
//
// 字段含义对齐参考 docs/风球GEO监控平台UI/js/data.js 的 QUESTION_TAGS
// 与 MODELS。

export interface QuestionTag {
  key: string;
  color: string;
}

export const QUESTION_TAGS: QuestionTag[] = [
  { key: "引流感", color: "blue" },
  { key: "场景类", color: "green" },
  { key: "用户人群", color: "purple" },
  { key: "对比类", color: "orange" },
  { key: "可及性", color: "cyan" },
  { key: "售后", color: "yellow" },
  { key: "毒副作用", color: "red" },
];

// =====================================================================
// 问题大类默认值 —— step 2「问题分类」页里始终自带这两个,wizard 不可删。
// 用户可以在它后面追加自定义分类,这些自定义分类与下面这两个同级
// 出现在「全部设为 X」批量按钮和每行问题的 seg-group 选择器里。
// 后端 ``WizardPayload.categories`` 字段以这个列表为前缀持久化。
// =====================================================================

export const WIZARD_DEFAULT_CATEGORIES: readonly string[] = ["引流类", "品牌类"] as const;

// =====================================================================
// 模型清单 —— value 必须与 /api/business/system/models 返回的 modelCode
// 完全一致,否则 super_admin 审批后会写到 geo_project_platforms.platform,
// 下游提示词渲染/平台身份识别会找不到映射。
//
// 截图原型 docs/风球GEO监控平台UI 仅展示了 7 个模型,所以本系统也只开放
// 这 7 个。要加新模型时:先去 Molizhishu /business/system/models 拿到
// modelCode,然后在这里追加一项,wizard 下拉会自动同步。
// =====================================================================

export interface WizardModelOption {
  /** 提交到后端的 modelCode,与 Molizhishu /business/system.models 的 modelCode 一致。 */
  value: string;
  /** 前端展示的中文名(沿用截图里的写法,不一定与 API 的 modelName 一致)。 */
  name: string;
  /** 模型卡片上的圆点色 + 图表配色,与原型 (--model-1..7) 对齐。 */
  color: string;
  /** 是否存在对应的移动端 modelCode;用于监控配置里阻止无移动版的模型被勾上「移动端」,
   * 否则审批后会写出 platform=kimi + DeliveryMode.MOBILE 这种下游找不到映射的组合。 */
  hasMobile: boolean;
  /** 移动端对应的真实 modelCode(与 /business/system.models 的 clientType=mobile 项对齐)。
   * 命名规则不是统一的 +_mobile 后缀:baiduai → baidu_mobile, douyinai → douyin_mobile,
   * 所以不能从 value 推断,必须显式维护。hasMobile=true 时必须有值,false 时为 null。 */
  mobileCode: string | null;
}

export const WIZARD_MODELS: WizardModelOption[] = [
  { value: "doubao", name: "豆包", color: "#1a55e8", hasMobile: true, mobileCode: "doubao_mobile" },
  { value: "yuanbao", name: "元宝", color: "#ff6b1a", hasMobile: true, mobileCode: "yuanbao_mobile" },
  { value: "qianwen", name: "千问", color: "#00a870", hasMobile: true, mobileCode: "qianwen_mobile" },
  { value: "kimi", name: "Kimi", color: "#722ed1", hasMobile: false, mobileCode: null },
  { value: "deepseek", name: "DeepSeek", color: "#13c2c2", hasMobile: true, mobileCode: "deepseek_mobile" },
  { value: "baiduai", name: "文心", color: "#eb2f96", hasMobile: true, mobileCode: "baidu_mobile" },
  { value: "antafu", name: "蚂蚁阿福", color: "#ed7b2f", hasMobile: false, mobileCode: null },
  // 2026-09-11 远端 GET /api/business/system/models 新增 chatgpt;无 mobile 版。
  { value: "chatgpt", name: "ChatGPT", color: "#10a37f", hasMobile: false, mobileCode: null },
];

// =====================================================================
// 提问位置模式 —— 与后端 RegionStrategy 一一对应。中文 label 只用于 UI,
// wire 上仍是英文 mode 值。
// =====================================================================

export type WizardGeoMode = "national_random" | "fixed";

export interface WizardRegionModeOption {
  key: WizardGeoMode;
  label: string;
  hint: string;
}

export const WIZARD_REGION_MODES: WizardRegionModeOption[] = [
  {
    key: "national_random",
    label: "全国随机",
    hint: "每次采集随机分配 IP 属地,覆盖全国采样",
  },
  {
    key: "fixed",
    label: "指定区域",
    hint: "仅在选定区域内投放提问,用于区域市场对比",
  },
];

// =====================================================================
// 情感分析开关 —— 默认 on。wire 上的值是 "on" / "off"。
// =====================================================================

export type WizardSentiment = "on" | "off";

export const WIZARD_SENTIMENT_OPTIONS: { key: WizardSentiment; label: string }[] = [
  { key: "on", label: "开启分析" },
  { key: "off", label: "关闭分析" },
];

// =====================================================================
// 监控频率与周内日期 —— 与后端 ``WizardPayload.monitor.{freq, days}`` 一一
// 对应。NewProjectWizard 与 BatchQuestionModal 的 PENDING 编辑面板共用
// 这两个常量,避免在 modal 里再声明一遍造成定义漂移。
// =====================================================================

export type WizardFreq = "w1" | "w2" | "wn";
export type WizardDay = "1" | "2" | "3" | "4" | "5" | "6" | "7";

// 提问模式 —— 落到 ``ProjectPlatform.thinking_mode``(think → true)。
// 待审核 modal 逐卡勾选,向导则是全局二选。
export const WIZARD_MODEL_MODES: { key: "fast" | "think"; label: string }[] = [
  { key: "fast", label: "快速" },
  { key: "think", label: "思考" },
];

export interface WizardMonitorFrequency {
  key: WizardFreq;
  label: string;
  min: number;
  max: number;
  hint: string;
}

export const WIZARD_MONITOR_FREQUENCIES: WizardMonitorFrequency[] = [
  { key: "w1", label: "一周一次", min: 1, max: 1, hint: "每周固定 1 天采集" },
  { key: "w2", label: "一周两次", min: 2, max: 2, hint: "每周固定 2 天采集" },
  { key: "wn", label: "一周多次", min: 1, max: 7, hint: "每周 1 ~ 7 天自由勾选,最多 7 次" },
];

export interface WizardWeekday {
  key: WizardDay;
  label: string;
}

export const WIZARD_WEEKDAYS: WizardWeekday[] = [
  { key: "1", label: "周一" },
  { key: "2", label: "周二" },
  { key: "3", label: "周三" },
  { key: "4", label: "周四" },
  { key: "5", label: "周五" },
  { key: "6", label: "周六" },
  { key: "7", label: "周日" },
];

/** 一周多次模式下的日期快捷组合(仅 wn 可用)。 */
export const WIZARD_WEEKDAY_PRESETS: { key: string; label: string; days: WizardDay[] }[] = [
  { key: "workday", label: "工作日", days: ["1", "2", "3", "4", "5"] },
  { key: "fullweek", label: "整周", days: ["1", "2", "3", "4", "5", "6", "7"] },
];

// =====================================================================
// 语义监控字段 —— 与后端 ``WizardSemantic`` 字段集一一对应,提交后由
// ``/api/pending-projects`` 落到 ``Project.semantic_json`` (一个 JSON 列,
// 详见 migration 20260908_0001)。
//
// UI 类型 (``tags`` / ``text`` / ``textarea``) 在 NewProjectWizard 里
// 直接 dispatch 到对应的渲染分支,不在这里做抽象 —— wizard 一处用,加
// 抽象反而绕。
// =====================================================================

export type WizardSemanticFieldType = "textarea";

export interface WizardSemanticField {
  /** WizardSemantic 字典里的 key,与后端字段名 1:1。 */
  key: keyof import("../../api/projects").WizardSemantic;
  /** UI 上显示的中文标签。 */
  label: string;
  type: WizardSemanticFieldType;
  /** 输入框 placeholder。 */
  placeholder: string;
  /** ``type == "tags"`` 时,字段为空时显示的提示文案。 */
  hint?: string;
}

export const WIZARD_SEMANTIC_FIELDS: WizardSemanticField[] = [
  {
    key: "selling_points",
    label: "核心卖点",
    type: "textarea",
    placeholder: "如:敏感肌可用\n无香精\n医研共创",
  },
];