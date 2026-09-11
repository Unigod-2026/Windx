import {
  Alert,
  App,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Tooltip,
  message,
} from "antd";
import {
  CheckOutlined,
  CloseOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { CirclePlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  approveProject,
  createCompetitor,
  deleteCompetitor,
  getLlmPricing,
  getProject,
  listCompetitors,
  putKeywords,
  putWizardDraft,
  rejectProject,
  submitWizardProject,
  updateCompetitor,
  updateProject,
  withdrawProject,
  type CompetitorOut,
  type ProjectDetailOut,
  type WizardCompetitor,
  type WizardDay,
  type WizardDevice,
  type WizardFreq,
  type WizardGeo,
  type WizardMode,
  type WizardModelConfig,
  type WizardMonitor,
  type WizardMonitorEntry,
  type WizardPayload,
  type WizardQuestion,
  type WizardSemantic,
  type WizardSentiment,
} from "../../api/projects";
import { listMolizhishuCities, type Province } from "../../api/molizhishu";
import { useAuth } from "../../auth/AuthProvider";
import BrandEditModal from "./BrandEditModal";
// 注:模型列表改用 WIZARD_MODELS + WIZARD_MODEL_CARD_CODES,PLATFORM_CATALOG
// 不再被本 modal 用到。
import {
  WIZARD_MODEL_MODES,
  WIZARD_MODELS,
  WIZARD_MONITOR_FREQUENCIES,
  WIZARD_SEMANTIC_FIELDS,
  WIZARD_SENTIMENT_OPTIONS,
  WIZARD_WEEKDAYS,
  WIZARD_WEEKDAY_PRESETS,
  type WizardSemanticField,
} from "./wizardConfig";

function SectionTitle(props: {
  title: string;
  required?: boolean;
  extra?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 6,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text-primary)" }}>
        {props.title}
        {props.required && <span style={{ color: "#ef4444", marginLeft: 2 }}>*</span>}
      </div>
      {props.extra}
    </div>
  );
}

function Card(props: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "#fff",
        borderRadius: 8,
        padding: 14,
        marginBottom: 10,
        ...props.style,
      }}
    >
      {props.children}
    </div>
  );
}

function SettingSubCard(props: {
  label: string;
  extra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "#fafafa",
        border: "1px solid var(--border-light)",
        borderRadius: 6,
        padding: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>{props.label}</span>
        {props.extra}
      </div>
      {props.children}
    </div>
  );
}

/** Generic small modal used to add or edit a single string (competitor / keyword). */
function NameEditModal(props: {
  open: boolean;
  title: string;
  initial: string;
  onCancel: () => void;
  onConfirm: (value: string) => Promise<void> | void;
}) {
  const [value, setValue] = useState(props.initial);
  useEffect(() => {
    if (props.open) setValue(props.initial);
  }, [props.open, props.initial]);
  return (
    <Modal
      open={props.open}
      title={props.title}
      okText="确定"
      cancelText="取消"
      onCancel={props.onCancel}
      onOk={async () => {
        const v = value.trim();
        if (!v) return;
        await props.onConfirm(v);
      }}
      destroyOnHidden
    >
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onPressEnter={async () => {
          const v = value.trim();
          if (!v) return;
          await props.onConfirm(v);
        }}
        autoFocus
      />
    </Modal>
  );
}

export interface BatchQuestionModalProps {
  open: boolean;
  /** When undefined the modal is in "create" mode; otherwise it's "edit". */
  projectId?: number;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * 弹出卡片 - 左侧分类,右侧问题勾选。
 *
 * 左列:项目级 category_taxonomy。每条目 = 分类名 + 当前引用此分类的问题数 +
 *       删除按钮。点击条目 = 选中该分类(右侧 checkbox 反映其当前成员)。
 *       底部 "+ 新增分类" inline 输入框,回车确认。
 * 右列:所有问题的 checkbox 列表。勾选状态 = ``assignments[text] ===
 *       activeCategory``。点击 checkbox 切换:已勾选则置 NULL,未勾选则置
 *       当前 activeCategory。
 *
 * 关闭时把 taxonomy 与 assignments 写回父组件;父组件在保存项目时一起提交。
 */
function CategoryAssignModal(props: {
  open: boolean;
  /** Snapshot of the project prompts as currently loaded — used as the
   *  baseline for what questions exist when the popup opens. The popup
   *  re-derives this from the parent's textarea on each open. */
  initialTaxonomy: string[];
  initialAssignments: Record<string, string | null>;
  /** Source of truth for the question list. Re-derived from the parent
   *  every time the popup opens, so editing the textarea then re-opening
   *  the popup reflects the new lines. */
  questionList: string[];
  onCancel: () => void;
  onConfirm: (
    nextTaxonomy: string[],
    nextAssignments: Record<string, string | null>,
    renames: Record<string, string>,
    removedCategories: string[],
  ) => void;
}) {
  // Local copies — the parent passes snapshots so the popup can be
  // cancelled without affecting outer state. ``renames`` and
  // ``removedCategories`` accumulate on top of the parent's baseline and
  // are surfaced through onConfirm.
  const [taxonomy, setTaxonomy] = useState<string[]>(props.initialTaxonomy);
  const [assignments, setAssignments] = useState<Record<string, string | null>>(
    props.initialAssignments,
  );
  const [activeCategory, setActiveCategory] = useState<string | null>(
    props.initialTaxonomy[0] ?? null,
  );
  const [newCategoryDraft, setNewCategoryDraft] = useState("");
  // Track renames and removals against the original taxonomy so the
  // parent can persist them on the project update (the cascading logic
  // on the server needs to know what changed).
  const baselineRef = useRef<string[]>(props.initialTaxonomy);
  const renamesRef = useRef<Record<string, string>>({});

  useEffect(() => {
    if (!props.open) return;
    setTaxonomy(props.initialTaxonomy);
    setAssignments(props.initialAssignments);
    setActiveCategory(props.initialTaxonomy[0] ?? null);
    setNewCategoryDraft("");
    baselineRef.current = props.initialTaxonomy;
    renamesRef.current = {};
  }, [props.open, props.initialTaxonomy, props.initialAssignments]);

  // Counts how many questions currently reference ``name`` (used to show
  // the "N 个问题" hint next to each category). Reads ``assignments`` so
  // unsaved edits in the popup show up immediately.
  const countByCategory = (name: string): number => {
    return Object.values(assignments).filter((v) => v === name).length;
  };

  const addCategory = (raw: string) => {
    const name = raw.trim();
    if (!name) return;
    if (taxonomy.includes(name)) {
      message.warning("已存在相同的分类名");
      return;
    }
    setTaxonomy((prev) => [...prev, name]);
    setActiveCategory(name);
  };

  const removeCategory = (name: string) => {
    const affected = countByCategory(name);
    Modal.confirm({
      title: `确认删除分类「${name}」?`,
      content:
        affected > 0
          ? `本弹窗内有 ${affected} 个问题使用了此分类,删除后这些问题会变为「未分类」。`
          : "此分类当前未被任何问题引用。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => {
        setTaxonomy((prev) => prev.filter((n) => n !== name));
        // Drop assignments that pointed at this category.
        setAssignments((prev) => {
          const next: Record<string, string | null> = {};
          for (const [k, v] of Object.entries(prev)) {
            next[k] = v === name ? null : v;
          }
          return next;
        });
        // If the active category was the one we just removed, fall back
        // to the first remaining taxonomy entry (or null).
        setActiveCategory((cur) => {
          if (cur !== name) return cur;
          return taxonomy.find((n) => n !== name) ?? null;
        });
        // Drop any rename that targeted the deleted name.
        if (renamesRef.current[name]) delete renamesRef.current[name];
      },
    });
  };

  // Toggle a question's membership in the currently-active category.
  // If the question was in a *different* category, switch it to the
  // active one — that's the natural "I'm now sorting under 体验类" gesture.
  const toggleQuestion = (text: string) => {
    if (!activeCategory) return;
    setAssignments((prev) => {
      const cur = prev[text] ?? null;
      const next = { ...prev };
      next[text] = cur === activeCategory ? null : activeCategory;
      return next;
    });
  };

  const handleConfirm = () => {
    // Compute renames against the original taxonomy snapshot. Only emit a
    // rename if the label moved (not added + removed in different orders).
    const oldTaxonomy = baselineRef.current;
    const renames: Record<string, string> = { ...renamesRef.current };
    const removed = oldTaxonomy.filter((n) => !taxonomy.includes(n));
    const added = taxonomy.filter((n) => !oldTaxonomy.includes(n));
    // Pair up removed/added as renames when their counts match — this
    // covers the "rename X to Y" case where the user's eye reads it as a
    // rename even though the UI does it as delete + add.
    if (added.length === removed.length && added.length > 0) {
      for (let i = 0; i < removed.length; i++) {
        renames[removed[i]] = added[i];
      }
    }
    props.onConfirm(taxonomy, assignments, renames, removed);
  };

