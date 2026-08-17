import {
  Button,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  TimePicker,
  Tooltip,
  message,
} from "antd";
import {
  CloseOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  SettingOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { CirclePlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import dayjs from "dayjs";
import {
  createCompetitor,
  deleteCompetitor,
  getProject,
  listCompetitors,
  putKeywords,
  putPlatforms,
  putPrompts,
  updateCompetitor,
  updateProject,
  updateSchedule,
  type CompetitorOut,
  type ProjectDetailOut,
  type ProjectPlatform,
  type SlotIn,
} from "../../api/projects";
import BrandEditModal from "./BrandEditModal";
import { PLATFORM_CATALOG, platformToKey } from "./platforms";

type DeliveryMode = "web" | "mobile";
type Mode = "standard" | "reasoning";

interface PlatformCardConfig {
  enabled: boolean;
  delivery_mode: DeliveryMode;
  /** UI exposes only the two common ones; ``search`` / ``reasoning_search``
   *  stay valid at the API layer for advanced configs. */
  mode: Mode;
  thinking_mode: boolean;
  screenshot: boolean;
}

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

export default function BatchQuestionModal({
  open,
  projectId,
  onClose,
  onSaved,
}: BatchQuestionModalProps) {
  const isEdit = projectId !== undefined;

  const [, setLoading] = useState(false);
  const [data, setData] = useState<ProjectDetailOut | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorOut[]>([]);
  // Snapshot of PromptOut keyed by question text — used by saveDraft to
  // preserve category/status when the user re-saves the same list via this
  // modal (which has no UI for those fields).
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
  const [platforms, setPlatforms] = useState<Record<string, PlatformCardConfig>>({});
  const [thinkingMode, setThinkingMode] = useState(false);
  const [screenshotMode, setScreenshotMode] = useState<"disabled" | "mentioned" | "all">(
    "disabled",
  );

  const [autoMode, setAutoMode] = useState<"daily" | "weekly">("daily");
  const [runCount, setRunCount] = useState(2);
  const [times, setTimes] = useState<string[]>(["09:00", "14:00"]);
  const [timesModalOpen, setTimesModalOpen] = useState(false);
  const [projectStatus, setProjectStatus] = useState<"active" | "disabled">("active");
  // Opens the popup that combines the project-level category taxonomy and
  // per-question category assignment (left = categories, right = checkbox
  // list of questions). The popup owns its own taxonomy copy and writes
  // back on confirm via ``setCategoryTaxonomy`` / ``setQuestionCategories``.
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [questionPosition, setQuestionPosition] = useState<"national_random" | "fixed">(
    "national_random",
  );
  const [regionCodesText, setRegionCodesText] = useState("");
  const [sentiment, setSentiment] = useState<"on" | "off">("on");
  // Per-question category overrides — keyed by the question text. Set when
  // the admin picks a category in the "为问题分配分类" card above the
  // textarea; on save this map wins over the snapshot loaded from the
  // server (so the admin's in-modal edits aren't lost). Keys are removed
  // when the admin picks "未分类" (allowClear).
  const [questionCategories, setQuestionCategories] = useState<Record<string, string | null>>({});
  const [ranking, setRanking] = useState("overall");
  const [pushCustomer, setPushCustomer] = useState<string | undefined>(undefined);
  const [targetSetting, setTargetSetting] = useState<string | undefined>(undefined);

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
    setPlatforms({});
    setQuestionPosition("national_random");
    setRegionCodesText("");
    setSentiment("on");
    setAutoMode("daily");
    setRunCount(2);
    setTimes(["09:00", "14:00"]);
    setTimesModalOpen(false);
    setProjectStatus("active");
    setQuestionCategories({});
    setRanking("overall");
    setPushCustomer(undefined);
    setTargetSetting(undefined);
    setThinkingMode(false);
    setScreenshotMode("disabled");
    setKeywordModal(null);
    setBrandEditModal(null);
    setAssignModalOpen(false);
    promptIndexRef.current = new Map();

    if (projectId === undefined) return;
    setLoading(true);
    (async () => {
      try {
        const d = await getProject(projectId);
        setData(d);
        setName(d.name);
        // 「监控品牌」在 backend 走 ``geo_projects.brand``,与「核心词」
        // (geo_project_keywords) 是两个独立概念 —— 这里只读自己的列,
        // 不要 fallback 到 keywords[0],否则会出现 brand 与核心词互
        // 相覆盖的旧 bug。
        setBrand(d.brand ?? "");
        setBrandAliases(d.aliases ?? []);
        // d.prompts is PromptOut[] (new shape with id/category/status/sort) —
        // this modal only edits the question text via a textarea, so collapse
        // to the raw strings; category/status is preserved per-text via the
        // snapshot used in saveDraft.
        setQuestions(d.prompts.map((p) => p.prompt).join("\n"));
        // Rebuild the snapshot from the freshly-loaded prompts so saveDraft
        // can preserve category/status when re-saving the same list.
        const idx = new Map<
          string,
          { category: string | null; status: "monitoring" | "paused" | "archived" }
        >();
        for (const p of d.prompts) {
          idx.set(p.prompt, { category: p.category, status: p.status });
        }
        promptIndexRef.current = idx;
        // Seed the per-question category overrides from the loaded prompts
        // so the "为问题分配分类" card shows each question's current label.
        // The admin's later edits win over this baseline on save.
        const seedCats: Record<string, string | null> = {};
        for (const p of d.prompts) {
          if (p.category) seedCats[p.prompt] = p.category;
        }
        setQuestionCategories(seedCats);
        setKeywords(d.keywords);
        setCategoryTaxonomy(d.category_taxonomy ?? []);
        setCategoryRenames({});
        setPlatforms(() => {
          const init: Record<string, PlatformCardConfig> = {};
          for (const p of d.platforms) {
            const k = platformToKey(p.platform);
            init[k] = {
              enabled: true,
              delivery_mode: p.delivery_mode,
              // ``p.mode`` was occasionally written as ``delivery_mode.value``
              // ("web"/"mobile") by an earlier bug — see
              // backend/app/services/scheduler.py submit payload comment. Only
              // accept the two LLM modes the UI exposes and fall back to
              // ``standard`` so legacy rows don't break the load.
              mode: p.mode === "reasoning" ? "reasoning" : "standard",
              thinking_mode: p.thinking_mode,
              screenshot: p.screenshot === 1,
            };
          }
          return init;
        });
        const screens = d.platforms.map((p) => p.screenshot);
        if (screens.some((s) => s === 2)) setScreenshotMode("mentioned");
        else if (screens.some((s) => s === 1)) setScreenshotMode("all");
        else setScreenshotMode("disabled");
        setQuestionPosition(d.region_strategy);
        setRegionCodesText((d.region_codes ?? []).join(","));
        setSentiment(d.sentiment_enabled ? "on" : "off");
        setProjectStatus(d.status === "disabled" ? "disabled" : "active");
        if (d.slots.length > 0) {
          const loaded = d.slots.map((s) =>
            `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`,
          );
          setTimes(loaded);
          setRunCount(loaded.length);
          setAutoMode("daily");
        }
        const comp = await listCompetitors(projectId).catch(() => ({
          items: [] as CompetitorOut[],
        }));
        setCompetitors(comp.items);
      } catch (err) {
        message.error((err as Error).message || "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [open, projectId]);

  const togglePlatform = (name: string) => {
    setPlatforms((prev) => {
      const cur = prev[name];
      if (cur) {
        return { ...prev, [name]: { ...cur, enabled: !cur.enabled } };
      }
      return {
        ...prev,
        [name]: {
          enabled: true,
          delivery_mode: "web",
          mode: "standard",
          thinking_mode: false,
          screenshot: false,
        },
      };
    });
  };

  const setPlatformDelivery = (name: string, mode: DeliveryMode) => {
    setPlatforms((prev) => {
      const cur = prev[name] ?? {
        enabled: true,
        delivery_mode: mode,
        mode: "standard",
        thinking_mode: false,
        screenshot: false,
      };
      return { ...prev, [name]: { ...cur, delivery_mode: mode } };
    });
  };

  const setPlatformMode = (name: string, mode: Mode) => {
    setPlatforms((prev) => {
      const cur = prev[name] ?? {
        enabled: true,
        delivery_mode: "web",
        mode,
        thinking_mode: false,
        screenshot: false,
      };
      return { ...prev, [name]: { ...cur, mode } };
    });
  };

  // ---- unified brand editor confirm ----
  // Monitor brand stays local (persists with the bottom 保存 button); the two
  // competitor scopes hit the API right away so the chip list reflects reality.
  const confirmBrandEdit = async (name: string, aliases: string[]) => {
    if (!brandEditModal) return;
    if (brandEditModal.scope === "brand") {
      setBrand(name);
      setBrandAliases(aliases);
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

  // ---- schedule helpers ----
  const updateRunCount = (n: number | null) => {
    const clamped = Math.max(1, Math.min(24, n ?? 1));
    setRunCount(clamped);
    setTimes((prev) => {
      if (clamped > prev.length) {
        return [...prev, ...Array(clamped - prev.length).fill("12:00")];
      }
      if (clamped < prev.length) {
        return prev.slice(0, clamped);
      }
      return prev;
    });
  };

  const updateTime = (index: number, value: string) => {
    setTimes((prev) => prev.map((t, i) => (i === index ? value : t)));
  };

  // ---- save actions ----
  const collectPayloads = () => {
    const questionList = questions
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const platformsOut: ProjectPlatform[] = PLATFORM_CATALOG.filter(
      (m) => platforms[m.key]?.enabled,
    ).map((m, i) => {
      const c = platforms[m.key]!;
      return {
        platform: m.key,
        mode: c.mode,
        delivery_mode: c.delivery_mode,
        thinking_mode: c.thinking_mode || thinkingMode,
        screenshot:
          screenshotMode === "all"
            ? 1
            : screenshotMode === "mentioned"
              ? 2
              : 0,
        sort: i,
      };
    });
    const regionCodes =
      questionPosition === "fixed" && regionCodesText
        ? regionCodesText
            .split(/[,\s]+/)
            .map((s) => s.trim())
            .filter(Boolean)
        : null;
    return { questionList, platformsOut, regionCodes };
  };

  const saveDraft = async () => {
    if (!data) return;
    const { questionList, platformsOut, regionCodes } = collectPayloads();
    const trimmedBrand = brand.trim();
    try {
      // Trim + dedupe + drop empties before sending the taxonomy. The
      // backend re-validates (no empties, no duplicates) and rejects with
      // a 400 if the UI somehow sent junk.
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
        sentiment_enabled: sentiment === "on",
        region_strategy: questionPosition,
        region_codes: regionCodes,
        // 监控品牌 → geo_projects.brand,与核心词独立。
        brand: trimmedBrand || null,
        aliases: brandAliases,
        category_taxonomy: cleanedTaxonomy,
        category_renames:
          Object.keys(cleanedRenames).length > 0 ? cleanedRenames : null,
      });
      // Persist prompts in the new full-shape (PromptInPayload) so the
      // backend can keep category/status. Order of precedence:
      //   1. Admin's in-modal category edit (set via the "为问题分配分类"
      //      card above the textarea) — keyed by question text.
      //   2. The snapshot we loaded at modal-open time (covers category
      //      edits made via PromptsTab).
      //   3. Default: monitoring + no category.
      const promptResult = await putPrompts(
        data.id,
        questionList.map((text) => {
          const prior = promptIndexRef.current.get(text);
          const edited =
            text in questionCategories
              ? questionCategories[text]
              : prior?.category ?? null;
          return {
            prompt: text,
            category: edited,
            status: prior?.status ?? "monitoring",
          };
        }),
      );
      // If the backend had to drop categories that aren't in the taxonomy
      // (legacy data from before this column existed), surface it so the
      // admin knows to re-assign them in the "为问题分配分类" card.
      const dropped = promptResult?.dropped_categories ?? [];
      // putKeywords 只管核心词,不再夹带监控品牌。
      await putKeywords(data.id, keywords);
      await putPlatforms(data.id, platformsOut);
      const slots: SlotIn[] = times.map((t) => {
        const [hh, mm] = t.split(":").map(Number);
        return { hour: hh ?? 0, minute: mm ?? 0 };
      });
      await updateSchedule(data.id, {
        slots,
        schedule_enabled: data.schedule_enabled,
      });
      if (dropped.length > 0) {
        const uniq = Array.from(new Set(dropped));
        message.warning(
          `已保存。${uniq.length} 个不再属于当前分类体系的旧分类被自动清空: ${uniq.join("、")}`,
        );
      } else {
        message.success("已保存！");
      }
      onSaved();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const enabledCount = PLATFORM_CATALOG.filter((m) => platforms[m.key]?.enabled).length;
  const allReasoning =
    enabledCount > 0 &&
    PLATFORM_CATALOG.every(
      (m) => !platforms[m.key]?.enabled || platforms[m.key]?.mode === "reasoning",
    );
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
                  />
                </div>
                <div>
                  <SectionTitle title="监控品牌" required />
                  <button
                    type="button"
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
                      >
                        分配分类
                      </Button>
                    }
                  />
                  <Input.TextArea
                    placeholder={
                      "每行输入一个监控问题，换行分隔\n例如：\n哪个智能客服系统最好用？\nAI智能和人工客服哪个效果更好？\n如何提升客服效率？"
                    }
                    value={questions}
                    onChange={(e) => setQuestions(e.target.value)}
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
            {/* ---- Card 1: 模型选择 ---- */}
            <Card>
              <SectionTitle
                title="模型选择"
                required
                extra={
                  <Space size={6} wrap>
                    <Button
                      size="small"
                      onClick={() => {
                        setPlatforms((prev) => {
                          const next: Record<string, PlatformCardConfig> = {};
                          for (const m of PLATFORM_CATALOG) {
                            const cur = prev[m.key];
                            next[m.key] = cur
                              ? { ...cur, enabled: true }
                              : {
                                  enabled: true,
                                  delivery_mode: "web",
                                  mode: "standard",
                                  thinking_mode: false,
                                  screenshot: false,
                                };
                          }
                          return next;
                        });
                      }}
                    >
                      全部模型
                    </Button>
                    <Button
                      size="small"
                      type={allReasoning ? "primary" : "default"}
                      onClick={() => {
                        const target: Mode = allReasoning ? "standard" : "reasoning";
                        setPlatforms((prev) => {
                          const next = { ...prev };
                          for (const k of Object.keys(next)) {
                            if (next[k]?.enabled) {
                              next[k] = { ...next[k]!, mode: target };
                            }
                          }
                          return next;
                        });
                      }}
                      style={
                        allReasoning
                          ? {
                              background: "var(--brand-blue)",
                              borderColor: "var(--brand-blue)",
                            }
                          : undefined
                      }
                    >
                      深度思考
                    </Button>
                    <Select
                      size="small"
                      value={screenshotMode}
                      onChange={(v) => setScreenshotMode(v)}
                      style={{ width: 130 }}
                      options={[
                        { value: "disabled", label: "禁用截图" },
                        { value: "mentioned", label: "提及截图" },
                        { value: "all", label: "全部截图" },
                      ]}
                    />
                  </Space>
                }
              />
              <div
                style={{
                  fontSize: 12,
                  color: "var(--text-tertiary)",
                  marginBottom: 8,
                }}
              >
                已选 <strong style={{ color: "var(--brand-blue)" }}>{enabledCount}</strong> 个模型
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(6, 1fr)",
                  gap: 6,
                }}
              >
                {PLATFORM_CATALOG.map((m) => {
                  const cfg = platforms[m.key]?.enabled ? platforms[m.key] : null;
                  return (
                    <div
                      key={m.key}
                      onClick={() => togglePlatform(m.key)}
                      style={{
                        border: `1px solid ${cfg ? "var(--brand-blue)" : "var(--border-default)"}`,
                        borderRadius: 6,
                        padding: "6px 4px 5px",
                        cursor: "pointer",
                        background: cfg ? "#eff6ff" : "#fff",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 3,
                        transition: "all 0.15s",
                      }}
                    >
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: "50%",
                          background: m.bg,
                          color: m.fg,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontWeight: 600,
                          fontSize: 11,
                        }}
                      >
                        {m.logo}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          fontWeight: 500,
                          color: cfg ? "var(--brand-blue)" : "var(--text-primary)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {m.name}
                      </div>
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          setPlatformDelivery(
                            m.key,
                            cfg?.delivery_mode === "mobile" ? "web" : "mobile",
                          );
                        }}
                        style={{
                          fontSize: 10,
                          color:
                            cfg?.delivery_mode === "mobile"
                              ? "var(--brand-orange)"
                              : "var(--text-tertiary)",
                          padding: "0 5px",
                          border: `1px solid ${cfg?.delivery_mode === "mobile" ? "var(--brand-orange)" : "var(--border-default)"}`,
                          borderRadius: 3,
                          cursor: "pointer",
                          lineHeight: 1.5,
                        }}
                      >
                        {cfg?.delivery_mode === "mobile" ? "移动版" : "网页版"}
                      </div>
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          setPlatformMode(
                            m.key,
                            cfg?.mode === "reasoning" ? "standard" : "reasoning",
                          );
                        }}
                        style={{
                          fontSize: 10,
                          color:
                            cfg?.mode === "reasoning"
                              ? "var(--brand-blue)"
                              : "var(--text-tertiary)",
                          padding: "0 5px",
                          border: `1px solid ${cfg?.mode === "reasoning" ? "var(--brand-blue)" : "var(--border-default)"}`,
                          borderRadius: 3,
                          cursor: "pointer",
                          lineHeight: 1.5,
                        }}
                      >
                        {cfg?.mode === "reasoning" ? "深度思考" : "快速模式"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>

            {/* ---- Card 2: 监控频次 (matches reference: header Segmented + 2-col body + gear) ---- */}
            <Card>
              <SectionTitle
                title="监控频次"
                extra={
                  <Segmented
                    value={projectStatus}
                    onChange={(v) => setProjectStatus(v as "active" | "disabled")}
                    options={[
                      { label: "启用", value: "active" },
                      { label: "停用", value: "disabled" },
                    ]}
                  />
                }
              />
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr auto",
                  gap: 16,
                  alignItems: "end",
                }}
              >
                <div>
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--text-tertiary)",
                      marginBottom: 6,
                    }}
                  >
                    自动监控
                  </div>
                  <Select
                    value={autoMode}
                    onChange={(v) => setAutoMode(v)}
                    options={[
                      { value: "daily", label: "每日" },
                      { value: "weekly", label: "每周" },
                    ]}
                    style={{ width: "100%" }}
                  />
                </div>
                <div>
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--text-tertiary)",
                      marginBottom: 6,
                    }}
                  >
                    提问次数
                    <span style={{ color: "#ef4444", marginLeft: 2 }}>*</span>
                  </div>
                  <InputNumber
                    min={1}
                    max={24}
                    value={runCount}
                    onChange={updateRunCount}
                    style={{ width: "100%" }}
                  />
                </div>
                <Tooltip title="设置每次发起任务的具体时间">
                  <Button
                    icon={<SettingOutlined />}
                    onClick={() => setTimesModalOpen(true)}
                    style={{ height: 32, width: 32, padding: 0 }}
                  />
                </Tooltip>
              </div>
            </Card>

            {/* ---- Card 3: 其他设置 (grid with 3 rows) ---- */}
            <Card style={{ marginBottom: 0 }}>
              <SectionTitle title="其他设置" />
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 10,
                }}
              >
                {/* Row 1: 提问位置 + 情感倾向 */}
                <SettingSubCard label="提问位置">
                  <Select
                    value={questionPosition}
                    onChange={(v) => setQuestionPosition(v)}
                    options={[
                      { value: "national_random", label: "全国随机" },
                      { value: "fixed", label: "固定地域" },
                    ]}
                    style={{ width: "100%" }}
                  />
                  {questionPosition === "fixed" && (
                    <Input
                      placeholder="地域代码,如 110000,310000"
                      value={regionCodesText}
                      onChange={(e) => setRegionCodesText(e.target.value)}
                      style={{ marginTop: 6 }}
                      size="small"
                    />
                  )}
                </SettingSubCard>
                <SettingSubCard label="情感倾向">
                  <Select
                    value={sentiment}
                    onChange={(v) => setSentiment(v)}
                    options={[
                      { value: "on", label: "开启分析" },
                      { value: "off", label: "关闭分析" },
                    ]}
                    style={{ width: "100%" }}
                  />
                </SettingSubCard>

                {/* Row 2: 排名设置 + 推送客户 */}
                <SettingSubCard label="排名设置">
                  <Select
                    value={ranking}
                    onChange={setRanking}
                    options={[
                      { value: "overall", label: "整体排名" },
                      { value: "by_platform", label: "按模型" },
                      { value: "by_keyword", label: "按核心词" },
                    ]}
                    style={{ width: "100%" }}
                  />
                </SettingSubCard>
                <SettingSubCard
                  label="推送客户"
                  extra={
                    <a style={{ fontSize: 12, color: "var(--brand-blue)" }}>+ 新增客户</a>
                  }
                >
                  <Select
                    placeholder="选择客户"
                    value={pushCustomer}
                    onChange={setPushCustomer}
                    allowClear
                    options={[
                      { value: "acme", label: "ACME 集团" },
                      { value: "beta", label: "Beta 科技" },
                    ]}
                    style={{ width: "100%" }}
                  />
                </SettingSubCard>

                {/* Row 3: 达标设置 (spans both columns) */}
                <div style={{ gridColumn: "span 2" }}>
                  <SettingSubCard label="达标设置">
                    <Select
                      placeholder="选择达标策略"
                      value={targetSetting}
                      onChange={setTargetSetting}
                      allowClear
                      options={[
                        { value: "auto_stop", label: "达标后自动停止监控" },
                        { value: "notify", label: "达标时推送通知" },
                        { value: "ignore", label: "不做处理" },
                      ]}
                      style={{ width: "100%" }}
                    />
                  </SettingSubCard>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>

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
          <span style={{ fontSize: 16, fontWeight: 600, color: "var(--brand-blue)" }}>
            ¥0.00
          </span>
          <span style={{ color: "var(--text-tertiary)" }}>/ 次</span>
          <Tooltip title="按当前问题 × 模型 计算,实际费用以远端 API 报价为准">
            <InfoCircleOutlined style={{ color: "var(--text-tertiary)" }} />
          </Tooltip>
        </div>
        <Space size={10}>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            onClick={saveDraft}
            disabled={!data}
            style={{
              background: "var(--brand-blue)",
              borderColor: "var(--brand-blue)",
            }}
          >
            保存
          </Button>
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

      {/* ===== schedule times modal ===== */}
      <Modal
        open={timesModalOpen}
        title="设置每次发起任务的具体时间"
        okText="确定"
        cancelText="取消"
        onCancel={() => setTimesModalOpen(false)}
        onOk={() => setTimesModalOpen(false)}
        destroyOnHidden
        width={420}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {times.map((t, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <span
                style={{
                  width: 70,
                  fontSize: 13,
                  color: "var(--text-tertiary)",
                }}
              >
                第 {i + 1} 次
              </span>
              <TimePicker
                format="HH:mm"
                minuteStep={15}
                value={dayjs(`2000-01-01 ${t}`, "YYYY-MM-DD HH:mm")}
                onChange={(_d, dateString) =>
                  updateTime(i, (dateString as string) || "12:00")
                }
                style={{ width: 140 }}
                allowClear={false}
              />
            </div>
          ))}
          <div
            style={{
              fontSize: 12,
              color: "var(--text-tertiary)",
              marginTop: 8,
              lineHeight: 1.6,
            }}
          >
            提示:每 {autoMode === "daily" ? "天" : "周"} 将按以上时间自动发起 {times.length} 次监控。
          </div>
        </div>
      </Modal>
    </Modal>
  );
}
