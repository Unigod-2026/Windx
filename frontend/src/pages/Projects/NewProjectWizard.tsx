// 多步新建项目向导 —— 引导步骤和内容与参考
// ``docs/风球GEO监控平台UI/js/wizard.js`` 完全一致:
//   1. 填写问题
//   2. 问题分类
//   3. 品牌与竞品
//   4. 选择模型
//   5. 监控配置
//   6. 确认提交
//
// 后端存储层 / API 不变;前端展示用中文,发到后端的 model token 仍是
// 英文 ``doubao`` / ``deepseek`` / ...(与现有 ``geo_project_platforms`` 数据
// 一致)。monitor 枚举值 (``pc`` / ``mobile`` / ``fast`` / ``think`` /
// ``w1`` / ``w2`` / ``wn``) 与后端 schema 同步。

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Input,
  Modal,
  Select,
  Space,
} from "antd";
import {
  CheckCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  EnvironmentOutlined,
  ProfileOutlined,
  RobotOutlined,
  ScheduleOutlined,
  ShopOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { submitWizardProject, type WizardBrand, type WizardCompetitor, type WizardGeo, type WizardMonitor, type WizardMonitorEntry, type WizardPayload, type WizardQuestion, type WizardSemantic, type WizardSentiment } from "../../api/projects";
import { listCustomers, type Customer } from "../../api/customers";
import { listMolizhishuCities, type Province } from "../../api/molizhishu";
import { useAuth } from "../../auth/AuthProvider";
import {
  WIZARD_DEFAULT_CATEGORIES,
  WIZARD_MODELS,
  WIZARD_MONITOR_FREQUENCIES,
  WIZARD_REGION_MODES,
  WIZARD_SEMANTIC_FIELDS,
  WIZARD_SENTIMENT_OPTIONS,
  WIZARD_WEEKDAYS,
  WIZARD_WEEKDAY_PRESETS,
  type WizardDay,
  type WizardFreq,
  type WizardGeoMode,
  type WizardModelOption,
  type WizardRegionModeOption,
  type WizardSemanticField,
} from "./wizardConfig";
import "./NewProjectWizard.css";

const { TextArea } = Input;

// =====================================================================
// 参考常量 —— 与 docs/风球GEO监控平台UI/js/data.js 字段对齐
// =====================================================================

/** 单项目最大问题数(对齐参考 WIZARD_MAX_QUESTIONS = 50)。 */
const WIZARD_MAX_QUESTIONS = 50;

/** 7 个模型 —— 来自 wizardConfig.ts,modelCode 与 Molizhishu /business/system/models 对齐。 */
const MODELS = WIZARD_MODELS;

/** 细分标签 —— 来自 wizardConfig.ts,方便后续在不改组件代码的情况下增删。 */

/** 固定问题分类的口径说明。WIZARD_DEFAULT_CATEGORIES 里两个默认分类
 *  在这里都有说明;用户追加的自定义分类不在此 map 里,seg-group 上
 *  也不带「判定口径」提示 —— 因为那些是用户自创的语义,我们无从给出
 *  业务判定口径。 */
const QUESTION_CATEGORY_TIPS: Record<string, string> = {
  引流类: "不含有项目对应产品的名称",
  品牌类: "包含产品的名称",
};

/** 监控频率与周内日期 —— 引用自 wizardConfig,modal 与 wizard 共用同一份定义。 */
const MONITOR_FREQUENCIES = WIZARD_MONITOR_FREQUENCIES;
const WEEKDAYS = WIZARD_WEEKDAYS;
const WEEKDAY_PRESETS = WIZARD_WEEKDAY_PRESETS;

/** 一周最大可采集天数(对齐参考 MONITOR_MAX_DAYS = 7)。 */
const MONITOR_MAX_DAYS = 7;

const ANSWER_DEVICES: { id: "pc" | "mobile"; name: string }[] = [
  { id: "pc", name: "PC 端" },
  { id: "mobile", name: "移动端" },
];

const ANSWER_MODES: { id: "fast" | "think"; name: string }[] = [
  { id: "fast", name: "快速模式" },
  { id: "think", name: "思考模式" },
];

const STEP_KEYS = [
  "questions",
  "categories",
  "brands",
  "models",
  "monitor",
  "geo",
  "summary",
] as const;
type StepKey = (typeof STEP_KEYS)[number];

interface WizardState {
  questions: WizardQuestion[];
  brand: WizardBrand;
  competitors: WizardCompetitor[];
  models: string[];
  // Step 2 — 用户自定义分类(项目级)。提交时与 WIZARD_DEFAULT_CATEGORIES
  // 合并成 ``payload.categories`` 落 ``Project.category_taxonomy``;每条
  // 问题的 ``q.category`` 必须是「WIZARD_DEFAULT_CATEGORIES + 这里」
  // 中的一个。CategoriesStep 里通过每行问题的「细分标签」Select
  // (typeable,可输入添加) 维护这个列表;chip 区的 × 负责删除。
  customCategories: string[];
  monitor: WizardMonitor;
  // Step 6 — geo/sentiment/semantic。空 wizard 进入时已带默认值:
  // 全国随机 + 情感开 + 语义全空。``region_code`` 在 fixed 模式下必填,
  // 校验在 ``validateStep`` 里管。
  geo: WizardGeo;
  sentiment: WizardSentiment;
  semantic: WizardSemantic;
  customerId: number | null;
}

const initialBrand = (): WizardBrand => ({ name: "", product: null, aliases: [] });
const initialMonitor = (): WizardMonitor => ({
  devices: [],
  modes: [],
  schedules: { fast: null, think: null },
});
const initialGeo = (): WizardGeo => ({ mode: "national_random", region_code: null });
const initialSemantic = (): WizardSemantic => ({
  selling_points: [],
  website: null,
  phone: null,
  address: null,
  email: null,
  wechat_service: null,
  wechat_official: null,
  xiaohongshu: null,
  douyin: null,
  weibo: null,
  custom: null,
});

const emptyState = (): WizardState => ({
  questions: [],
  brand: initialBrand(),
  competitors: [],
  models: [],
  customCategories: [],
  monitor: initialMonitor(),
  geo: initialGeo(),
  sentiment: "on",
  semantic: initialSemantic(),
  customerId: null,
});

interface Props {
  /** 保留扩展点:以后若需在提交后回调(比如跳转 / 埋点),从这里接。
      当前流程下,wizard 内部已经弹 message.success 并清空表单回到
      step 1,不需要外部再做什么 —— 所以是可选的。 */
  onSubmitted?: (pendingId: number) => void;
}

// =====================================================================
// 工具函数
// =====================================================================

function freqRange(freq: string): { min: number; max: number } {
  const f = MONITOR_FREQUENCIES.find((x) => x.key === freq);
  if (!f) return { min: 0, max: 0 };
  return { min: f.min, max: Math.min(f.max, MONITOR_MAX_DAYS) };
}

function modelName(value: string): string {
  return MODELS.find((m) => m.value === value)?.name ?? value;
}

// =====================================================================
// Step 1 · 填写问题
// =====================================================================

function QuestionsStep({ state, setQuestions }: { state: WizardState; setQuestions: (next: WizardQuestion[]) => void }) {
  const [bulk, setBulk] = useState("");
  const addBulk = () => {
    const raw = bulk
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (raw.length === 0) return;
    const rest = WIZARD_MAX_QUESTIONS - state.questions.length;
    if (rest <= 0) return;
    const added = raw.slice(0, rest);
    setQuestions([
      ...state.questions,
      ...added.map<WizardQuestion>((text) => ({
        text,
        category: "引流类",
        tag: null,
      })),
    ]);
    setBulk("");
  };
  const remove = (idx: number) => {
    setQuestions(state.questions.filter((_, i) => i !== idx));
  };
  const clear = () => setQuestions([]);
  return (
    <div className="wizard-step">
      <div className="w-block">
        <div className="w-block-head">
          <h3>填写需要监控的问题</h3>
          <span className={`w-counter ${state.questions.length >= WIZARD_MAX_QUESTIONS ? "is-full" : ""}`}>
            {state.questions.length} / {WIZARD_MAX_QUESTIONS}
          </span>
        </div>
        <p className="w-desc">
          每行一个问题,支持批量粘贴。单个项目最多录入 {WIZARD_MAX_QUESTIONS} 个问题。
        </p>
        <TextArea
          rows={6}
          value={bulk}
          onChange={(e) => setBulk(e.target.value)}
          placeholder={`敏感肌护肤品牌推荐\n敏感肌可以用什么护肤品\n薇诺娜和珂润哪个好`}
        />
        <div className="w-row-actions">
          <Button type="primary" onClick={addBulk}>
            添加问题
          </Button>
          <Button type="text" onClick={clear} disabled={state.questions.length === 0}>
            清空
          </Button>
        </div>
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>已添加的问题</h3>
        </div>
        {state.questions.length === 0 ? (
          <div className="w-empty">还没有添加问题,请在上方输入或粘贴</div>
        ) : (
          <ul className="w-q-list">
            {state.questions.map((q, i) => (
              <li key={`${i}-${q.text}`} className="w-q-item">
                <span className="w-q-idx">{i + 1}</span>
                <span className="w-q-text" title={q.text}>
                  {q.text}
                </span>
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  aria-label="删除"
                  onClick={() => remove(i)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// =====================================================================
// Step 2 · 问题分类
//
// UI 模型:每行问题有「分类 seg-group (引流感 / 品牌类)」和「自定义
// 分类 Select」两个互斥的单选入口 —— 点其中任一,另一个自动取消选中。
//
// - seg-group 固定只渲染两个默认值,不可删、不可改;点击即把
//   ``q.category`` 设为该默认值,同时清掉 Select 里的值。
// - 自定义分类 Select 显示 ``state.customCategories``;支持输入
//   新分类并按 Enter 添加(同时选中);清除时 q.category 兜底回
//   「引流感」。Select 和 seg-group 共享同一个 q.category 字段,
//   所以二者天然互斥(同一个字段不可能同时是两个值)。
// - chip 区的 × 用来从项目级 taxonomy 里彻底移除一个自定义分类;
//   被删分类下的所有问题会回退到「引流感」。
//
// 提交时 ``payload.categories`` = WIZARD_DEFAULT_CATEGORIES +
// state.customCategories,后端会原样写到 ``Project.category_taxonomy``。
// =====================================================================

function CategoriesStep({
  state,
  setQuestions,
  setCustomCategories,
}: {
  state: WizardState;
  setQuestions: (next: WizardQuestion[]) => void;
  setCustomCategories: (next: string[]) => void;
}) {
  const customs = state.customCategories;
  const defaultFirst = WIZARD_DEFAULT_CATEGORIES[0];
  // 「编辑标签」Modal 的开关 + 弹层内正在编辑的新标签输入值。
  const [tagEditorOpen, setTagEditorOpen] = useState(false);
  const [pendingTag, setPendingTag] = useState("");

  const setCat = (idx: number, cat: string) => {
    setQuestions(
      state.questions.map((q, i) => (i === idx ? { ...q, category: cat } : q)),
    );
  };

  // 自定义分类 Select 的 onChange:值要么是 customs 里的某项,
  // 要么是 undefined(allowClear 清空)。清空时 q.category 兜底回
  // 「引流感」,与 seg-group 行为一致 —— 二者写入同一个字段,
  // 所以「选其一,另一项自动取消」靠这个事实保证,不用在 onChange
  // 里手动联动。
  const onCustomSelect = (idx: number, val: string | undefined) => {
    if (val === undefined || val === "") {
      setCat(idx, defaultFirst);
      return;
    }
    setCat(idx, val);
  };

  // 批量设置(「全部设为 X」按钮)。
  const batch = (cat: string) => {
    setQuestions(state.questions.map((q) => ({ ...q, category: cat })));
  };

  // 删自定义分类:同步把该分类名下的 question 回退到「引流感」,
  // 避免留下指向已不存在分类的 q.category。
  const removeCategory = (cat: string) => {
    setCustomCategories(customs.filter((c) => c !== cat));
    if (state.questions.some((q) => q.category === cat)) {
      setQuestions(
        state.questions.map((q) =>
          q.category === cat ? { ...q, category: defaultFirst } : q,
        ),
      );
    }
  };

  // 完整分类列表(默认值 + 自定义值),用来在「全部设为 X」按钮组
  // 和统计文本里统一渲染。
  const allCategories = [...WIZARD_DEFAULT_CATEGORIES, ...customs];

  return (
    <div className="wizard-step">
      <div className="w-tip-card">
        <div className="w-tip-title">分类口径</div>
        <ul className="w-tip-list">
          {WIZARD_DEFAULT_CATEGORIES.map((c) => (
            <li key={c}>
              <strong>{c}问题</strong>:{QUESTION_CATEGORY_TIPS[c]}。
            </li>
          ))}
          <li>
            <strong>细分标签</strong>:在问题行的「细分标签」下拉里输入
            新名字即可添加,口径自定,仅作用于本项目。
          </li>
        </ul>
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>问题分类</h3>
          <span className="w-sub-info">
            {allCategories
              .map(
                (c) =>
                  `${c} ${state.questions.filter((q) => q.category === c).length}`,
              )
              .join(" · ")}
          </span>
        </div>
        <div className="w-row-actions w-row-actions-split">
          <div className="w-row-actions-left">
            {WIZARD_DEFAULT_CATEGORIES.map((c) => (
              <Button
                key={c}
                onClick={() => batch(c)}
                disabled={state.questions.length === 0}
              >
                全部设为{c}
              </Button>
            ))}
          </div>
          <Button onClick={() => setTagEditorOpen(true)}>编辑标签</Button>
        </div>
      </div>

      <div className="w-block">
        {state.questions.length === 0 ? (
          <div className="w-empty">请返回上一步添加问题</div>
        ) : (
          <ul className="w-cat-list">
            {state.questions.map((q, i) => (
              <li key={`${i}-${q.text}`} className="w-cat-item">
                <span className="w-q-idx">{i + 1}</span>
                <span className="w-cat-text" title={q.text}>
                  {q.text}
                </span>
                <div className="w-seg-group" role="group" aria-label="问题大类">
                  {WIZARD_DEFAULT_CATEGORIES.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={`w-seg-item ${q.category === c ? "is-active" : ""}`}
                      onClick={() => setCat(i, c)}
                    >
                      {c}
                    </button>
                  ))}
                </div>
                <Select
                  // 单选,只允许从已经维护好的 ``customCategories`` 里选。
                  // 新增/删除走顶部「编辑标签」Modal,这里不开放输入,
                  // 避免在长问题列表里 50 个 Select 同时开 typeable 体验
                  // 失控。
                  value={customs.includes(q.category) ? q.category : undefined}
                  onChange={(v) => onCustomSelect(i, v)}
                  allowClear
                  placeholder="细分标签"
                  style={{ width: 180 }}
                  options={customs.map((c) => ({ value: c, label: c }))}
                  disabled={customs.length === 0}
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 「编辑标签」Modal —— 维护 ``customCategories`` 列表。新增/删除
          都只动这一个数组,被删标签下的 question 在 ``removeCategory`` 里
          同步回退到「引流感」,保证 q.category 永远指向一个有效分类。 */}
      <Modal
        title="编辑标签"
        open={tagEditorOpen}
        onCancel={() => {
          setTagEditorOpen(false);
          setPendingTag("");
        }}
        footer={null}
        destroyOnClose
        width={520}
      >
        <p className="w-desc w-desc-sm">
          在这里维护每个问题的「细分标签」可选值;输入新名字回车或点
          「添加」即可追加,点 chip 上的 × 移除(被该标签命中的问题会
          自动回退到「引流感」)。
        </p>
        <div className="w-row-addcat">
          <Input
            value={pendingTag}
            onChange={(e) => setPendingTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                const v = pendingTag.trim();
                if (!v || customs.includes(v)) {
                  setPendingTag("");
                  return;
                }
                setCustomCategories([...customs, v]);
                setPendingTag("");
              }
            }}
            placeholder="新标签名,如:对比类、用户人群、售后"
            maxLength={32}
            allowClear
            style={{ flex: 1 }}
          />
          <Button
            type="primary"
            onClick={() => {
              const v = pendingTag.trim();
              if (!v || customs.includes(v)) {
                setPendingTag("");
                return;
              }
              setCustomCategories([...customs, v]);
              setPendingTag("");
            }}
          >
            添加
          </Button>
        </div>
        {customs.length > 0 ? (
          <ul className="w-tag-edit-list">
            {customs.map((c) => (
              <li key={c} className="w-tag-edit-row">
                <span className="w-tag-edit-name">{c}</span>
                <Button
                  type="text"
                  size="small"
                  aria-label={`删除标签 ${c}`}
                  onClick={() => removeCategory(c)}
                >
                  删除
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="w-empty w-empty-sm">还没有自定义标签,在上方添加。</div>
        )}
      </Modal>
    </div>
  );
}

// =====================================================================
// Step 3 · 品牌与竞品
// =====================================================================

function BrandsStep({
  state,
  setBrand,
  setCompetitors,
}: {
  state: WizardState;
  setBrand: (next: WizardBrand) => void;
  setCompetitors: (next: WizardCompetitor[]) => void;
}) {
  return (
    <div className="wizard-step">
      <div className="w-block">
        <div className="w-block-head">
          <h3>自有品牌</h3>
          <span className="w-required">品牌名必填</span>
        </div>
        <div className="w-form-grid">
          <label className="w-field">
            <span className="w-label">品牌名 *</span>
            <Input
              value={state.brand.name}
              placeholder="如:薇诺娜"
              onChange={(e) => setBrand({ ...state.brand, name: e.target.value })}
            />
          </label>
          <label className="w-field">
            <span className="w-label">产品名</span>
            <Input
              value={state.brand.product ?? ""}
              placeholder="如:舒敏保湿特护霜"
              onChange={(e) =>
                setBrand({
                  ...state.brand,
                  product: e.target.value.trim() ? e.target.value : null,
                })
              }
            />
          </label>
        </div>
        <label className="w-field">
          <span className="w-label">别名</span>
          <AliasesEditor
            aliases={state.brand.aliases}
            onChange={(next) => setBrand({ ...state.brand, aliases: next })}
          />
        </label>
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>竞品名称</h3>
          <span className="w-sub-info">支持添加多个竞品</span>
        </div>
        {state.competitors.length === 0 ? (
          <div className="w-empty">暂无竞品,可点击下方按钮添加</div>
        ) : (
          state.competitors.map((c, idx) => (
            <div key={idx} className="w-comp-card">
              <div className="w-comp-head">
                <strong>竞品 {idx + 1}</strong>
                <Button type="text" size="small" onClick={() =>
                  setCompetitors(state.competitors.filter((_, i) => i !== idx))
                }>
                  删除
                </Button>
              </div>
              <div className="w-form-grid">
                <label className="w-field">
                  <span className="w-label">品牌名</span>
                  <Input
                    value={c.name}
                    placeholder="如:珂润"
                    onChange={(e) =>
                      setCompetitors(
                        state.competitors.map((x, i) =>
                          i === idx ? { ...x, name: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </label>
                <label className="w-field">
                  <span className="w-label">产品名</span>
                  <Input
                    value={c.product ?? ""}
                    placeholder="如:润浸保湿面霜"
                    onChange={(e) =>
                      setCompetitors(
                        state.competitors.map((x, i) =>
                          i === idx
                            ? {
                                ...x,
                                product: e.target.value.trim() ? e.target.value : null,
                              }
                            : x,
                        ),
                      )
                    }
                  />
                </label>
              </div>
              <label className="w-field">
                <span className="w-label">别名</span>
                <AliasesEditor
                  aliases={c.aliases}
                  onChange={(next) =>
                    setCompetitors(
                      state.competitors.map((x, i) =>
                        i === idx ? { ...x, aliases: next } : x,
                      ),
                    )
                  }
                />
              </label>
            </div>
          ))
        )}
        <div className="w-row-actions">
          <Button
            onClick={() =>
              setCompetitors([
                ...state.competitors,
                { name: "", product: null, aliases: [] },
              ])
            }
          >
            + 添加竞品
          </Button>
        </div>
      </div>
    </div>
  );
}

/** 别名标签输入 —— 回车 / 逗号生成 tag,× 删除,最多 10 个。 */
function AliasesEditor({
  aliases,
  onChange,
}: {
  aliases: string[];
  onChange: (next: string[]) => void;
}) {
  const [pending, setPending] = useState("");
  const commit = () => {
    const v = pending.trim().replace(/[,，]$/, "");
    if (!v) return;
    if (aliases.includes(v)) {
      setPending("");
      return;
    }
    if (aliases.length >= 10) {
      setPending("");
      return;
    }
    onChange([...aliases, v]);
    setPending("");
  };
  return (
    <div className="w-tag-input">
      {aliases.map((a) => (
        <span key={a} className="w-tag">
          {a}
          <button
            type="button"
            className="w-tag-x"
            aria-label="删除"
            onClick={() => onChange(aliases.filter((x) => x !== a))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        className="w-tag-field"
        placeholder="输入后回车添加"
        value={pending}
        onChange={(e) => setPending(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          }
        }}
      />
    </div>
  );
}

// =====================================================================
// Step 4 · 选择模型
// =====================================================================

function ModelsStep({
  state,
  setModels,
}: {
  state: WizardState;
  setModels: (next: string[]) => void;
}) {
  const toggle = (value: string) => {
    setModels(
      state.models.includes(value)
        ? state.models.filter((m) => m !== value)
        : [...state.models, value],
    );
  };
  const selectAll = () => setModels(MODELS.map((m) => m.value));
  const clear = () => setModels([]);
  return (
    <div className="wizard-step">
      <div className="w-block">
        <div className="w-block-head">
          <h3>选择需要监控的大模型</h3>
          <span className="w-counter">
            已选 {state.models.length} / {MODELS.length}
          </span>
        </div>
        <p className="w-desc">可选择单个或多个模型,监控结果将按所选模型分别统计。</p>
        <div className="w-model-grid">
          {MODELS.map((m) => {
            const on = state.models.includes(m.value);
            return (
              <button
                key={m.value}
                type="button"
                className={`w-model-card ${on ? "is-active" : ""}`}
                onClick={() => toggle(m.value)}
              >
                <span className="w-model-dot" style={{ background: m.color }} />
                <span className="w-model-name">{m.name}</span>
                <span className="w-model-check">{on ? "✓" : ""}</span>
              </button>
            );
          })}
        </div>
        <div className="w-row-actions">
          <Button onClick={selectAll}>全选</Button>
          <Button type="text" onClick={clear} disabled={state.models.length === 0}>
            清空
          </Button>
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// Step 5 · 监控配置
//
// v4: 每个模式(快速 / 思考)单独一组 freq + days,可以分别配置监控频率。
// 平台(``devices`` / ``modes``) 与调度(``schedules``) 在这一步分开:
// 平台决定哪些 ``ProjectPlatform`` 行被展开;调度决定哪些模式在哪些
// 工作日触发。一个项目可以「开了思考平台但只调度快速平台」,
// 慢思考模式下不必每天跑。
// =====================================================================

function MonitorStep({
  state,
  setMonitor,
}: {
  state: WizardState;
  setMonitor: (next: WizardMonitor) => void;
}) {
  const { message } = App.useApp();
  const toggleDevice = (id: "pc" | "mobile") => {
    const arr = state.monitor.devices;
    // 勾选「移动端」前校验:已选模型中是否有无移动版的(Kimi / 蚂蚁阿福);
    // 有则阻断勾选并提示,避免下游写出 platform=kimi + DeliveryMode.MOBILE
    // 这种找不到对应 modelCode 的组合。
    if (id === "mobile" && !arr.includes("mobile")) {
      const noMobile = state.models
        .map((v) => WIZARD_MODELS.find((m) => m.value === v))
        .filter((m): m is WizardModelOption => !!m && !m.hasMobile);
      if (noMobile.length > 0) {
        message.error(
          `已选模型「${noMobile.map((m) => m.name).join("、")}」无移动端版本,无法监控移动端`,
        );
        return;
      }
    }
    setMonitor({
      ...state.monitor,
      devices: arr.includes(id) ? arr.filter((d) => d !== id) : [...arr, id],
    });
  };
  const toggleMode = (id: "fast" | "think") => {
    const arr = state.monitor.modes;
    setMonitor({
      ...state.monitor,
      modes: arr.includes(id) ? arr.filter((m) => m !== id) : [...arr, id],
    });
  };
  // 把 mode 这一格的 schedule 整体设为 ``null`` 等价于「不调度该模式」;
  // 设成一个 ``WizardMonitorEntry`` 才会真正出现在 cron 里。
  const setModeEntry = (
    modeKey: "fast" | "think",
    entry: WizardMonitorEntry | null,
  ) => {
    const schedules = { ...(state.monitor.schedules || {}) };
    schedules[modeKey] = entry;
    setMonitor({ ...state.monitor, schedules });
  };
  return (
    <div className="wizard-step is-compact">
      <div className="w-block">
        <div className="w-block-head">
          <h3>终端选择</h3>
        </div>
        <p className="w-desc">可选 PC 端与移动端联合监控,也可只监控其中一个。</p>
        <div className="w-seg-group w-seg-lg">
          {ANSWER_DEVICES.map((d) => (
            <button
              key={d.id}
              type="button"
              className={`w-seg-item ${state.monitor.devices.includes(d.id) ? "is-active" : ""}`}
              onClick={() => toggleDevice(d.id)}
            >
              {d.name}
            </button>
          ))}
        </div>
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>模式选择</h3>
        </div>
        <p className="w-desc">快速模式调用成本低、覆盖广;思考模式推理更深,答案质量与正确率更高。</p>
        <div className="w-seg-group w-seg-lg">
          {ANSWER_MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`w-seg-item ${state.monitor.modes.includes(m.id) ? "is-active" : ""}`}
              onClick={() => toggleMode(m.id)}
            >
              {m.name}
            </button>
          ))}
        </div>
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>监控频率(按模式)</h3>
        </div>
        <p className="w-desc">
          每个模式可以独立配置监控频率。开启后该模式会按所选工作日触发;不勾选则该模式不入调度。
        </p>
        <div className="w-freq-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {ANSWER_MODES.map((m) => {
            const entry = state.monitor.schedules?.[m.id] ?? null;
            return (
              <ModeScheduleCard
                key={m.id}
                modeKey={m.id}
                modeName={m.id === "fast" ? "快速" : "思考"}
                entry={entry}
                onChange={(next) => setModeEntry(m.id, next)}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** 单个模式(快速 / 思考)的 freq + days 编辑卡片。

 *  ``entry=null`` 表示「不调度该模式」,展开后是一个 "启用" 按钮;
 *  ``entry`` 存在时是 freq 选择 + 周几勾选 + 「关闭调度」链接。
 */
function ModeScheduleCard({
  modeKey: _modeKey,
  modeName,
  entry,
  onChange,
}: {
  modeKey: "fast" | "think";
  modeName: string;
  entry: WizardMonitorEntry | null;
  onChange: (next: WizardMonitorEntry | null) => void;
}) {
  const setFreq = (key: WizardFreq) => {
    // 切换频率清空日期,避免出现与新频率不匹配的残留选择。
    onChange({ freq: key, days: [] });
  };
  const toggleDay = (key: WizardDay) => {
    const current = entry ?? { freq: "w1" as WizardFreq, days: [] };
    const arr = current.days;
    let next: WizardDay[];
    if (arr.includes(key)) {
      next = arr.filter((d) => d !== key);
    } else {
      const r = freqRange(current.freq);
      if (arr.length >= r.max) return;
      next = [...arr, key].sort((a, b) => Number(a) - Number(b));
    }
    onChange({ freq: current.freq, days: next });
  };
  const applyPreset = (key: string) => {
    const ps = WEEKDAY_PRESETS.find((p) => p.key === key);
    if (!ps || !entry) return;
    const r = freqRange(entry.freq);
    onChange({ freq: entry.freq, days: ps.days.slice(0, r.max) });
  };
  const clearDays = () => {
    if (!entry) return;
    onChange({ freq: entry.freq, days: [] });
  };
  if (!entry) {
    return (
      <div className="w-mode-schedule-card is-disabled">
        <div className="w-block-head">
          <h3>{modeName}模式调度</h3>
        </div>
        <p className="w-desc">未启用 —— 不会在 cron 中触发。</p>
        <Button
          type="default"
          onClick={() => onChange({ freq: "w1", days: [] })}
        >
          启用{modeName}模式调度
        </Button>
      </div>
    );
  }
  const range = freqRange(entry.freq);
  const freqObj = MONITOR_FREQUENCIES.find((f) => f.key === entry.freq);
  return (
    <div className="w-mode-schedule-card">
      <div className="w-block-head">
        <h3>{modeName}模式调度</h3>
        <Button
          type="link"
          size="small"
          onClick={() => onChange(null)}
          style={{ padding: 0 }}
        >
          关闭调度
        </Button>
      </div>
      <div className="w-freq-grid">
        {MONITOR_FREQUENCIES.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`w-freq-card ${entry.freq === f.key ? "is-active" : ""}`}
            onClick={() => setFreq(f.key)}
          >
            <span className="w-freq-label">{f.label}</span>
            <span className="w-freq-hint">{f.hint}</span>
          </button>
        ))}
      </div>
      <div className="w-block" style={{ marginTop: 12 }}>
        <div className="w-block-head">
          <h3>监控日期</h3>
          <span className="w-sub-info">
            {freqObj
              ? `${freqObj.label} · 可选 ${range.min}${range.min === range.max ? "" : " ~ " + range.max} 天`
              : "请先选择频率"}
          </span>
        </div>
        <div className="w-day-bar">
          <span
            className={`w-day-count ${entry.days.length >= range.max ? "is-full" : ""}`}
          >
            已选 {entry.days.length} 天 · 每周采集 {entry.days.length} 次
            {entry.days.length >= range.max ? "(已达上限)" : ""}
          </span>
          {range.min !== range.max && (
            <span className="w-day-presets">
              {WEEKDAY_PRESETS.map((ps) => (
                <Button
                  key={ps.key}
                  size="small"
                  onClick={() => applyPreset(ps.key)}
                >
                  {ps.label}
                </Button>
              ))}
              <Button size="small" onClick={clearDays}>
                清空
              </Button>
            </span>
          )}
        </div>
        <div className="w-day-group">
          {WEEKDAYS.map((d) => (
            <button
              key={d.key}
              type="button"
              className={`w-day-item ${entry.days.includes(d.key) ? "is-active" : ""}`}
              onClick={() => toggleDay(d.key)}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// Step 6 · 监控配置② —— 提问位置 + 情感分析 + 语义监控
//
// 设计稿 docs/风球GEO监控平台UI/js/wizard.js#viewGeo 的 React 化;
// 注意这里把多选 grid 改成了单选 Select —— Molizhishu 提交任务时
// regionCode 数组只允许 1 个元素
// (https://github.com/molizhishu/molizhishu-api-pub/blob/main/docs/api/city-info.md §调用约定),
// 多选没有意义。
// =====================================================================

/** 一次性拉取省份清单 + 简单重试。挂在组件外避免每次重渲都重抓。 */
function useMolizhishuCities() {
  const [cities, setCities] = useState<Province[] | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listMolizhishuCities();
      setCities(res.items);
      setWarning(res.warning);
    } catch (e) {
      setCities([]);
      setWarning((e as Error).message || "拉取失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  return { cities, warning, loading, reload: load };
}

function GeoStep({
  state,
  setGeo,
  setSentiment,
  setSemantic,
}: {
  state: WizardState;
  setGeo: (next: WizardGeo) => void;
  setSentiment: (next: WizardSentiment) => void;
  setSemantic: (next: WizardSemantic) => void;
}) {
  const { cities, warning, loading, reload } = useMolizhishuCities();
  const setMode = (mode: WizardGeoMode) => {
    // 切到 random 就把残留的 region_code 抹掉,避免切换后还带着一个
    // 无用的固定码,后端审批时 fixed + null 会回退到 region_codes=None。
    setGeo({
      mode,
      region_code: mode === "fixed" ? state.geo.region_code : null,
    });
  };
  const setRegionCode = (code: string | null) =>
    setGeo({ ...state.geo, region_code: code });

  // 语义监控 —— 输入过程不重渲整个步骤,否则光标会丢。这里直接改
  // 上层 setSemantic 让整个 state 引用换掉即可,但 RHF 风格地按字段
  // 改 setter 更直观。
  const setSemanticField = <K extends keyof WizardSemantic>(
    key: K,
    value: WizardSemantic[K],
  ) => setSemantic({ ...state.semantic, [key]: value });

  return (
    <div className="wizard-step is-compact">
      <div className="w-block">
        <div className="w-block-head">
          <h3>提问位置</h3>
        </div>
        <p className="w-desc">
          通过多 IP 方式实现地域投放。不同地区的 AI 答案存在差异,
          可按区域采样对比。
        </p>
        <div className="w-freq-grid">
          {WIZARD_REGION_MODES.map((m: WizardRegionModeOption) => (
            <button
              key={m.key}
              type="button"
              className={`w-freq-card ${state.geo.mode === m.key ? "is-active" : ""}`}
              onClick={() => setMode(m.key)}
            >
              <span className="w-freq-label">{m.label}</span>
              <span className="w-freq-hint">{m.hint}</span>
            </button>
          ))}
        </div>
        {state.geo.mode === "fixed" && (
          <div className="w-region-wrap">
            {loading && <div className="w-empty">正在加载省份清单…</div>}
            {!loading && (cities === null || cities.length === 0) && (
              <div className="w-empty">
                {warning ?? "暂无可用区域"}
                <Button
                  size="small"
                  type="link"
                  onClick={reload}
                  style={{ marginLeft: 8 }}
                >
                  重试
                </Button>
              </div>
            )}
            {!loading && cities && cities.length > 0 && (
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择一个省份"
                value={state.geo.region_code ?? undefined}
                onChange={(v) => setRegionCode(v ?? null)}
                options={cities.map((c) => ({
                  value: c.code,
                  label: c.name,
                }))}
                style={{ width: 320 }}
              />
            )}
            {warning && cities && cities.length > 0 && (
              <p className="w-desc w-desc-warn">{warning}(展示的是缓存数据)</p>
            )}
          </div>
        )}
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>情感分析</h3>
        </div>
        <p className="w-desc">
          开启后将对 AI 答案中的品牌提及进行情感倾向判定
          (正面 / 中性 / 负面)。
        </p>
        <div className="w-seg-group w-seg-lg">
          {WIZARD_SENTIMENT_OPTIONS.map((o) => (
            <button
              key={o.key}
              type="button"
              className={`w-seg-item ${state.sentiment === o.key ? "is-active" : ""}`}
              onClick={() => setSentiment(o.key)}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="w-block">
        <div className="w-block-head">
          <h3>语义监控</h3>
          <span className="w-sub-info">选填 · 已填 {semanticFilledCount(state.semantic)} 项</span>
        </div>
        <p className="w-desc">
          填写品牌的核心卖点,用于判断 AI 答案是否准确提及。
          <strong>未填写时,语义分析结果页将显示空白。</strong>
        </p>
        <div className="w-sem-grid">
          {WIZARD_SEMANTIC_FIELDS.map((f) => (
            <SemanticField
              key={f.key}
              field={f}
              value={state.semantic[f.key]}
              onChange={(v) => setSemanticField(f.key, v)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function SemanticField({
  field,
  value,
  onChange,
}: {
  field: WizardSemanticField;
  value: WizardSemantic[keyof WizardSemantic];
  onChange: (v: WizardSemantic[keyof WizardSemantic]) => void;
}) {
  // 语义监控只剩 selling_points 一项(多行 textarea,每行一条卖点,最多 10 行)。
  // selling_points 在 state 里是 string[],UI 层用 \n 连接展示,onChange 时
  // 仅按 \n 拆成数组 —— 不动行内容(不 trim / 不过滤空行),保证用户在末尾按
  // Enter 时 DOM 是 "foo\n" → split 出 ["foo", ""] 后,React 受控 prop 会写成
  // "foo\n",换行才不被吞掉。10 行上限在提交时统一截断。
  const text =
    typeof value === "string"
      ? value
      : Array.isArray(value)
        ? (value as string[]).join("\n")
        : "";
  const handleChange = (next: string) => {
    onChange(next.split("\n"));
  };
  return (
    <div className="w-sem-item w-sem-full">
      <label className="w-sem-label">{field.label}</label>
      <TextArea
        rows={5}
        placeholder={field.placeholder}
        value={text}
        onChange={(e) => handleChange(e.target.value)}
      />
      <p className="w-desc w-desc-sm" style={{ marginTop: 4 }}>
        每行一条卖点,最多 10 行;超出部分将被截断。
      </p>
    </div>
  );
}

function semanticFilledCount(s: WizardSemantic): number {
  return s.selling_points.length > 0 ? 1 : 0;
}

/** 汇总页用的语义文案:未填写时给一个明确提示。 */
function semanticSummary(s: WizardSemantic): React.ReactNode {
  const filled = semanticFilledCount(s);
  if (filled === 0) {
    return <span style={{ color: "var(--text-tertiary)" }}>未填写 · 语义分析结果页将显示空白</span>;
  }
  return (
    <>
      <span style={{ color: "var(--text-tertiary)" }}>已填 {filled} 项</span>
      {s.selling_points.length > 0 && (
        <div className="w-sum-sub">
          <span className="w-sum-sub-k">核心卖点</span>
          <Space size={4} wrap>
            {s.selling_points.map((t) => (
              <span key={t} className="w-tag">
                {t}
              </span>
            ))}
          </Space>
        </div>
      )}
    </>
  );
}

function geoSummary(g: WizardGeo): React.ReactNode {
  if (g.mode === "fixed") {
    return (
      <span>
        指定区域 ·{" "}
        <span className="w-tag">{g.region_code ?? "(未选省份)"}</span>
      </span>
    );
  }
  return <span>全国随机(每次采集随机分配 IP 属地)</span>;
}

function sentimentSummary(s: WizardSentiment): React.ReactNode {
  return s === "on" ? (
    <span style={{ color: "var(--text-tertiary)" }}>开启分析</span>
  ) : (
    <span style={{ color: "var(--text-tertiary)" }}>关闭分析</span>
  );
}

// =====================================================================
// Step 7 · 配置汇总确认
// =====================================================================

function SummaryStep({
  state,
  setCustomerId,
  customers,
  customerOptionsLoading,
  isSuper,
}: {
  state: WizardState;
  setCustomerId: (id: number | null) => void;
  customers: Customer[];
  customerOptionsLoading: boolean;
  isSuper: boolean;
}) {
  const m = state.monitor;
  const dayLabels = (entry: WizardMonitorEntry | null) =>
    (entry?.days ?? [])
      .map((k: WizardDay) => WEEKDAYS.find((d) => d.key === k)?.label ?? k)
      .join("、");
  const freqLabel = (entry: WizardMonitorEntry | null) =>
    (entry && MONITOR_FREQUENCIES.find((f) => f.key === entry.freq)?.label) || "—";
  const row = (label: string, value: React.ReactNode) => (
    <div className="w-sum-row">
      <span className="w-sum-label">{label}</span>
      <span className="w-sum-value">{value}</span>
    </div>
  );
  return (
    <div className="wizard-step">
      <div className="w-summary">
        <div className="w-sum-card">
          <div className="w-sum-head">项目问题</div>
          {row("问题总数", `${state.questions.length} 个`)}
          {[...WIZARD_DEFAULT_CATEGORIES, ...state.customCategories].map((c) =>
            row(c, `${state.questions.filter((q) => q.category === c).length} 个`),
          )}
          {row("已标细分标签", `${state.questions.filter((q) => q.tag).length} 个`)}
        </div>

        <div className="w-sum-card">
          <div className="w-sum-head">品牌与竞品</div>
          {row("自有品牌", state.brand.name.trim() || "—")}
          {row("产品名", state.brand.product?.trim() || "—")}
          {row(
            "别名",
            state.brand.aliases.length > 0 ? (
              <Space size={4} wrap>
                {state.brand.aliases.map((a) => (
                  <span key={a} className="w-tag">
                    {a}
                  </span>
                ))}
              </Space>
            ) : (
              "—"
            ),
          )}
          {row("竞品数量", `${state.competitors.length} 个`)}
          {state.competitors.map((c, i) =>
            row(
              `竞品 ${i + 1}`,
              `${c.name.trim() || "未命名"}${c.product ? " · " + c.product : ""}${
                c.aliases.length ? " · " + c.aliases.join("/") : ""
              }`,
            ),
          )}
        </div>

        <div className="w-sum-card">
          <div className="w-sum-head">监控模型</div>
          {row("已选模型", `${state.models.length} 个`)}
          {row(
            "模型清单",
            state.models.length > 0 ? (
              <Space size={4} wrap>
                {state.models.map((v) => (
                  <span key={v} className="w-tag">
                    {modelName(v)}
                  </span>
                ))}
              </Space>
            ) : (
              "—"
            ),
          )}
        </div>

        <div className="w-sum-card">
          <div className="w-sum-head">监控配置</div>
          {row(
            "终端",
            m.devices
              .map((d) => ANSWER_DEVICES.find((x) => x.id === d)?.name ?? d)
              .join(" + ") || "—",
          )}
          {row(
            "模式",
            m.modes
              .map((md) => ANSWER_MODES.find((x) => x.id === md)?.name ?? md)
              .join(" + ") || "—",
          )}
          {row(
            "快速模式调度",
            m.schedules?.fast
              ? `${freqLabel(m.schedules.fast)} · ${dayLabels(m.schedules.fast) || "未选日期"}`
              : "未启用",
          )}
          {row(
            "思考模式调度",
            m.schedules?.think
              ? `${freqLabel(m.schedules.think)} · ${dayLabels(m.schedules.think) || "未选日期"}`
              : "未启用",
          )}
        </div>

        <div className="w-sum-card">
          <div className="w-sum-head">提问位置 / 情感分析 / 语义监控</div>
          {row("提问位置", geoSummary(state.geo))}
          {row("情感分析", sentimentSummary(state.sentiment))}
          {row("语义监控", semanticSummary(state.semantic))}
        </div>

        <div className="w-sum-card">
          <div className="w-sum-head">目标客户</div>
          {isSuper ? (
            <Select
              value={state.customerId ?? undefined}
              loading={customerOptionsLoading}
              placeholder="选择目标客户"
              options={customers.map((c) => ({
                value: c.id,
                label: `${c.name} (#${c.id})`,
              }))}
              onChange={(v) => setCustomerId(v as number)}
              showSearch
              optionFilterProp="label"
              style={{ width: 320 }}
            />
          ) : (
            <span style={{ color: "var(--text-tertiary)" }}>(由系统强制为您的客户)</span>
          )}
        </div>
      </div>

      <div className="w-submit-note">
        提交后项目将进入<strong>待审核</strong>状态,可在「待审核」列表中查看。审核通过后开始首次采集。
      </div>
    </div>
  );
}

// =====================================================================
// 自定义步骤条 —— 圆点 + 标题 + 连接线
// current:实心蓝填充 + 外发光 ring;done:浅蓝底 + ✓;pending:灰底序号。
// =====================================================================

const STEP_META: { key: StepKey; title: string; icon: React.ReactNode }[] = [
  { key: "questions", title: "填写问题", icon: <ProfileOutlined /> },
  { key: "categories", title: "问题分类", icon: <TagsOutlined /> },
  { key: "brands", title: "品牌与竞品", icon: <ShopOutlined /> },
  { key: "models", title: "选择模型", icon: <RobotOutlined /> },
  { key: "monitor", title: "监控配置", icon: <ScheduleOutlined /> },
  { key: "geo", title: "监控配置②", icon: <EnvironmentOutlined /> },
  { key: "summary", title: "确认提交", icon: <CheckCircleOutlined /> },
];

function WizardSteps({ current }: { current: number }) {
  return (
    <div className="wizard-steps">
      {STEP_META.map((s, i) => {
        const state = i < current ? "is-done" : i === current ? "is-current" : "";
        return (
          <Fragment key={s.key}>
            {i > 0 && <span className="w-step-line" />}
            <div className={`w-step ${state}`}>
              <span className="w-step-dot">
                {i < current ? <CheckOutlined /> : i + 1}
              </span>
              <span className="w-step-title">{s.title}</span>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

// =====================================================================
// 主 wizard 容器
// =====================================================================

export default function NewProjectWizard(_props: Props) {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";

  const [step, setStep] = useState<StepKey>("questions");
  const [state, setState] = useState<WizardState>(emptyState);
  const [submitting, setSubmitting] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(false);

  useEffect(() => {
    if (!isSuper) return;
    setCustomersLoading(true);
    listCustomers({ page: 1, size: 100 })
      .then((data) => setCustomers(data.items))
      .catch(() => setCustomers([]))
      .finally(() => setCustomersLoading(false));
  }, [isSuper]);

  const stepIndex = useMemo(() => STEP_KEYS.indexOf(step), [step]);

  const setQuestions = (next: WizardQuestion[]) =>
    setState((s) => ({ ...s, questions: next }));
  const setCustomCategories = (next: string[]) =>
    setState((s) => ({ ...s, customCategories: next }));
  const setBrand = (next: WizardBrand) =>
    setState((s) => ({ ...s, brand: next }));
  const setCompetitors = (next: WizardCompetitor[]) =>
    setState((s) => ({ ...s, competitors: next }));
  const setModels = (next: string[]) =>
    setState((s) => ({ ...s, models: next }));
  const setMonitor = (next: WizardMonitor) =>
    setState((s) => ({ ...s, monitor: next }));
  const setGeo = (next: WizardGeo) =>
    setState((s) => ({ ...s, geo: next }));
  const setSentiment = (next: WizardSentiment) =>
    setState((s) => ({ ...s, sentiment: next }));
  const setSemantic = (next: WizardSemantic) =>
    setState((s) => ({ ...s, semantic: next }));
  const setCustomerId = (id: number | null) =>
    setState((s) => ({ ...s, customerId: id }));

  const validateStep = (s: StepKey): string | null => {
    switch (s) {
      case "questions":
        if (state.questions.length === 0) return "请至少添加 1 个问题";
        return null;
      case "categories":
        return null;
      case "brands":
        if (!state.brand.name.trim()) return "请填写自有品牌名";
        return null;
      case "models":
        if (state.models.length === 0) return "请至少选择 1 个监控模型";
        return null;
      case "monitor": {
        const m = state.monitor;
        if (m.devices.length === 0) return "请选择监控终端";
        if (m.modes.length === 0) return "请选择监控模式";
        // At least one mode must be scheduled — a wizard that picks
        // platforms but no schedule still flips ``schedule_enabled`` to
        // false on submit, which silently breaks the project. Validation
        // runs before submit so the operator gets an upfront error.
        const schedules = m.schedules || {};
        const scheduled = (["fast", "think"] as const).filter(
          (k) => schedules[k] !== null && schedules[k] !== undefined,
        );
        if (scheduled.length === 0) return "请至少为 1 个模式启用监控调度";
        for (const k of scheduled) {
          const entry = schedules[k]!;
          const range = freqRange(entry.freq);
          if (entry.days.length < range.min) {
            return range.min === range.max
              ? `${k === "fast" ? "快速" : "思考"}模式请选择 ${range.min} 个监控日期`
              : `${k === "fast" ? "快速" : "思考"}模式请至少选择 ${range.min} 个监控日期`;
          }
          if (entry.days.length > range.max) {
            return `${k === "fast" ? "快速" : "思考"}模式当前频率每周最多 ${range.max} 次`;
          }
        }
        return null;
      }
      case "geo":
        // 全国随机恒通过;指定区域必须选 1 个省份。情感分析有默认值
        // (on),语义监控选填,均不阻塞提交。
        if (state.geo.mode === "fixed" && !state.geo.region_code) {
          return "请选择一个省份";
        }
        return null;
      case "summary":
        if (isSuper && state.customerId === null) return "请选择目标客户";
        return null;
    }
  };

  const goNext = () => {
    const err = validateStep(step);
    if (err) {
      setHint(err);
      return;
    }
    setHint(null);
    const next = STEP_KEYS[stepIndex + 1];
    if (next) setStep(next);
  };
  const goPrev = () => {
    setHint(null);
    const prev = STEP_KEYS[stepIndex - 1];
    if (prev) setStep(prev);
  };

  const submit = async () => {
    // 提交前校验全部 step(含 summary —— super_admin 必须已选目标客户)。
    for (const s of STEP_KEYS) {
      const err = validateStep(s);
      if (err) {
        setHint(`第 ${STEP_KEYS.indexOf(s) + 1} 步未完成:${err}`);
        setStep(s);
        return;
      }
    }
    const payload: WizardPayload = {
      questions: state.questions.map((q) => ({ ...q, text: q.text.trim() })),
      brand: state.brand,
      competitors: state.competitors.filter((c) => c.name.trim()),
      models: state.models,
      // 向导只收「模型 × 终端」两个维度,逐卡配置是 待审核 modal
      // 的能力;留空让后端走笛卡尔展开。
      models_config: [],
      monitor: state.monitor,
      // 默认分类 + 自定义分类,顺序保持 WIZARD_DEFAULT_CATEGORIES 在前。
      categories: [...WIZARD_DEFAULT_CATEGORIES, ...state.customCategories],
      geo: state.geo,
      sentiment: state.sentiment,
      // 语义监控只在保存时截断 selling_points 到 10 行,textarea 本身不限。
      semantic: {
        ...state.semantic,
        selling_points: state.semantic.selling_points.slice(0, 10),
      },
    };
    setSubmitting(true);
    try {
      const body: { customer_id?: number; payload: WizardPayload } = {
        payload,
      };
      if (isSuper && state.customerId !== null) {
        body.customer_id = state.customerId;
      }
      await submitWizardProject(body);
      // 成功提交 → 弹提示、清空向导、回到「填写问题」步骤。
      // 不调用 onSubmitted(navigate):用户应留在本页继续下一份。
      // 状态重置放最前面,message 失败也不影响向导重置。
      setState(emptyState());
      setStep("questions");
      setHint(null);
      message.success("提交成功,已进入待审核队列");
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || (e as Error).message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="new-project-wizard">
      <WizardSteps current={stepIndex} />
      <div className="wizard-body">
        {step === "questions" && (
          <QuestionsStep state={state} setQuestions={setQuestions} />
        )}
        {step === "categories" && (
          <CategoriesStep
            state={state}
            setQuestions={setQuestions}
            setCustomCategories={setCustomCategories}
          />
        )}
        {step === "brands" && (
          <BrandsStep
            state={state}
            setBrand={setBrand}
            setCompetitors={setCompetitors}
          />
        )}
        {step === "models" && <ModelsStep state={state} setModels={setModels} />}
        {step === "monitor" && (
          <MonitorStep state={state} setMonitor={setMonitor} />
        )}
        {step === "geo" && (
          <GeoStep
            state={state}
            setGeo={setGeo}
            setSentiment={setSentiment}
            setSemantic={setSemantic}
          />
        )}
        {step === "summary" && (
          <SummaryStep
            state={state}
            setCustomerId={setCustomerId}
            customers={customers}
            customerOptionsLoading={customersLoading}
            isSuper={isSuper}
          />
        )}
        {step === "summary" && isSuper && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8, marginBottom: 12 }}
            message="提交后,后台会在「待审核」列表里看到这条申请。"
          />
        )}
      </div>
      <div className="wizard-footer">
        <div className="wizard-footer-left">
          {hint && <span className="wizard-hint">{hint}</span>}
        </div>
        <div className="wizard-footer-right">
          <Button onClick={goPrev} disabled={stepIndex === 0 || submitting}>
            上一步
          </Button>
          {step !== "summary" ? (
            <Button type="primary" onClick={goNext}>
              下一步
            </Button>
          ) : (
            <Button
              type="primary"
              onClick={submit}
              loading={submitting}
              icon={<CheckCircleOutlined />}
            >
              提交审核
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}