  return (
    <Modal
      open={props.open}
      onCancel={props.onCancel}
      footer={null}
      width={720}
      centered
      destroyOnHidden
      title="为问题分配分类"
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "220px 1fr",
          gap: 14,
          minHeight: 420,
          maxHeight: "70vh",
        }}
      >
        {/* ===== Left column: taxonomy ===== */}
        <div
          style={{
            background: "#f3f4f6",
            border: "1px solid var(--border-light)",
            borderRadius: 6,
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            overflowY: "auto",
          }}
        >
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: "var(--text-secondary)",
              marginBottom: 2,
            }}
          >
            问题分类
          </div>
          {taxonomy.length === 0 ? (
            <span style={{ color: "var(--text-quaternary)", fontSize: 13 }}>
              尚未配置分类
            </span>
          ) : (
            taxonomy.map((name) => {
              const isActive = activeCategory === name;
              const count = countByCategory(name);
              return (
                <div
                  key={name}
                  onClick={() => setActiveCategory(name)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    background: isActive ? "#eff6ff" : "#fff",
                    border: `1px solid ${isActive ? "var(--brand-blue)" : "#e5e7eb"}`,
                    borderRadius: 6,
                    padding: "6px 10px",
                    fontSize: 13,
                    color: "var(--text-primary)",
                    cursor: "pointer",
                  }}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      flex: 1,
                      minWidth: 0,
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: isActive ? "var(--brand-blue)" : "#d1d5db",
                        flexShrink: 0,
                      }}
                    />
                    <span
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={name}
                    >
                      {name}
                    </span>
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      color: "var(--text-tertiary)",
                      flexShrink: 0,
                    }}
                  >
                    {count}
                  </span>
                  <Button
                    size="small"
                    type="text"
                    style={{
                      padding: "0 4px",
                      fontSize: 12,
                      height: 20,
                      color: "#dc2626",
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      removeCategory(name);
                    }}
                  >
                    ×
                  </Button>
                </div>
              );
            })
          )}

          {/* "+ 新增分类" — inline, Enter to confirm. */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              background: "#fff",
              border: "1px dashed #d1d5db",
              borderRadius: 6,
              padding: "6px 10px",
            }}
          >
            <PlusOutlined style={{ color: "var(--brand-blue)", fontSize: 12 }} />
            <Input
              placeholder="新增分类(回车确认)"
              size="small"
              bordered={false}
              value={newCategoryDraft}
              onChange={(e) => setNewCategoryDraft(e.target.value)}
              onPressEnter={() => {
                if (newCategoryDraft.trim()) {
                  addCategory(newCategoryDraft);
                  setNewCategoryDraft("");
                }
              }}
              style={{ flex: 1, padding: 0 }}
            />
          </div>
        </div>

        {/* ===== Right column: questions with checkboxes ===== */}
        <div
          style={{
            background: "#fafafa",
            border: "1px solid var(--border-light)",
            borderRadius: 6,
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 4,
            overflowY: "auto",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: 13,
              color: "var(--text-secondary)",
              marginBottom: 4,
              fontWeight: 500,
            }}
          >
            <span>
              {activeCategory
                ? `勾选归入「${activeCategory}」的问题`
                : "请在左侧点选一个分类"}
            </span>
            <span style={{ fontSize: 12, color: "var(--text-tertiary)", fontWeight: 400 }}>
              共 {props.questionList.length} 个问题
            </span>
          </div>
          {props.questionList.length === 0 ? (
            <span style={{ color: "var(--text-quaternary)", fontSize: 13 }}>
              下方 textarea 暂未输入问题
            </span>
          ) : (
            props.questionList.map((text, i) => {
              const checked = activeCategory
                ? assignments[text] === activeCategory
                : false;
              return (
                <label
                  key={`${text}-${i}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 8px",
                    borderRadius: 4,
                    background: checked ? "#eff6ff" : "#fff",
                    border: `1px solid ${checked ? "var(--brand-blue)" : "#e5e7eb"}`,
                    cursor: activeCategory ? "pointer" : "default",
                    fontSize: 13,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!activeCategory}
                    onChange={() => toggleQuestion(text)}
                    style={{ accentColor: "var(--brand-blue)" }}
                  />
                  <span
                    style={{
                      flex: 1,
                      minWidth: 0,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={text}
                  >
                    {text}
                  </span>
                  {/* Show the question's category even if it's a different
                      one — gives the admin a hint about what they're
                      about to overwrite. */}
                  {assignments[text] && assignments[text] !== activeCategory && (
                    <span
                      style={{
                        fontSize: 11,
                        color: "var(--text-tertiary)",
                        background: "#f3f4f6",
                        padding: "1px 6px",
                        borderRadius: 3,
                        flexShrink: 0,
                      }}
                    >
                      {assignments[text]}
                    </span>
                  )}
                </label>
              );
            })
          )}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          gap: 8,
          paddingTop: 14,
          marginTop: 14,
          borderTop: "1px solid var(--border-light)",
        }}
      >
        <Button onClick={props.onCancel}>取消</Button>
        <Button
          type="primary"
          onClick={handleConfirm}
          style={{
            background: "var(--brand-blue)",
            borderColor: "var(--brand-blue)",
          }}
        >
          确定
        </Button>
      </div>
    </Modal>
  );
}

/**
 * 把 wizard 提交的 payload 折回 modal 的 form state。PENDING 状态下
 * modal 开放对 questions / brand / competitors / models / monitor /
 * geo / sentiment / semantic 的逐项编辑,所以这里把这些字段全部从
 * payload 拉出来挂到 form state。``payload`` 整体仍存在
 * ``originalWizardPayload`` 里,save 通道(``putWizardDraft`` /
 * ``submitWizardProject``) 走 ``buildWizardPayloadFromForm`` 时
 * 通过 opts 注入编辑后的字段。
 */
function hydrateFromWizardPayload(payload: WizardPayload) {
  const questionLines = payload.questions.map((q) => q.text);
  const questionCategories: Record<string, string | null> = {};
  for (const q of payload.questions) {
    if (q.category) questionCategories[q.text] = q.category;
  }
  const modelsConfig = hydrateModelsConfig(payload);
  // 顶部「截图」下拉框是全局开关 —— 从已勾选卡的 screenshot 字段
  // 取 OR:任一张开了就算「全部截图」(便于继续编辑时延续状态),
  // 否则按「禁用截图」展示。
  const isScreenshotOn = modelsConfig.some((c) => c.screenshot);
  return {
    questionsText: questionLines.join("\n"),
    questionCategories,
    categoryTaxonomy: payload.categories ?? [],
    brand: payload.brand.name,
    brandAliases: payload.brand.aliases ?? [],
    competitors: payload.competitors ?? [],
    modelsConfig,
    isScreenshotOn,
    monitor: cloneMonitor(payload.monitor),
    geo: { mode: payload.geo.mode, region_code: payload.geo.region_code },
    sentiment: payload.sentiment,
    semantic: cloneSemantic(payload.semantic),
  };
}

/** 把 payload 折成「每张模型卡一条配置」。
 *
 *  ``models_config`` 非空(modal 存过草稿)直接用;否则说明 payload
 *  来自向导,只有 ``models``(全是网页 code) + ``monitor.devices``,
 *  这里把它展开成显式 code:勾了移动端就为有移动版的模型补一张移动卡,
 *  ``monitor.modes`` 作为所有卡片的初始模式。 */
/** 把 ``ProjectDetailOut`` + 已拉到的竞品列表折回 ``WizardPayload``。
 *
 *  active/disabled 行没有 ``wizard_payload_json``,modal 要把 child tables
 *  + project-row 字段反推成一个等价 payload,再走与 PENDING 完全相同的
 *  ``hydrateFromWizardPayload`` / ``buildWizardPayloadFromForm`` 通道。
 *  这样 form state 与 save 逻辑只有一份,不再因为 status 分叉。
 *
 *  Notes:
 *  - 监控名称 / description / schedule_enabled 不在 WizardPayload 里,
 *    仍走 ``updateProject`` / ``putScheduleStatus`` 处理;
 *  - 核心词 ``d.keywords`` 也不在 payload 里,active modal 走
 *    ``putKeywords``,PENDING modal 暂不支持编辑核心词;
 *  - 竞品 ``d.competitors`` 走单独的 CRUD(见 ``confirmBrandEdit``),
 *    不进 wizard payload。 */
function synthesizeWizardPayloadFromDetail(
  d: ProjectDetailOut,
  competitors: CompetitorOut[],
): WizardPayload {
  // 后端在 ``_expand_wizard_platforms`` 里按 (surface, mode) 二维展开,
  // ``platform_code`` 可能不同(doubao / doubao_mobile / doubao_reasoning
  // / doubao_mobile_reasoning),但 ``platform`` 仍是 UI 用的概念名
  // (doubao) —— 这里按概念名分组,把所有行打包到同一张卡上,反推出
  // ``modes``。早期版本按 ``p.platform`` 取 Map first-match,reasoning
  // 行会被 search 行吞掉。
  const rowsByCard = new Map<string, typeof d.platforms>();
  for (const p of d.platforms) {
    const card = p.platform;
    if (!rowsByCard.has(card)) rowsByCard.set(card, []);
    rowsByCard.get(card)!.push(p);
  }
  // 全局截图开关:任一行开启了截图就算「全部截图」,便于继续编辑时
  // 延续状态;否则按「禁用截图」展示。与 hydrateFromWizardPayload
  // 一端的 ``isScreenshotOn = modelsConfig.some(...)`` 行为对齐。
  const anyScreenshot = d.platforms.some((p) => p.screenshot > 0);
  const modelsConfig: WizardModelConfig[] = WIZARD_MODEL_CARD_CODES.map(
    (code) => {
      const rows = rowsByCard.get(code);
      if (!rows || rows.length === 0) {
        return { code, modes: [], screenshot: anyScreenshot };
      }
      // 同一张卡的多个 row 里,任一 ``thinking_mode=true`` 就勾「思考」;
      // 若同时有 fast + think 行,就都勾上,保持原始勾选状态。
      const modes: WizardMode[] = [];
      if (rows.some((r) => r.thinking_mode)) modes.push("think");
      if (rows.some((r) => !r.thinking_mode)) modes.push("fast");
      return { code, modes, screenshot: anyScreenshot };
    },
  );
  // baiduai 不支持思考模式,剥掉任何残留的 ``think`` 行(老数据兼容)。
  const normalizedModelsConfig = normalizeAllNoThink(modelsConfig);
  return {
    questions: d.prompts.map((p) => ({
      text: p.prompt,
      // WizardQuestion.category 是必填字符串;空分类落到 "" 而非 null,
      // 与 wizard submit() 一致。
      category: p.category || "",
      tag: null,
    })),
    brand: {
      name: d.brand || "",
      product: null,
      aliases: d.aliases || [],
    },
    // ``note`` ↔ ``product`` 是后端 CompetitorOut 与前端 WizardCompetitor
    // 的字段映射,旧 active 路径用 ``c.name`` 是历史 bug,统一纠正。
    competitors: competitors.map((c) => ({
      name: c.name,
      product: c.note || null,
      aliases: c.aliases || [],
    })),
    models: normalizedModelsConfig.map((c) => c.code),
    models_config: normalizedModelsConfig,
    monitor: {
      // ``devices`` / ``modes`` 从卡片配置反推,与 wizard payload 自洽。
      devices: deriveDevices(normalizedModelsConfig),
      modes: deriveModes(normalizedModelsConfig),
      schedules: deriveSchedules(d.monitor_schedule),
    },
    categories: d.category_taxonomy ?? [],
    geo: {
      mode: d.region_strategy === "fixed" ? "fixed" : "national_random",
      region_code: d.region_codes?.[0] ?? null,
    },
    sentiment: d.sentiment_enabled ? "on" : "off",
    semantic: {
      selling_points: d.semantic_json?.selling_points ?? [],
      website: d.semantic_json?.website ?? null,
      phone: d.semantic_json?.phone ?? null,
      address: d.semantic_json?.address ?? null,
      email: d.semantic_json?.email ?? null,
      wechat_service: d.semantic_json?.wechat_service ?? null,
      wechat_official: d.semantic_json?.wechat_official ?? null,
      xiaohongshu: d.semantic_json?.xiaohongshu ?? null,
      douyin: d.semantic_json?.douyin ?? null,
      weibo: d.semantic_json?.weibo ?? null,
      custom: d.semantic_json?.custom ?? null,
    },
  };
}

function hydrateModelsConfig(payload: WizardPayload): WizardModelConfig[] {
  if (payload.models_config && payload.models_config.length > 0) {
    return normalizeAllNoThink(
      payload.models_config.map((c) => ({
        code: c.code,
        modes: [...c.modes],
        screenshot: c.screenshot,
      })),
    );
  }
  const modes: WizardMode[] =
    payload.monitor.modes.length > 0 ? [...payload.monitor.modes] : ["fast"];
  const devices = payload.monitor.devices;
  const wantWeb = devices.length === 0 || devices.includes("pc");
  const wantMobile = devices.includes("mobile");
  const out: WizardModelConfig[] = [];
  const seen = new Set<string>();
  const push = (code: string) => {
    if (seen.has(code)) return;
    seen.add(code);
    out.push({ code, modes: [...modes], screenshot: false });
  };
  for (const code of payload.models) {
    const mobileEntry = WIZARD_MODELS.find((m) => m.mobileCode === code);
    if (mobileEntry) {
      // 已经是移动 code(modal 之前提交过),原样保留。
      push(code);
      continue;
    }
    const entry = WIZARD_MODELS.find((m) => m.value === code);
    if (!entry) continue;
    if (wantWeb) push(entry.value);
    if (wantMobile && entry.hasMobile && entry.mobileCode) push(entry.mobileCode);
  }
  return normalizeAllNoThink(out);
}

function cloneMonitor(m: WizardMonitor): WizardMonitor {
  const schedules = m.schedules || {};
  const cloned: WizardMonitor["schedules"] = {};
  for (const k of ["fast", "think"] as const) {
    const entry = schedules[k];
    cloned[k] = entry ? { freq: entry.freq, days: [...entry.days] } : null;
  }
  return {
    devices: [...m.devices],
    modes: [...m.modes],
    schedules: cloned,
  };
}

/** 从 project row 上的 ``monitor_schedule`` JSON 反推 ``WizardMonitor.schedules``。
 *
 *  与 v4 之前的单组 ``monitor_freq`` / ``monitor_days`` 不兼容 —— 老
 *  字段已 drop;返回的 shape 永远是 ``{fast, think}``。
 */
function deriveSchedules(
  monitorSchedule: Partial<Record<WizardMode, WizardMonitorEntry>> | null | undefined,
): WizardMonitor["schedules"] {
  const out: WizardMonitor["schedules"] = { fast: null, think: null };
  if (!monitorSchedule) return out;
  for (const k of ["fast", "think"] as const) {
    const entry = monitorSchedule[k];
    if (!entry) continue;
    const days = (entry.days ?? []).filter((x): x is WizardDay =>
      ["1", "2", "3", "4", "5", "6", "7"].includes(x),
    );
    if (!days.length) continue;
    out[k] = {
      freq: (entry.freq as WizardFreq) ?? "w1",
      days,
    };
  }
  return out;
}

// ``baiduai``(文心一言)在远端 API 不支持思考模式(submit-task 时返回
// code=500 "模型baiduai不支持深度思考"),UI 端直接拒绝 ``think``:
// 卡内不再显示 checkbox、批量「思考模式」按钮也跳过、load/save 通道
// 都把 baiduai 卡的 ``think`` 剥掉。勾上即视为快速模式。
const NO_THINK_PLATFORM_CODES: ReadonlySet<string> = new Set([
  "baiduai",
  "baidu_mobile",
]);

function normalizeNoThink(cfg: WizardModelConfig): WizardModelConfig {
  if (!NO_THINK_PLATFORM_CODES.has(cfg.code)) return cfg;
  if (!cfg.modes.includes("think")) return cfg;
  const without = cfg.modes.filter((m) => m !== "think");
  // 原状态只有 ``think``(说明用户原意是启用这张卡),退回 ``fast``
  // 避免变成「已勾选但 modes 为空」的怪状态。
  return { ...cfg, modes: without.length > 0 ? without : ["fast"] };
}

function normalizeAllNoThink(cfg: WizardModelConfig[]): WizardModelConfig[] {
  return cfg.map(normalizeNoThink);
}

// 与 WizardModelCard 内的 pushPair 顺序保持一致:豆包 / 元宝 / 千问 /
// DeepSeek / 文心 / Kimi / 阿福,每个 model 视 hasMobile 决定是否再
// 加一张 mobile 卡;共 12 张卡。把这里提到模块作用域,active 加载
// 时反推 wizardModelsConfig 也复用同一份顺序。
const WIZARD_MODEL_CARD_CODES: string[] = (() => {
  const out: string[] = [];
  for (const idx of [0, 1, 2, 4, 5, 3, 6]) {
    const m = WIZARD_MODELS[idx];
    if (!m) continue;
    out.push(m.value);
    if (m.hasMobile && m.mobileCode) out.push(m.mobileCode);
  }
  return out;
})();

function cloneSemantic(s: WizardSemantic): WizardSemantic {
  return {
    selling_points: [...s.selling_points],
    website: s.website,
    phone: s.phone,
    address: s.address,
    email: s.email,
    wechat_service: s.wechat_service,
    wechat_official: s.wechat_official,
    xiaohongshu: s.xiaohongshu,
    douyin: s.douyin,
    weibo: s.weibo,
    custom: s.custom,
  };
}

/** 从卡片配置反推 ``monitor.devices`` —— 移动 code 存在即算勾了移动端。 */
function deriveDevices(cfg: WizardModelConfig[]): WizardDevice[] {
  const out: WizardDevice[] = [];
  const isMobile = (code: string) =>
    WIZARD_MODELS.some((m) => m.mobileCode === code);
  if (cfg.some((c) => !isMobile(c.code))) out.push("pc");
  if (cfg.some((c) => isMobile(c.code))) out.push("mobile");
  return out;
}

/** 从卡片配置反推 ``monitor.modes`` —— 任一张卡勾了就算全局有。 */
function deriveModes(cfg: WizardModelConfig[]): WizardMode[] {
  const out: WizardMode[] = [];
  if (cfg.some((c) => c.modes.includes("fast"))) out.push("fast");
  if (cfg.some((c) => c.modes.includes("think"))) out.push("think");
  return out;
}

/** 把 modal 的可编辑字段 + originalWizardPayload 拼回 WizardPayload。
 *  categories 始终带默认两个分类 + 用户自定义,与 wizard submit()
 *  一致;其它字段以 opts 注入优先,opts 缺失时透传原 payload。 */
function buildWizardPayloadFromForm(opts: {
  questionsText: string;
  questionCategories: Record<string, string | null>;
  categoryTaxonomy: string[];
  brand: string;
  brandAliases: string[];
  competitors: WizardCompetitor[];
  modelsConfig: WizardModelConfig[];
  monitor: WizardMonitor;
  geo: WizardGeo;
  sentiment: WizardSentiment;
  semantic: WizardSemantic;
  original: WizardPayload;
}): WizardPayload {
  const questions: WizardQuestion[] = opts.questionsText
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((text) => ({
      text,
      // WizardQuestion.category 是必填字符串;空分类落到 "" 而非 null,
      // 与 wizard submit() 拼装时把 questionCategories[text] ?? "" 对齐。
      category: opts.questionCategories[text] ?? "",
      tag: null,
    }));
  // ``baiduai`` 不支持思考模式 —— load 通道已剥过,但用户可能通过
  // 「思考模式」批量按钮绕过 UI 守卫;save 通道再 normalize 一次,
  // 防止 ``think`` 落到 ``geo_project_platforms``。
  const safeModelsConfig = normalizeAllNoThink(opts.modelsConfig);
  return {
    ...opts.original,
    questions,
    brand: {
      ...opts.original.brand,
      name: opts.brand.trim(),
      aliases: opts.brandAliases,
    },
    competitors: opts.competitors
      .map((c) => ({ ...c, name: c.name.trim() }))
      .filter((c) => c.name),
    categories: opts.categoryTaxonomy,
    // ``models`` 保留成扁平 code 列表(只读摘要与旧数据仍读它),
    // 平台展开由后端按 ``models_config`` 走。``monitor.devices/modes``
    // 从卡片配置反推,保持 payload 自洽。``baiduai`` 在远端 API
    // 不支持思考模式 —— load 通道已剥过,但用户可能通过「思考模式」
    // 批量按钮绕过 UI 守卫;save 通道再 normalize 一次,防止 ``think``
    // 落到 ``geo_project_platforms``。
    models: safeModelsConfig.map((c) => c.code),
    models_config: safeModelsConfig,
    monitor: {
      ...opts.monitor,
      devices: deriveDevices(safeModelsConfig),
      modes: deriveModes(safeModelsConfig),
    },
    geo: opts.geo,
    sentiment: opts.sentiment,
    // 语义监控只在保存时截断 selling_points 到 10 行,textarea 本身不限。
    semantic: {
      ...opts.semantic,
      selling_points: opts.semantic.selling_points.slice(0, 10),
    },
  };
}

// =====================================================================
// Wizard-only right-column 卡片(PENDING 行可编辑)
//
// 三张卡片(模型选择 / 监控配置 / 其他设置)各自承担 payload 的
// 一组字段(state-models / monitor / geo / sentiment / semantic),
// 不再走 PLATFORM_CATALOG 与 slot 编排 —— 那是 ACTIVE/DISABLED
// 编辑路径的语义,与 wizard 提交流程不一致。
//
// 之所以不直接复用 NewProjectWizard 的 step 组件:modal 还要共用
// 原本的「监控名称 / 监控品牌 / 竞品 / 核心词 / 监控问题」左侧
// 业务表单,把它切成一个 wizard 步骤会破坏主路径;而 wizard 那
// 几个 step 组件本身又绑死 ``state`` 全局形状,搬过来要拆一
// 大圈 props。直接在 modal 里写一份等价卡片更稳。
// =====================================================================

function WizardModelCard(props: {
  config: WizardModelConfig[];
  setConfig: (next: WizardModelConfig[]) => void;
  isReadOnly: boolean;
  /** 顶部「截图」下拉框对应的全局开关(对所有已勾选卡生效)。 */
  isScreenshotOn: boolean;
  setIsScreenshotOn: (on: boolean) => void;
}) {
  // 每张卡代表「模型 × 设备」一个组合,按 WIZARD_MODELS 顺序展开:
  // 有移动版的展开成两张卡(网页 + 移动),无移动版的只有一张。
  // 共 13 张:5 对(10 张)+ Kimi / 阿福 / ChatGPT 各 1 张。
  // 7×2 grid 排布,最后一格空。
  //
  // **维度独立语义**:每张卡片代表「模型 × 设备」一个可用组合,
  // 卡片永远显示(不能整张卡 on/off);卡内 [快速] [思考] 两个
  // checkbox 是独立维度,可以多选。一个模型勾上网页版 + 移动版
  // + 快速 + 思考 = 4 次 API 调用。
  const cards: { code: string; name: string; color: string; mobile: boolean }[] = [];
  const pushPair = (entry: (typeof WIZARD_MODELS)[number]) => {
    cards.push({ code: entry.value, name: entry.name, color: entry.color, mobile: false });
    if (entry.hasMobile && entry.mobileCode) {
      cards.push({
        code: entry.mobileCode,
        name: entry.name,
        color: entry.color,
        mobile: true,
      });
    }
  };
  WIZARD_MODELS.forEach(pushPair);

  // 把 ``props.config`` 补全成所有 12 张卡的配置 —— 缺失的卡以空
  // ``modes=[]`` 补上,这样卡片永远能在 config 里有对应项,UI 和
  // 状态保持 1:1。``mergedConfig`` 是当前渲染的真值来源。
  const mergedConfig = cards.map((c) => {
    const existing = props.config.find((cc) => cc.code === c.code);
    return (
      existing ?? { code: c.code, modes: [] as WizardMode[], screenshot: props.isScreenshotOn }
    );
  });
  const byCode = new Map(mergedConfig.map((c) => [c.code, c]));
  const enabledWebCount = cards.filter(
    (c) => !c.mobile && (byCode.get(c.code)?.modes.length ?? 0) > 0,
  ).length;
  const enabledMobileCount = cards.filter(
    (c) => c.mobile && (byCode.get(c.code)?.modes.length ?? 0) > 0,
  ).length;

  /** 切某张卡的模式(数组里加 / 减某个 mode,不互斥)。
   *  空 modes 表示这个组合未启用 —— 卡仍可见,后端展开不出行。 */
  const toggleMode = (code: string, mode: WizardMode) => {
    if (props.isReadOnly) return;
    props.setConfig(
      mergedConfig.map((c) => {
        if (c.code !== code) return c;
        const nextModes = c.modes.includes(mode)
          ? c.modes.filter((m) => m !== mode)
          : [...c.modes, mode];
        return { ...c, modes: nextModes };
      }),
    );
  };

  /** 单卡启用/禁用 —— baiduai 不显示 [快速][思考] checkbox,
   *  整张卡变成可点击的开关:启用时 modes=["fast"],禁用时 modes=[];
   *  视觉反馈走现有的 enabled 边框 + 背景样式。 */
  const toggleCardEnabled = (code: string) => {
    if (props.isReadOnly) return;
    props.setConfig(
      mergedConfig.map((c) => {
        if (c.code !== code) return c;
        return { ...c, modes: c.modes.length > 0 ? [] : ["fast"] };
      }),
    );
  };

  /** 顶部「截图」下拉框回调 —— 把所有卡的 screenshot 字段同步成
   *  下拉选择的值;新出现的空白卡(``modes=[]``)也跟这个值。 */
  const applyScreenshot = (on: boolean) => {
    if (props.isReadOnly) return;
    props.setConfig(mergedConfig.map((c) => ({ ...c, screenshot: on })));
    props.setIsScreenshotOn(on);
  };

  /** 「全选 / 网页版 / 移动版」批量按钮 —— toggle 该组卡的「启用」状态:
   *  - 全部已启用(modes 非空)时点 → 整组清空(modes=[]);
   *  - 否则(部分启用或全部未启用)点 → 整组启用,modes=["fast"]。
   *  按钮高亮判断只看「该组是否全部 modes 非空」,modes 里的具体
   *  组合不影响高亮。 */
  const toggleGroupEnable = (codes: string[]) => {
    if (props.isReadOnly) return;
    const codeSet = new Set(codes);
    const allEnabled = codes.every(
      (code) => (byCode.get(code)?.modes.length ?? 0) > 0,
    );
    props.setConfig(
      mergedConfig.map((c) => {
        if (!codeSet.has(c.code)) return c;
        return { ...c, modes: allEnabled ? [] : ["fast"] };
      }),
    );
  };

  /** 「快速模式 / 思考模式」批量按钮 —— 按组 toggle 语义:
   *  - 只影响**已启用**卡(modes 非空),未启用卡不动;
   *  - 如果所有已启用卡都包含 ``mode``(全选)→ 高亮,再点批量去掉;
   *  - 否则(部分勾 / 都没勾)→ 批量加上,已有不变。
   *  没有启用任何卡时按钮不响应(避免「开启 0 个卡的 fast」这种
   *  无意义状态)。 */
  const toggleModeIfAllHave = (mode: WizardMode) => {
    if (props.isReadOnly) return;
    const enabled = mergedConfig.filter((c) => c.modes.length > 0);
    if (enabled.length === 0) return;
    const allHave = enabled.every((c) => c.modes.includes(mode));
    props.setConfig(
      mergedConfig.map((c) => {
        if (c.modes.length === 0) return c;
        // baiduai 不支持思考模式,「思考模式」批量按钮不动它的 modes;
        // save 通道会再 normalize 一次兜底,这里只是让 UI 状态不再
        // 假装可以批量添加。
        if (mode === "think" && NO_THINK_PLATFORM_CODES.has(c.code)) return c;
        if (allHave) {
          return { ...c, modes: c.modes.filter((m) => m !== mode) };
        }
        if (c.modes.includes(mode)) return c;
        return { ...c, modes: [...c.modes, mode] };
      }),
    );
  };

  // 「快速模式 / 思考模式」按钮高亮判断:所有已启用卡都包含该 mode。
  const enabledCards = mergedConfig.filter((c) => c.modes.length > 0);
  const allFastHighlighted =
    enabledCards.length > 0 &&
    enabledCards.every((c) => c.modes.includes("fast"));
  const allThinkHighlighted =
    enabledCards.length > 0 &&
    enabledCards.every((c) => c.modes.includes("think"));

  const allCodes = cards.map((c) => c.code);
  const webCodes = cards.filter((c) => !c.mobile).map((c) => c.code);
  const mobileCodes = cards.filter((c) => c.mobile).map((c) => c.code);

  return (
    <Card>
      <SectionTitle
        title="模型选择"
        required
        extra={
          <Space size={4} wrap>
            <Button
              size="small"
              disabled={props.isReadOnly}
              onClick={() => toggleGroupEnable(allCodes)}
              style={
                allCodes.every((code) => (byCode.get(code)?.modes.length ?? 0) > 0)
                  ? { background: "var(--brand-blue)", borderColor: "var(--brand-blue)", color: "#fff" }
                  : undefined
              }
            >
              全选
            </Button>
            <Button
              size="small"
              disabled={props.isReadOnly}
              onClick={() => toggleGroupEnable(webCodes)}
              style={
                webCodes.every((code) => (byCode.get(code)?.modes.length ?? 0) > 0)
                  ? { background: "var(--brand-blue)", borderColor: "var(--brand-blue)", color: "#fff" }
                  : undefined
              }
            >
              网页版
            </Button>
            <Button
              size="small"
              disabled={props.isReadOnly}
              onClick={() => toggleGroupEnable(mobileCodes)}
              style={
                mobileCodes.every((code) => (byCode.get(code)?.modes.length ?? 0) > 0)
                  ? { background: "var(--brand-orange)", borderColor: "var(--brand-orange)", color: "#fff" }
                  : undefined
              }
            >
              移动版
            </Button>
            <Button
              size="small"
              disabled={props.isReadOnly}
              onClick={() => toggleModeIfAllHave("fast")}
              style={
                allFastHighlighted
                  ? { background: "var(--brand-blue)", borderColor: "var(--brand-blue)", color: "#fff" }
                  : undefined
              }
            >
              快速模式
            </Button>
            <Button
              size="small"
              disabled={props.isReadOnly}
              onClick={() => toggleModeIfAllHave("think")}
              style={
                allThinkHighlighted
                  ? { background: "var(--brand-blue)", borderColor: "var(--brand-blue)", color: "#fff" }
                  : undefined
              }
            >
              思考模式
            </Button>
            <Button
              size="small"
              disabled={props.isReadOnly}
              onClick={() => applyScreenshot(!props.isScreenshotOn)}
              style={
                props.isScreenshotOn
                  ? { background: "var(--brand-blue)", borderColor: "var(--brand-blue)", color: "#fff" }
                  : undefined
              }
            >
              {props.isScreenshotOn ? "全部截图" : "禁用截图"}
            </Button>
          </Space>
        }
      />
      <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginBottom: 8 }}>
        已启用{" "}
        <strong style={{ color: "var(--brand-blue)" }}>{enabledWebCount}</strong>{" "}
        个网页版
        {enabledMobileCount > 0 && (
          <>
            {" · "}
            <strong style={{ color: "var(--brand-orange)" }}>
              {enabledMobileCount}
            </strong>{" "}
            个移动版
          </>
        )}
        {" · 共 "}
        {cards.reduce(
          (sum, c) => sum + (byCode.get(c.code)?.modes.length ?? 0),
          0,
        )}{" "}
        次 API 调用
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: 8,
        }}
      >
        {cards.map((c) => {
          const cur = byCode.get(c.code);
          const enabled = (cur?.modes.length ?? 0) > 0;
          const accent = c.mobile ? "var(--brand-orange)" : "var(--brand-blue)";
          const isBaiduaiNoThink = NO_THINK_PLATFORM_CODES.has(c.code);
          // baiduai 不显示 [快速][思考] checkbox,整张卡变成可点开关;
          // 其它卡仍由 checkbox 控制启用,卡面点击无副作用。
          const cardClickable = isBaiduaiNoThink && !props.isReadOnly;
          return (
            <div
              key={c.code}
              role={cardClickable ? "button" : undefined}
              tabIndex={cardClickable ? 0 : undefined}
              aria-pressed={cardClickable ? enabled : undefined}
              onClick={
                cardClickable ? () => toggleCardEnabled(c.code) : undefined
              }
              onKeyDown={
                cardClickable
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleCardEnabled(c.code);
                      }
                    }
                  : undefined
              }
              style={{
                cursor: cardClickable ? "pointer" : "default",
                border: `1px solid ${enabled ? accent : "var(--border-default)"}`,
                borderRadius: 6,
                background: enabled ? (c.mobile ? "#fff7ed" : "#eff6ff") : "#fff",
                padding: "8px 6px",
                display: "flex",
                flexDirection: "column",
                alignItems: "stretch",
                gap: 6,
                transition: "all 0.15s",
              }}
            >
              {/* Row 1: 模型名 + 设备,合并成单行标签,左侧带圆点色块。 */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  fontSize: 12,
                  fontWeight: enabled ? 500 : 400,
                  color: enabled ? accent : "var(--text-primary)",
                  whiteSpace: "nowrap",
                  minWidth: 0,
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: c.color,
                    flexShrink: 0,
                  }}
                />
                <span>{c.name}</span>
                <span
                  style={{
                    fontSize: 10,
                    color: enabled ? accent : "var(--text-tertiary)",
                    border: `1px solid ${enabled ? accent : "var(--border-default)"}`,
                    borderRadius: 3,
                    padding: "0 4px",
                    lineHeight: 1.5,
                  }}
                >
                  {c.mobile ? "移动版" : "网页版"}
                </span>
              </div>
              {/* Row 2: 快速 / 思考 checkbox。baiduai 不支持思考,展示提示文案。 */}
              {NO_THINK_PLATFORM_CODES.has(c.code) ? (
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--text-tertiary)",
                    textAlign: "center",
                    lineHeight: 1.4,
                  }}
                >
                  不支持思考模式
                </div>
              ) : (
                <div
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    alignItems: "center",
                    gap: 6,
                    whiteSpace: "nowrap",
                  }}
                >
                  {WIZARD_MODEL_MODES.map((m) => {
                    const active = cur?.modes.includes(m.key) ?? false;
                    return (
                      <label
                        key={m.key}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 3,
                          fontSize: 11,
                          whiteSpace: "nowrap",
                          color: active ? accent : "var(--text-tertiary)",
                          cursor: props.isReadOnly ? "default" : "pointer",
                          userSelect: "none",
                        }}
                      >
                        <input
                          type="checkbox"
                          disabled={props.isReadOnly}
                          checked={active}
                          onChange={() => toggleMode(c.code, m.key)}
                          style={{
                            width: 12,
                            height: 12,
                            accentColor: accent,
                            cursor: props.isReadOnly ? "default" : "pointer",
                          }}
                        />
                        {m.label}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function WizardMonitorCard(props: {
  monitor: WizardMonitor;
  setMonitor: (next: WizardMonitor) => void;
  isReadOnly: boolean;
}) {
  const setModeEntry = (
    modeKey: WizardMode,
    entry: WizardMonitorEntry | null,
  ) => {
    if (props.isReadOnly) return;
    const schedules = { ...(props.monitor.schedules || {}) };
    schedules[modeKey] = entry;
    props.setMonitor({ ...props.monitor, schedules });
  };
  const schedules = props.monitor.schedules || {};
  return (
    <Card>
      <SectionTitle title="监控配置(按模式)" />
      <div
        style={{
          fontSize: 12,
          color: "var(--text-tertiary)",
          marginBottom: 10,
        }}
      >
        每个模式(快速 / 思考)可以独立配置监控频率;关闭调度的模式不会出现在 cron 里。
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        {(["fast", "think"] as const).map((modeKey) => {
          const entry = schedules[modeKey] ?? null;
          return (
            <ModeScheduleInline
              key={modeKey}
              modeKey={modeKey}
              modeLabel={modeKey === "fast" ? "快速" : "思考"}
              entry={entry}
              isReadOnly={props.isReadOnly}
              onChange={(next) => setModeEntry(modeKey, next)}
            />
          );
        })}
      </div>
    </Card>
  );
}

/** 单个模式(快速 / 思考)的 freq + days 编辑卡片,inline-style 版。
 *  ``entry=null`` 表示「该模式不调度」,展示一个「启用」按钮;
 *  ``entry`` 存在时是 freq 选择 + 周几勾选 + 「关闭调度」链接。 */
function ModeScheduleInline(props: {
  modeKey: WizardMode;
  modeLabel: string;
  entry: WizardMonitorEntry | null;
  isReadOnly: boolean;
  onChange: (next: WizardMonitorEntry | null) => void;
}) {
  const { entry } = props;
  if (!entry) {
    return (
      <div
        style={{
          padding: 12,
          border: "1px dashed var(--border-default)",
          borderRadius: 8,
          background: "#fafafa",
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
          {props.modeLabel}模式调度
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-tertiary)",
            marginBottom: 8,
          }}
        >
          未启用 —— 不会在 cron 中触发
        </div>
        <Button
          size="small"
          type="default"
          onClick={() => props.onChange({ freq: "w1", days: [] })}
          disabled={props.isReadOnly}
        >
          启用{props.modeLabel}模式调度
        </Button>
      </div>
    );
  }
  const setFreq = (key: WizardFreq) => {
    if (props.isReadOnly) return;
    props.onChange({ freq: key, days: [] });
  };
  const toggleDay = (key: WizardDay) => {
    if (props.isReadOnly) return;
    const arr = entry.days;
    let next: WizardDay[];
    if (arr.includes(key)) {
      next = arr.filter((d) => d !== key);
    } else {
      const f = WIZARD_MONITOR_FREQUENCIES.find((x) => x.key === entry.freq);
      const max = f ? Math.min(f.max, 7) : 7;
      if (arr.length >= max) return;
      next = [...arr, key].sort((a, b) => Number(a) - Number(b));
    }
    props.onChange({ freq: entry.freq, days: next });
  };
  const applyPreset = (key: string) => {
    if (props.isReadOnly) return;
    const ps = WIZARD_WEEKDAY_PRESETS.find((p) => p.key === key);
    if (!ps) return;
    const f = WIZARD_MONITOR_FREQUENCIES.find((x) => x.key === entry.freq);
    const max = f ? Math.min(f.max, 7) : 7;
    props.onChange({ freq: entry.freq, days: ps.days.slice(0, max) });
  };
  const clearDays = () => {
    if (props.isReadOnly) return;
    props.onChange({ freq: entry.freq, days: [] });
  };
  const freqObj = WIZARD_MONITOR_FREQUENCIES.find((f) => f.key === entry.freq);
  const fMax = freqObj ? Math.min(freqObj.max, 7) : 7;
  return (
    <div
      style={{
        padding: 12,
        border: "1px solid var(--border-default)",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 500 }}>
          {props.modeLabel}模式调度
        </span>
        <Button
          type="link"
          size="small"
          onClick={() => props.onChange(null)}
          disabled={props.isReadOnly}
          style={{ padding: 0 }}
        >
          关闭调度
        </Button>
      </div>
      {/* 频率 */}
      <div
        style={{
          fontSize: 12,
          color: "var(--text-tertiary)",
          marginBottom: 4,
        }}
      >
        监控频率
      </div>
      <div
        style={{
          display: "flex",
          flexWrap: "nowrap",
          gap: 6,
          marginBottom: 8,
          width: "100%",
        }}
      >
        {WIZARD_MONITOR_FREQUENCIES.map((f) => {
          const active = entry.freq === f.key;
          return (
            <button
              key={f.key}
              type="button"
              disabled={props.isReadOnly}
              onClick={() => setFreq(f.key)}
              style={{
                flex: "1 1 0",
                minWidth: 0,
                width: 0,
                padding: "6px 4px",
                border: `1px solid ${active ? "var(--brand-blue)" : "var(--border-default)"}`,
                borderRadius: 6,
                background: active ? "#eff6ff" : "#fff",
                cursor: props.isReadOnly ? "default" : "pointer",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 1,
                transition: "all 0.15s",
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: active ? "var(--brand-blue)" : "var(--text-primary)",
                }}
              >
                {f.label}
              </span>
              <span
                style={{
                  fontSize: 10,
                  color: "var(--text-tertiary)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: "100%",
                }}
              >
                {f.hint}
              </span>
            </button>
          );
        })}
      </div>
      {/* 监控日期 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 11,
          color: "var(--text-tertiary)",
          marginBottom: 6,
          gap: 8,
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          <span>监控日期</span>
          <span
            style={{
              color:
                entry.days.length >= fMax ? "#dc2626" : "var(--text-secondary)",
              fontWeight: 500,
            }}
          >
            已选 {entry.days.length} 天
          </span>
          {entry.days.length >= fMax && (
            <span style={{ color: "#dc2626" }}>· 已达上限</span>
          )}
        </span>
        {freqObj && freqObj.min !== freqObj.max && (
          <Space size={4} wrap={false} style={{ flexShrink: 0 }}>
            {WIZARD_WEEKDAY_PRESETS.map((ps) => (
              <button
                key={ps.key}
                type="button"
                disabled={props.isReadOnly}
                onClick={() => applyPreset(ps.key)}
                style={{
                  height: 22,
                  padding: "0 6px",
                  fontSize: 11,
                  whiteSpace: "nowrap",
                  border: "1px solid var(--border-default)",
                  borderRadius: 11,
                  background: "#fff",
                  color: "var(--text-secondary)",
                  cursor: props.isReadOnly ? "default" : "pointer",
                }}
              >
                {ps.label}
              </button>
            ))}
            <button
              type="button"
              disabled={props.isReadOnly}
              onClick={clearDays}
              style={{
                height: 22,
                padding: "0 6px",
                fontSize: 11,
                whiteSpace: "nowrap",
                border: "1px solid var(--border-default)",
                borderRadius: 11,
                background: "#fff",
                color: "var(--text-secondary)",
                cursor: props.isReadOnly ? "default" : "pointer",
              }}
            >
              清空
            </button>
          </Space>
        )}
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        {WIZARD_WEEKDAYS.map((d) => {
          const active = entry.days.includes(d.key);
          return (
            <button
              key={d.key}
              type="button"
              disabled={props.isReadOnly}
              onClick={() => toggleDay(d.key)}
              style={{
                flex: 1,
                padding: "4px 0",
                border: `1px solid ${active ? "var(--brand-blue)" : "var(--border-default)"}`,
                borderRadius: 4,
                background: active ? "#eff6ff" : "#fff",
                color: active ? "var(--brand-blue)" : "var(--text-primary)",
                fontSize: 12,
                fontWeight: active ? 500 : 400,
                cursor: props.isReadOnly ? "default" : "pointer",
                transition: "all 0.15s",
              }}
            >
              {d.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function WizardOtherCard(props: {
  geo: WizardGeo;
  setGeo: (next: WizardGeo) => void;
  sentiment: WizardSentiment;
  setSentiment: (next: WizardSentiment) => void;
  semantic: WizardSemantic;
  setSemantic: (next: WizardSemantic) => void;
  isReadOnly: boolean;
}) {
  // 复用 wizard 的省份清单 (Molizhishu /eip-edge/ports/city-info)。
  // 加载失败时回退到自由输入。
  const [cities, setCities] = useState<Province[] | null>(null);
  const [citiesWarning, setCitiesWarning] = useState<string | null>(null);
  const [citiesLoading, setCitiesLoading] = useState(false);
  useEffect(() => {
    setCitiesLoading(true);
    listMolizhishuCities()
      .then((res) => {
        setCities(res.items);
        setCitiesWarning(res.warning);
      })
      .catch((e) => {
        setCities([]);
        setCitiesWarning((e as Error).message || "拉取失败");
      })
      .finally(() => setCitiesLoading(false));
  }, []);
  const setSemanticField = <K extends keyof WizardSemantic>(
    key: K,
    value: WizardSemantic[K],
  ) => props.setSemantic({ ...props.semantic, [key]: value });
  const filled = semanticFilledCount(props.semantic);
  return (
    <Card style={{ marginBottom: 0 }}>
      <SectionTitle title="其他设置" />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          marginBottom: 10,
        }}
      >
        <SettingSubCard label="提问位置">
          <Select
            value={props.geo.mode}
            onChange={(v) =>
              props.setGeo({
                mode: v,
                region_code:
                  v === "fixed" ? props.geo.region_code : null,
              })
            }
            disabled={props.isReadOnly}
            options={[
              { value: "national_random", label: "全国随机" },
              { value: "fixed", label: "指定区域" },
            ]}
            style={{ width: "100%" }}
          />
          {props.geo.mode === "fixed" && (
            <>
              {citiesLoading && (
                <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 6 }}>
                  正在加载省份清单…
                </div>
              )}
              {!citiesLoading && cities && cities.length > 0 && (
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择一个省份"
                  value={props.geo.region_code ?? undefined}
                  onChange={(v) =>
                    props.setGeo({
                      ...props.geo,
                      region_code: (v as string) ?? null,
                    })
                  }
                  disabled={props.isReadOnly}
                  style={{ width: "100%", marginTop: 6 }}
                  options={cities.map((c) => ({
                    value: c.code,
                    label: c.name,
                  }))}
                />
              )}
              {!citiesLoading && cities && cities.length === 0 && (
                <Input
                  placeholder="省份代码(6 位 adcode)"
                  value={props.geo.region_code ?? ""}
                  onChange={(e) =>
                    props.setGeo({
                      ...props.geo,
                      region_code: e.target.value.trim() || null,
                    })
                  }
                  disabled={props.isReadOnly}
                  style={{ marginTop: 6 }}
                  size="small"
                />
              )}
              {citiesWarning && cities && cities.length > 0 && (
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-tertiary)",
                    marginTop: 4,
                  }}
                >
                  {citiesWarning}(展示的是缓存数据)
                </div>
              )}
            </>
          )}
        </SettingSubCard>
        <SettingSubCard label="情感分析">
          <Select
            value={props.sentiment}
            onChange={(v) => props.setSentiment(v)}
            disabled={props.isReadOnly}
            options={WIZARD_SENTIMENT_OPTIONS.map((o) => ({
              value: o.key,
              label: o.label,
            }))}
            style={{ width: "100%" }}
          />
        </SettingSubCard>
      </div>
      {/* 语义监控 —— 11 个字段;与 NewProjectWizard 的 WIZARD_SEMANTIC_FIELDS 同步。 */}
      <div
        style={{
          background: "#f3f4f6",
          border: "1px solid var(--border-light)",
          borderRadius: 6,
          padding: 10,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 13,
            color: "var(--text-secondary)",
            marginBottom: 8,
          }}
        >
          <strong>语义监控</strong>
          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            已填 {filled} 项
          </span>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
          }}
        >
          {WIZARD_SEMANTIC_FIELDS.map((f) => (
            <SemanticFieldInline
              key={f.key}
              field={f}
              value={props.semantic[f.key]}
              onChange={(v) => setSemanticField(f.key, v)}
              isReadOnly={props.isReadOnly}
            />
          ))}
        </div>
      </div>
    </Card>
  );
}

function semanticFilledCount(s: WizardSemantic): number {
  let n = 0;
  if (s.selling_points.length > 0) n += 1;
  for (const k of [
    "website",
    "phone",
    "address",
    "email",
    "wechat_service",
    "wechat_official",
    "xiaohongshu",
    "douyin",
    "weibo",
    "custom",
  ] as const) {
    if ((s[k] ?? "").trim()) n += 1;
  }
  return n;
}

function SemanticFieldInline(props: {
  field: WizardSemanticField;
  value: WizardSemantic[keyof WizardSemantic];
  onChange: (v: WizardSemantic[keyof WizardSemantic]) => void;
  isReadOnly: boolean;
}) {
  // 语义监控只剩 selling_points 一项(多行 textarea,每行一条卖点,最多 10 行)。
  // selling_points 在 state 里是 string[],UI 层用 \n 连接展示,onChange 时
  // 仅按 \n 拆成数组 —— 不动行内容(不 trim / 不过滤空行),保证用户在末尾按
  // Enter 时 DOM 是 "foo\n" → split 出 ["foo", ""] 后,React 受控 prop 会写成
  // "foo\n",换行才不被吞掉。10 行上限在提交时统一截断。
  const labelStyle: React.CSSProperties = {
    fontSize: 12,
    color: "var(--text-tertiary)",
    marginBottom: 4,
  };
  const text =
    typeof props.value === "string"
      ? props.value
      : Array.isArray(props.value)
        ? (props.value as string[]).join("\n")
        : "";
  const handleChange = (next: string) => {
    props.onChange(next.split("\n"));
  };
  return (
    <div style={{ gridColumn: "span 2" }}>
      <div style={labelStyle}>{props.field.label}</div>
      <Input.TextArea
        rows={5}
        placeholder={props.field.placeholder}
        value={text}
        disabled={props.isReadOnly}
        onChange={(e) => handleChange(e.target.value)}
      />
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
        每行一条卖点,最多 10 行;超出部分将被截断。
      </div>
    </div>
  );
}

export default function BatchQuestionModal({
  open,
  projectId,
  onClose,
  onSaved,
}: BatchQuestionModalProps) {
  const isEdit = projectId !== undefined;
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const { modal: modalApi } = App.useApp();

  const [, setLoading] = useState(false);
  const [data, setData] = useState<ProjectDetailOut | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorOut[]>([]);
  // ===== wizard-only state (post 20260908_0002) =====
  // PENDING / REJECTED 行没有 prompts/keywords/platforms 子表,所以这些
  // 子表操作对应的本地 state 在该状态下不填值。原始 wizard payload
  // 留作 save 通道(putWizardDraft / submitWizardProject)原样回写
  // ``monitor`` / ``semantic`` 等 modal 没有编辑入口的字段。
  const [originalWizardPayload, setOriginalWizardPayload] = useState<WizardPayload | null>(
    null,
  );
  // PENDING / REJECTED 行没有 geo_project_competitors 行;wizard 提交时
  // 带的竞品存在 payload.competitors 里,这里挂个只读展示。
  const [wizardCompetitors, setWizardCompetitors] = useState<WizardCompetitor[]>([]);
  // 审批流(驳回 + 通过)的输入弹窗。
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [reviewNoteDraft, setReviewNoteDraft] = useState("");
  const [approveBusy, setApproveBusy] = useState(false);
  const [rejectBusy, setRejectBusy] = useState(false);
  const [withdrawBusy, setWithdrawBusy] = useState(false);
  const [resubmitBusy, setResubmitBusy] = useState(false);
  // 单次 API 调用费用(元),后端从 API_COST_PER_CALL 读,用于底部
  // 「预计费用」实时计算。未加载完时为 0,UI 显示 ¥0.00 不至于误算。
  const [costPerCall, setCostPerCall] = useState<number>(0);
  // Snapshot of PromptOut keyed by question text — used by saveAdapter
  // to preserve category/status when the user re-saves the same list via
  // this modal (which has no UI for those fields).
  const promptIndexRef = useRef<Map<string, { category: string | null; status: "monitoring" | "paused" | "archived" }>>(new Map());

  // form state
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [brandAliases, setBrandAliases] = useState<string[]>([]);
  const [questions, setQuestions] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  // Project-scoped prompt category taxonomy. ``renames`` accumulates every
  // rename the admin makes in this session (old name → new name) so the
  // server can rewrite ``geo_project_prompts.category`` in one go instead
  // of cascading deletions on labels the admin only renamed.
  const [categoryTaxonomy, setCategoryTaxonomy] = useState<string[]>([]);
  const [categoryRenames, setCategoryRenames] = useState<Record<string, string>>({});

  // ===== wizard 表单状态 (active / disabled / pending / rejected 共用) =====
  // 加载 active/disabled 行从 d.* 反推,PENDING / REJECTED 从 wizard_payload_json
  // hydrate。右侧 wizard 卡片改的就是它们;保存时由 ``saveAdapter`` 把它们
  // 翻译成 ``putWizardDraft``,active/disabled 额外再走 ``updateProject`` +
  // ``putKeywords``(这两类字段不在 wizard payload 里)。
  const [wizardModelsConfig, setWizardModelsConfig] = useState<
    WizardModelConfig[]
  >([]);
  // 顶部「截图」开关对应的全局状态:on 时所有已勾选卡的
  // ``screenshot`` 字段会被同步为 true,off 时为 false。
  const [wizardScreenshotEnabled, setWizardScreenshotEnabled] = useState(false);
  const [wizardMonitor, setWizardMonitor] = useState<WizardMonitor>({
    devices: [],
    modes: [],
    schedules: { fast: null, think: null },
  });
  const [wizardGeo, setWizardGeo] = useState<WizardGeo>({
    mode: "national_random",
    region_code: null,
  });
  const [wizardSentiment, setWizardSentiment] = useState<WizardSentiment>("on");
  const [wizardSemantic, setWizardSemantic] = useState<WizardSemantic>({
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

  const [projectStatus, setProjectStatus] = useState<"active" | "disabled">("active");
  // Opens the popup that combines the project-level category taxonomy and
  // per-question category assignment (left = categories, right = checkbox
  // list of questions). The popup owns its own taxonomy copy and writes
  // back on confirm via ``setCategoryTaxonomy`` / ``setQuestionCategories``.
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  // Per-question category overrides — keyed by the question text. Set when
  // the admin picks a category in the "为问题分配分类" card above the
  // textarea; on save this map wins over the snapshot loaded from the
  // server (so the admin's in-modal edits aren't lost). Keys are removed
  // when the admin picks "未分类" (allowClear).
  const [questionCategories, setQuestionCategories] = useState<Record<string, string | null>>({});

  // competitor / keyword modal state
  const [keywordModal, setKeywordModal] = useState<
    { mode: "add" } | { mode: "edit"; index: number; original: string } | null
  >(null);
  // Unified brand editor — handles monitor brand (project-level; persists
  // on the bottom 保存 button) AND competitor brands (per-row; persists
  // immediately via the competitor API so the chip list stays in sync).
  const [brandEditModal, setBrandEditModal] = useState<{
    scope: "brand" | "competitor-add" | "competitor-edit";
    title: string;
    initialName: string;
    initialAliases: string[];
    targetId?: number;
    /** wizard 模式下编辑竞品时,定位 wizardCompetitors 数组的索引
     *  (PENDING / REJECTED 行没有 geo_project_competitors 行,所以没有
     *  ``targetId``)。 */
    wizardIndex?: number;
  } | null>(null);

  useEffect(() => {
    if (!open) return;
    setData(null);
    setCompetitors([]);
    setName("");
    setBrand("");
    setBrandAliases([]);
    setQuestions("");
    setKeywords([]);
    setCategoryTaxonomy([]);
    setCategoryRenames({});
    setProjectStatus("active");
    setQuestionCategories({});
    setKeywordModal(null);
    setBrandEditModal(null);
    setAssignModalOpen(false);
    setOriginalWizardPayload(null);
    setWizardCompetitors([]);
    setWizardModelsConfig([]);
    setWizardScreenshotEnabled(false);
    setWizardMonitor({ devices: [], modes: [], schedules: { fast: null, think: null } });
    setWizardGeo({ mode: "national_random", region_code: null });
    setWizardSentiment("on");
    setWizardSemantic({
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
    setRejectModalOpen(false);
    setReviewNoteDraft("");
    setApproveBusy(false);
    setRejectBusy(false);
    setWithdrawBusy(false);
    setResubmitBusy(false);
    promptIndexRef.current = new Map();

    if (projectId === undefined) return;
    setLoading(true);
    (async () => {
      try {
        const d = await getProject(projectId);
        setData(d);
        setName(d.name);

        // 总是拉竞品列表 —— active modal 直接调 listCompetitors,
        // PENDING 也用它来填充 competitors 弹窗(虽然 PENDING 的
        // wizard payload 里也有竞品,这里是为了 chip 渲染需要)。
        const comp = await listCompetitors(projectId).catch(() => ({
          items: [] as CompetitorOut[],
        }));

        // WizardPayload 是 form state 的 canonical 来源 —— PENDING 行
        // 直接读 ``wizard_payload_json``,active/disabled 行没有就合成
        // 一份等价 payload。下游的 ``hydrateFromWizardPayload`` /
        // ``buildWizardPayloadFromForm`` 不再分叉。
        let payload: WizardPayload;
        if (d.wizard_payload_json) {
          try {
            payload = JSON.parse(d.wizard_payload_json) as WizardPayload;
          } catch {
            // wizard_payload_json 损坏 → 用 child tables 兜底合成
            payload = synthesizeWizardPayloadFromDetail(d, comp.items);
          }
        } else {
          payload = synthesizeWizardPayloadFromDetail(d, comp.items);
        }
        setOriginalWizardPayload(payload);

        const hydrated = hydrateFromWizardPayload(payload);
        // 「监控品牌」→ geo_projects.brand,与「核心词」独立。
        setBrand(hydrated.brand);
        setBrandAliases(hydrated.brandAliases);
        setQuestions(hydrated.questionsText);
        setQuestionCategories(hydrated.questionCategories);
        setCategoryTaxonomy(hydrated.categoryTaxonomy);
        setWizardCompetitors(hydrated.competitors);
        // 右侧 wizard 卡片(models / monitor / geo / sentiment / semantic)
        setWizardModelsConfig(hydrated.modelsConfig);
        setWizardScreenshotEnabled(hydrated.isScreenshotOn);
        setWizardMonitor(hydrated.monitor);
        setWizardGeo(hydrated.geo);
        setWizardSentiment(hydrated.sentiment);
        setWizardSemantic(hydrated.semantic);

        // 项目行字段:核心词、监控名称、status。仅 active/disabled 可编辑。
        setKeywords(d.keywords);
        setCategoryRenames({});
        setCompetitors(comp.items);
        setProjectStatus(d.status === "disabled" ? "disabled" : "active");

        // 重建 promptIndexRef —— 用 d.prompts(权威)而不是 payload
        // (payload 是 wizard 提交时的快照,可能缺 category/status 字段)。
        // active/disabled 走 d.prompts;PENDING 走 d.prompts 也对,因为
        // ``_materialise_wizard_payload`` 已把 wizard 的 questions 同步到
        // ProjectPrompt 行(category 同步成 "",status="monitoring")。
        const idx = new Map<
          string,
          { category: string | null; status: "monitoring" | "paused" | "archived" }
        >();
        for (const p of d.prompts) {
          idx.set(p.prompt, { category: p.category, status: p.status });
        }
        promptIndexRef.current = idx;
      } catch (err) {
        message.error((err as Error).message || "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [open, projectId]);

  // 单次 API 调用费用:后端从 API_COST_PER_CALL 读。只在组件 mount 时拉
  // 一次,不依赖 modal open —— 配置是服务级常量,不会因为打开 modal 而
  // 变化;后端热重启后才会失效,届时重开页面也会重新拉。
  useEffect(() => {
    getLlmPricing()
      .then((p) => setCostPerCall(Number(p.cost_per_call) || 0))
      .catch(() => setCostPerCall(0));
  }, []);

  // ---- unified brand editor confirm ----
  // 三种 scope:
  // - brand: 监控品牌,仅改本地 state,跟着底部「保存」走
  // - competitor-add / competitor-edit:
  //     - ACTIVE/DISABLED 行:立即调 createCompetitor / updateCompetitor,
  //       并 reload 列表让 chip 同步
  //     - PENDING / REJECTED 行:wizard 模式下没有 geo_project_competitors
  //       行,所有竞品随 putWizardDraft 一起走 WizardPayload;这里直接
  //       更新本地 wizardCompetitors state。
  const confirmBrandEdit = async (name: string, aliases: string[]) => {
    if (!brandEditModal) return;
    if (brandEditModal.scope === "brand") {
      setBrand(name);
      setBrandAliases(aliases);
      setBrandEditModal(null);
      return;
    }
    // wizard 模式 (PENDING / REJECTED) —— 直接更新 wizardCompetitors
    if (isWizardRow) {
      const trimmed = name.trim();
      if (brandEditModal.scope === "competitor-add") {
        if (!trimmed) {
          setBrandEditModal(null);
          return;
        }
        setWizardCompetitors((prev) => [
          ...prev,
          { name: trimmed, product: null, aliases },
        ]);
      } else {
        const idx = brandEditModal.wizardIndex;
        if (idx === undefined) {
          setBrandEditModal(null);
          return;
        }
        setWizardCompetitors((prev) =>
          prev.map((c, i) =>
            i === idx
              ? { ...c, name: trimmed || c.name, aliases }
              : c,
          ),
        );
      }
      setBrandEditModal(null);
      return;
    }
    if (projectId === undefined) {
      setBrandEditModal(null);
      return;
    }
    try {
      if (brandEditModal.scope === "competitor-add") {
        await createCompetitor(projectId, { name, aliases });
      } else {
        const target = competitors.find((c) => c.id === brandEditModal.targetId);
        await updateCompetitor(projectId, brandEditModal.targetId!, {
          name,
          note: target?.note,
          aliases,
        });
      }
      const comp = await listCompetitors(projectId);
      setCompetitors(comp.items);
      setBrandEditModal(null);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } };
      message.error(e?.response?.data?.detail || (err as Error).message || "操作失败");
    }
  };

  // wizard 模式:从 wizardCompetitors 删一条(无 API)
  const removeWizardCompetitor = (index: number) => {
    setWizardCompetitors((prev) => prev.filter((_, i) => i !== index));
  };

  const removeCompetitor = async (id: number) => {
    if (projectId === undefined) return;
    try {
      await deleteCompetitor(projectId, id);
      const comp = await listCompetitors(projectId);
      setCompetitors(comp.items);
    } catch (err) {
      message.error((err as Error).message || "删除失败");
    }
  };

  // ---- keyword CRUD (local; persisted via putKeywords on save) ----
  const confirmKeyword = (value: string) => {
    if (!keywordModal) return;
    if (keywordModal.mode === "add") {
      if (keywords.includes(value)) {
        message.warning("已存在相同的关键词");
        setKeywordModal(null);
        return;
      }
      setKeywords([...keywords, value]);
    } else {
      const next = [...keywords];
      if (next[keywordModal.index] !== value && next.includes(value)) {
        message.warning("已存在相同的关键词");
        setKeywordModal(null);
        return;
      }
      next[keywordModal.index] = value;
      setKeywords(next);
    }
    setKeywordModal(null);
  };

  const removeKeyword = (index: number) => {
    setKeywords(keywords.filter((_, i) => i !== index));
  };

  // ---- save action (unified for active / disabled / pending) ----
  // 之前分两条 (active→saveDraft,pending→saveDraftAsWizard),同一份 form
  // state 各自翻译一次,字段漂移会埋雷(modes fast+think 漏改)。现在
  // 一律走 ``putWizardDraft``:wizard 字段用 ``buildWizardPayloadFromForm``
  // 拼成 WizardPayload;active/disabled 额外多走
  // ``updateProject``(name/status)+ ``putKeywords``,因为这两类字段不
  // 在 wizard payload 内。``preserve_schedule_enabled=true`` 让后端不
  // 用 ``bool(days)`` 覆盖 ``schedule_enabled`` —— 调度开关是列表页
  // Switch 的职责,modal 不能默默改它。
  const saveAdapter = async () => {
    if (!data || !originalWizardPayload) return;
    const payload = buildWizardPayloadFromForm({
      questionsText: questions,
      questionCategories,
      categoryTaxonomy,
      brand,
      brandAliases,
      competitors: wizardCompetitors,
      modelsConfig: wizardModelsConfig,
      monitor: wizardMonitor,
      geo: wizardGeo,
      sentiment: wizardSentiment,
      semantic: wizardSemantic,
      original: originalWizardPayload,
    });
    const preserveScheduleEnabled =
      status === "active" || status === "disabled";
    try {
      await putWizardDraft(data.id, {
        payload,
        preserve_schedule_enabled: preserveScheduleEnabled,
        // 「监控名称」不在 wizard payload 里:PENDING 由后端
        // ``update_project`` 拒收业务字段,只能走 wizard draft 端点
        // 顶层 ``name`` 字段;active/disabled 已有 update_project 路径,
        // 这里多带是幂等冗余。
        name: name.trim(),
      });
      if (preserveScheduleEnabled) {
        // 项目行字段 + 核心词:仅 active/disabled 走。PENDING 受
        // ``update_project`` 生命周期规则约束,业务字段拒收;keywords
        // 走 ``put_keywords`` 也要 super_admin,PENDING modal 没开入口。
        const cleanedTaxonomy = Array.from(
          new Set(categoryTaxonomy.map((s) => s.trim()).filter(Boolean)),
        );
        const cleanedRenames: Record<string, string> = {};
        for (const [oldName, newName] of Object.entries(categoryRenames)) {
          const o = oldName.trim();
          const n = newName.trim();
          if (o && n && o !== n && cleanedTaxonomy.includes(n)) {
            cleanedRenames[o] = n;
          }
        }
        await updateProject(data.id, {
          name: name.trim(),
          status: projectStatus,
        });
        await putKeywords(data.id, keywords);
      }
      message.success("已保存！");
      onSaved();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || (err as Error).message || "保存失败");
    }
  };

  // ===== 派生状态 =====
  const status = data?.status ?? null;
  const isWizardRow = status === "pending" || status === "rejected";
  // REJECTED 仍只读(super_admin 仅能审批,customer_admin 通过
  // 「重新提交」以原 payload 二次提交)。
  const isReadOnly = status === "rejected";

  // ===== 审批动作(pending / rejected) =====
  const doApprove = async () => {
    if (!data) return;
    setApproveBusy(true);
    try {
      await approveProject(data.id);
      message.success("已审批通过");
      onSaved();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || (err as Error).message || "审批失败");
    } finally {
      setApproveBusy(false);
    }
  };

  const doReject = async () => {
    if (!data) return;
    if (!reviewNoteDraft.trim()) {
      message.warning("请填写驳回原因");
      return;
    }
    setRejectBusy(true);
    try {
      await rejectProject(data.id, reviewNoteDraft.trim());
      message.success("已驳回");
      setRejectModalOpen(false);
      setReviewNoteDraft("");
      onSaved();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || (err as Error).message || "驳回失败");
    } finally {
      setRejectBusy(false);
    }
  };

  const doWithdraw = async () => {
    if (!data) return;
    modalApi.confirm({
      title: "确认撤回申请?",
      content: `项目「${data.name}」撤回后将无法恢复,需要重新提交。`,
      okText: "撤回",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        setWithdrawBusy(true);
        try {
          await withdrawProject(data.id);
          message.success("已撤回");
          onSaved();
        } catch (err) {
          const detail = (err as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail;
          message.error(detail || (err as Error).message || "撤回失败");
        } finally {
          setWithdrawBusy(false);
        }
      },
    });
  };

  const doResubmit = async () => {
    if (!data || !originalWizardPayload) return;
    modalApi.confirm({
      title: "确认重新提交?",
      content: "将以当前编辑内容重新创建一份申请,原驳回记录保留。",
      okText: "重新提交",
      cancelText: "取消",
      onOk: async () => {
        setResubmitBusy(true);
        try {
          const payload = buildWizardPayloadFromForm({
            questionsText: questions,
            questionCategories,
            categoryTaxonomy,
            brand,
            brandAliases,
            competitors: wizardCompetitors,
            modelsConfig: wizardModelsConfig,
            monitor: wizardMonitor,
            geo: wizardGeo,
            sentiment: wizardSentiment,
            semantic: wizardSemantic,
            original: originalWizardPayload,
          });
          const next = await submitWizardProject({ payload });
          message.success("已重新提交,新申请已加入待审核队列");
          onSaved();
          // 让外部列表能拿到新行 id;这里仅关闭 modal,父级负责刷新。
          void next;
        } catch (err) {
          const detail = (err as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail;
          message.error(detail || (err as Error).message || "提交失败");
        } finally {
          setResubmitBusy(false);
        }
      },
    });
  };

  const questionList = questions.split("\n").map((s) => s.trim()).filter(Boolean);
  const questionCount = questionList.length;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={1440}
      centered
      closable={false}
      destroyOnHidden
      styles={{
        body: {
          padding: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
        },
        content: {
          padding: 0,
          overflow: "hidden",
          borderRadius: 10,
          height: 800,
          maxHeight: "90vh",
        },
      }}
      maskStyle={{ background: "rgba(15, 23, 42, 0.45)" }}
    >
      {/* ===== light header bar ===== */}
      <div
        style={{
          background: "#fff",
          padding: "14px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid var(--border-light)",
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>
          {isEdit ? "编辑监控项目" : "批量添加问题"}
        </div>
        <Button
          type="text"
          icon={<CloseOutlined style={{ color: "var(--text-tertiary)", fontSize: 16 }} />}
          onClick={onClose}
        />
      </div>

      {/* ===== body ===== */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          padding: "16px 24px",
          background: "#f5f6f8",
          overflow: "auto",
        }}
      >
        {data?.status === "rejected" && data.review_note && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message="驳回原因"
            description={data.review_note}
          />
        )}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 14,
            minHeight: "100%",
          }}
        >
          {/* ============= LEFT COLUMN ============= */}
          <div style={{ display: "flex", flexDirection: "column" }}>
            {/* ---- Card 1: 监控名称 + 监控品牌 ---- */}
            <Card>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <div>
                  <SectionTitle title="监控名称" required />
                  <Input
                    placeholder="请输入监控名称"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    disabled={isReadOnly}
                  />
                </div>
                <div>
                  <SectionTitle title="监控品牌" required />
                  <button
                    type="button"
                    disabled={isReadOnly}
                    onClick={() =>
                      setBrandEditModal({
                        scope: "brand",
                        title: brand.trim() ? "编辑监控品牌" : "添加监控品牌",
                        initialName: brand,
                        initialAliases: brandAliases,
                      })
                    }
                    style={{
                      width: "100%",
                      minHeight: 32,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "6px 10px",
                      border: "1px dashed var(--border-default, #d1d5db)",
                      borderRadius: 6,
                      background: brand.trim() ? "#fff" : "#fafafa",
                      cursor: "pointer",
                      fontFamily: "inherit",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 13,
                        color: brand.trim()
                          ? "var(--text-primary)"
                          : "var(--text-quaternary)",
                      }}
                    >
                      {brand.trim() || "点击添加监控品牌"}
                    </span>
                    <span
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: 12,
                      }}
                    >
                      {brandAliases.length > 0 && (
                        <span
                          style={{
                            color: "var(--text-tertiary)",
                            background: "#f3f4f6",
                            padding: "0 6px",
                            borderRadius: 3,
                          }}
                        >
                          {brandAliases.length} 个别名
                        </span>
                      )}
                      <span style={{ color: "var(--brand-blue)" }}>
                        {brand.trim() ? "编辑" : "添加"}
                      </span>
                    </span>
                  </button>
                </div>
              </div>
            </Card>

            {/* ---- Card 2: 竞品品牌 (gray container + cards inside) ---- */}
            <Card>
              <SectionTitle title="竞品品牌" />
              <div
                style={{
                  background: "#f3f4f6",
                  border: "1px solid var(--border-light)",
                  borderRadius: 6,
                  padding: "10px 12px",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                  minHeight: 56,
                }}
              >
                {isWizardRow ? (
                  <>
                    <CirclePlus
                      size={20}
                      strokeWidth={1.8}
                      color={isReadOnly ? "#9ca3af" : "var(--brand-blue)"}
                      style={{
                        cursor: isReadOnly ? "not-allowed" : "pointer",
                        flexShrink: 0,
                      }}
                      onClick={() => {
                        if (isReadOnly) return;
                        setBrandEditModal({
                          scope: "competitor-add",
                          title: "添加竞品品牌",
                          initialName: "",
                          initialAliases: [],
                        });
                      }}
                    />
                    {wizardCompetitors.length === 0 ? (
                      <span
                        style={{
                          color: "var(--text-quaternary)",
                          fontSize: 13,
                          userSelect: "none",
                        }}
                      >
                        暂未添加,点击左侧 + 添加
                      </span>
                    ) : (
                      wizardCompetitors.map((c, i) => (
                        <div
                          key={`${c.name}-${i}`}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                            background: "#fff",
                            border: "1px solid #e5e7eb",
                            borderRadius: 6,
                            padding: "4px 8px 4px 10px",
                            fontSize: 13,
                            color: "var(--text-primary)",
                            transition: "border-color 0.15s ease",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.borderColor = "var(--brand-blue)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.borderColor = "#e5e7eb";
                          }}
                        >
                          <span
                            onClick={() => {
                              if (isReadOnly) return;
                              setBrandEditModal({
                                scope: "competitor-edit",
                                title: "编辑竞品品牌",
                                initialName: c.name,
                                initialAliases: c.aliases ?? [],
                                wizardIndex: i,
                              });
                            }}
                            style={{
                              cursor: isReadOnly ? "default" : "pointer",
                              fontWeight: 500,
                            }}
                          >
                            {c.name || "(未填)"}
                          </span>
                          {c.aliases && c.aliases.length > 0 && (
                            <span
                              style={{
                                fontSize: 11,
                                color: "var(--text-tertiary)",
                                background: "#f3f4f6",
                                padding: "0 6px",
                                borderRadius: 3,
                              }}
                            >
                              {c.aliases.length} 个别名
                            </span>
                          )}
                          <X
                            size={12}
                            strokeWidth={2}
                            color="#9ca3af"
                            style={{
                              cursor: isReadOnly ? "default" : "pointer",
                              flexShrink: 0,
                            }}
                            onClick={() => {
                              if (isReadOnly) return;
                              removeWizardCompetitor(i);
                            }}
                          />
                        </div>
                      ))
                    )}
                  </>
                ) : (
                  <>
                <CirclePlus
                  size={20}
                  strokeWidth={1.8}
                  color={
                    projectId === undefined ? "#9ca3af" : "var(--brand-blue)"
                  }
                  style={{
                    cursor: projectId === undefined ? "not-allowed" : "pointer",
                    flexShrink: 0,
                  }}
                  onClick={() => {
                    if (projectId === undefined) {
                      message.info("请先保存项目后再添加竞品");
                      return;
                    }
                    setBrandEditModal({
                      scope: "competitor-add",
                      title: "添加竞品品牌",
                      initialName: "",
                      initialAliases: [],
                    });
                  }}
                />
                {competitors.length === 0 ? (
                  <span
                    style={{
                      color: "var(--text-quaternary)",
                      fontSize: 13,
                      userSelect: "none",
                    }}
                  >
                    暂未添加,点击左侧 + 添加
                  </span>
                ) : (
                  competitors.map((c) => (
                    <div
                      key={c.id}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 8,
                        background: "#fff",
                        border: "1px solid #e5e7eb",
                        borderRadius: 6,
                        padding: "4px 8px 4px 10px",
                        fontSize: 13,
                        color: "var(--text-primary)",
                        transition: "border-color 0.15s ease",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = "var(--brand-blue)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = "#e5e7eb";
                      }}
                    >
                      <span
                        onClick={() =>
                          setBrandEditModal({
                            scope: "competitor-edit",
                            title: "编辑竞品品牌",
                            initialName: c.name,
                            initialAliases: c.aliases ?? [],
                            targetId: c.id,
                          })
                        }
                        style={{ cursor: "pointer", fontWeight: 500 }}
                      >
                        {c.name}
                      </span>
                      {c.aliases && c.aliases.length > 0 && (
                        <span
                          style={{
                            fontSize: 11,
                            color: "var(--text-tertiary)",
                            background: "#f3f4f6",
                            padding: "0 6px",
                            borderRadius: 3,
                          }}
                        >
                          {c.aliases.length} 个别名
                        </span>
                      )}
                      <X
                        size={12}
                        strokeWidth={2}
                        color="#9ca3af"
                        style={{ cursor: "pointer", flexShrink: 0 }}
                        onClick={() => removeCompetitor(c.id)}
                      />
                    </div>
                  ))
                )}
                  </>
                )}
              </div>
            </Card>

            {/* ---- Card 3: 核心词 (card list) + 监控问题 ---- */}
            <Card style={{ flex: 1, marginBottom: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 3fr",
                  gap: 18,
                  flex: 1,
                  minHeight: 0,
                }}
              >
                {/* 核心词 list (cards inside gray container) */}
                <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
                  <SectionTitle
                    title="核心词"
                    extra={
                      <Button
                        size="small"
                        type="link"
                        icon={<PlusOutlined />}
                        onClick={() => setKeywordModal({ mode: "add" })}
                        disabled={isReadOnly}
                      >
                        新增
                      </Button>
                    }
                  />
                  <div
                    style={{
                      flex: 1,
                      minHeight: 0,
                      background: "#f3f4f6",
                      border: "1px solid var(--border-light)",
                      borderRadius: 6,
                      padding: "10px 12px",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "flex-start",
                      gap: 8,
                      overflow: "auto",
                    }}
                  >
                    {keywords.length === 0 ? (
                      <span
                        style={{
                          color: "var(--text-quaternary)",
                          fontSize: 13,
                          userSelect: "none",
                        }}
                      >
                        暂无核心词,点击右上角新增
                      </span>
                    ) : (
                      keywords.map((k, i) => (
                        <div
                          key={`${k}-${i}`}
                          onClick={() =>
                            setKeywordModal({ mode: "edit", index: i, original: k })
                          }
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            background: "#fff",
                            border: "1px solid #e5e7eb",
                            borderRadius: 4,
                            padding: "4px 8px 4px 10px",
                            fontSize: 13,
                            color: "var(--text-primary)",
                            cursor: "pointer",
                            boxShadow: "0 1px 2px rgba(15, 23, 42, 0.05)",
                            transition: "all 0.15s ease",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.boxShadow =
                              "0 2px 6px rgba(15, 23, 42, 0.1)";
                            e.currentTarget.style.borderColor = "var(--brand-blue)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.boxShadow =
                              "0 1px 2px rgba(15, 23, 42, 0.05)";
                            e.currentTarget.style.borderColor = "#e5e7eb";
                          }}
                        >
                          <span>{k}</span>
                          <X
                            size={12}
                            strokeWidth={2}
                            color="#9ca3af"
                            style={{ cursor: "pointer", flexShrink: 0 }}
                            onClick={(e) => {
                              e.stopPropagation();
                              removeKeyword(i);
                            }}
                          />
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* 监控问题 textarea */}
                <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
                  <SectionTitle
                    title="监控问题"
                    required
                    extra={
                      <Button
                        size="small"
                        type="link"
                        icon={<TagsOutlined />}
                        onClick={() => setAssignModalOpen(true)}
                        disabled={isReadOnly}
                      >
                        分配分类
                      </Button>
                    }
                  />
                  {/* 分类 chip 列表 —— 让用户在 modal 主界面就能看到
                      当前「监控问题分类」配置(点了「分配分类」改完也能
                      立刻看到生效结果),不再是只在弹窗里才能查看。 */}
                  {categoryTaxonomy.length === 0 ? (
                    <div
                      onClick={() => !isReadOnly && setAssignModalOpen(true)}
                      style={{
                        background: "#f3f4f6",
                        border: "1px solid var(--border-light)",
                        borderRadius: 6,
                        padding: "8px 12px",
                        fontSize: 12,
                        color: "var(--text-quaternary)",
                        cursor: isReadOnly ? "default" : "pointer",
                        marginBottom: 8,
                      }}
                    >
                      尚未配置分类,点此处添加
                    </div>
                  ) : (
                    <div
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 6,
                        marginBottom: 8,
                      }}
                    >
                      {categoryTaxonomy.map((name) => {
                        const count = Object.values(questionCategories).filter(
                          (v) => v === name,
                        ).length;
                        return (
                          <div
                            key={name}
                            onClick={() => !isReadOnly && setAssignModalOpen(true)}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                              background: "#eff6ff",
                              border: "1px solid #bfdbfe",
                              borderRadius: 4,
                              padding: "2px 8px",
                              fontSize: 12,
                              color: "var(--brand-blue)",
                              cursor: isReadOnly ? "default" : "pointer",
                            }}
                          >
                            <span>{name}</span>
                            <span
                              style={{
                                fontSize: 11,
                                color: "var(--text-tertiary)",
                                background: "#fff",
                                padding: "0 4px",
                                borderRadius: 3,
                              }}
                            >
                              {count}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <Input.TextArea
                    placeholder={
                      "每行输入一个监控问题，换行分隔\n例如：\n哪个智能客服系统最好用？\nAI智能和人工客服哪个效果更好？\n如何提升客服效率？"
                    }
                    value={questions}
                    onChange={(e) => setQuestions(e.target.value)}
                    disabled={isReadOnly}
                    style={{ flex: 1, minHeight: 0, fontSize: 13, lineHeight: 1.7 }}
                  />
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--text-tertiary)",
                      marginTop: 6,
                      textAlign: "right",
                    }}
                  >
                    已输入 {questionCount} 个问题（每行 1 个）
                  </div>
                </div>
              </div>
            </Card>
          </div>

          {/* ============= RIGHT COLUMN ============= */}
          <div>
            {/* ---- 统一 wizard 卡片 ----
                active / disabled / pending / rejected 都渲染同一套三张卡
                (模型选择 / 监控配置 / 其他设置)。active 加载时从
                d.platforms / d.monitor_schedule / d.region_strategy /
                d.sentiment_enabled / d.semantic_json 反推 wizard
                state;PENDING / REJECTED 从 wizard_payload_json hydrate。
                编辑入口(active/disabled / pending)走统一 saveAdapter,
                一律 ``putWizardDraft``,active/disabled 额外再走
                ``updateProject`` + ``putKeywords``(name/status/keywords
                不在 wizard payload 内);REJECTED 卡片只读。 */}
            {status !== null && (
              <>
                <WizardModelCard
                  config={wizardModelsConfig}
                  setConfig={setWizardModelsConfig}
                  isScreenshotOn={wizardScreenshotEnabled}
                  setIsScreenshotOn={setWizardScreenshotEnabled}
                  isReadOnly={status === "rejected"}
                />
                <WizardMonitorCard
                  monitor={wizardMonitor}
                  setMonitor={setWizardMonitor}
                  isReadOnly={status === "rejected"}
                />
                <WizardOtherCard
                  geo={wizardGeo}
                  setGeo={setWizardGeo}
                  sentiment={wizardSentiment}
                  setSentiment={setWizardSentiment}
                  semantic={wizardSemantic}
                  setSemantic={setWizardSemantic}
                  isReadOnly={status === "rejected"}
                />
              </>
            )}
          </div>
        </div>
      </div>

      {/* ===== bottom action bar ===== */}

      {/* ===== bottom action bar ===== */}
      <div
        style={{
          background: "#fff",
          borderTop: "1px solid var(--border-light)",
          padding: "12px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        {(() => {
          // 底部「预计费用」:costPerCall(元/次,来自 .env 的 API_COST_PER_CALL)
          // × 单次监控触发的 API 调用数 = 问题数 × 单问题调用的模型组合数。
          // 与后端 scheduler.run_project 的 cartesian(prompts, platforms) 一致
          // —— 每个问题对每个启用的 (mode) 都发一次 API。
          // 待审核 / 已驳回 行不展示费用 —— 此时项目还未上线跑,展示预算
          // 容易误导客户以为「按这个数收费」,但实际是按审批通过后正式启用
          // 的配置计费。
          if (status === "pending") {
            return (
              <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
                此项目正在审核中。提交人或管理员均可在此处修改并保存草稿。
              </span>
            );
          }
          if (status === "rejected") {
            return (
              <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
                此申请已被驳回,业务字段不可编辑。
              </span>
            );
          }
          const questionCount = questions.split("\n").filter((s) => s.trim()).length;
          const platformsPerQuestion = wizardModelsConfig.reduce(
            (sum, c) => sum + c.modes.length,
            0,
          );
          const totalCalls = questionCount * platformsPerQuestion;
          const totalCost = costPerCall * totalCalls;
          return (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                color: "var(--text-secondary)",
              }}
            >
              <span>预计费用:</span>
              <span
                style={{
                  fontSize: 16,
                  fontWeight: 600,
                  color: "var(--brand-blue)",
                }}
              >
                ¥{totalCost.toFixed(2)}
              </span>
              <span style={{ color: "var(--text-tertiary)" }}>/ 次</span>
              <Tooltip title="根据当前监控配置预估,实际费用以账单为准">
                <InfoCircleOutlined style={{ color: "var(--text-tertiary)" }} />
              </Tooltip>
            </div>
          );
        })()}
        <Space size={10}>
          {/* active / disabled —— 现有 「取消 / 保存」 */}
          {(status === "active" || status === "disabled" || status === null) && (
            <>
              <Button onClick={onClose}>取消</Button>
              <Button
                type="primary"
                onClick={() => void saveAdapter?.()}
                disabled={!data || !saveAdapter}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                }}
              >
                保存
              </Button>
            </>
          )}
          {/* pending + super_admin —— 「关闭 / 保存草稿 / 驳回 / 审批通过」
              (super_admin 现在也能编辑 PENDING 项目的所有字段,跟 customer_admin
              走同一 saveAdapter;驳回 + 审批仍然只 super_admin 可点) */}
          {status === "pending" && isSuper && (
            <>
              <Button onClick={onClose}>关闭</Button>
              <Button
                onClick={() => void saveAdapter?.()}
                disabled={!data || !saveAdapter}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                  color: "#fff",
                }}
              >
                保存草稿
              </Button>
              <Button
                danger
                onClick={() => setRejectModalOpen(true)}
                disabled={!data}
              >
                驳回
              </Button>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                onClick={doApprove}
                disabled={!data}
                loading={approveBusy}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                }}
              >
                审批通过
              </Button>
            </>
          )}
          {/* pending + customer_admin —— 「关闭 / 保存草稿 / 撤回申请」 */}
          {status === "pending" && !isSuper && (
            <>
              <Button onClick={onClose}>关闭</Button>
              <Button
                danger
                onClick={doWithdraw}
                disabled={!data}
                loading={withdrawBusy}
              >
                撤回申请
              </Button>
              <Button
                type="primary"
                onClick={() => void saveAdapter?.()}
                disabled={!data || !saveAdapter}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                }}
              >
                保存草稿
              </Button>
            </>
          )}
          {/* rejected + super_admin —— 「关闭 / 审批通过」 */}
          {status === "rejected" && isSuper && (
            <>
              <Button onClick={onClose}>关闭</Button>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                onClick={doApprove}
                disabled={!data}
                loading={approveBusy}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                }}
              >
                审批通过
              </Button>
            </>
          )}
          {/* rejected + customer_admin —— 「关闭 / 重新提交」 */}
          {status === "rejected" && !isSuper && (
            <>
              <Button onClick={onClose}>关闭</Button>
              <Button
                type="primary"
                onClick={doResubmit}
                disabled={!data || !originalWizardPayload}
                loading={resubmitBusy}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                }}
              >
                重新提交
              </Button>
            </>
          )}
        </Space>
      </div>

      {/* ===== unified brand editor (monitor brand + competitor brands) ===== */}
      <BrandEditModal
        open={brandEditModal !== null}
        title={brandEditModal?.title ?? "编辑品牌"}
        initialName={brandEditModal?.initialName ?? ""}
        initialAliases={brandEditModal?.initialAliases ?? []}
        onCancel={() => setBrandEditModal(null)}
        onConfirm={confirmBrandEdit}
      />

      {/* ===== keyword add/edit modal ===== */}
      <NameEditModal
        open={keywordModal !== null}
        title={keywordModal?.mode === "edit" ? "编辑核心词" : "新增核心词"}
        initial={keywordModal?.mode === "edit" ? keywordModal.original : ""}
        onCancel={() => setKeywordModal(null)}
        onConfirm={confirmKeyword}
      />

      {/* ===== 为问题分配分类 弹出卡片 ===== */}
      <CategoryAssignModal
        open={assignModalOpen}
        initialTaxonomy={categoryTaxonomy}
        initialAssignments={questionCategories}
        questionList={questionList}
        onCancel={() => setAssignModalOpen(false)}
        onConfirm={(nextTaxonomy, nextAssignments, renames, removed) => {
          setCategoryTaxonomy(nextTaxonomy);
          setQuestionCategories(nextAssignments);
          // Forward accumulated renames / removals to the server-side
          // cascading logic so prompt.category is rewritten (renames) or
          // nulled (removals) in one PUT /projects call.
          setCategoryRenames((prev) => ({ ...prev, ...renames }));
          for (const name of removed) {
            setCategoryRenames((prev) => {
              if (!(name in prev)) return prev;
              const next = { ...prev };
              delete next[name];
              return next;
            });
          }
          setAssignModalOpen(false);
        }}
      />

      {/* ===== schedule times modal 已废弃:周内监控日期与频次由
            WizardMonitorCard 编辑,具体时间由 backend 从 freq+days 计算,
            这里不再需要手动配置 times[] —— 把整个 Modal 删掉以免误用。 ===== */}

      {/* ===== 驳回输入弹窗 —— pending + super_admin 用 ===== */}
      <Modal
        open={rejectModalOpen}
        title="驳回申请"
        okText="确认驳回"
        cancelText="取消"
        okButtonProps={{ danger: true, loading: rejectBusy }}
        onCancel={() => {
          if (rejectBusy) return;
          setRejectModalOpen(false);
          setReviewNoteDraft("");
        }}
        onOk={doReject}
        destroyOnHidden
      >
        <div style={{ marginBottom: 8, fontSize: 13, color: "var(--text-tertiary)" }}>
          驳回原因会回写到项目记录,提交人在「待审核」页面可看到。
        </div>
        <Input.TextArea
          rows={4}
          value={reviewNoteDraft}
          onChange={(e) => setReviewNoteDraft(e.target.value)}
          placeholder="例如:问题数量不足 10 个,请补充后重新提交"
          maxLength={500}
          showCount
          autoFocus
        />
      </Modal>
    </Modal>
  );
}
