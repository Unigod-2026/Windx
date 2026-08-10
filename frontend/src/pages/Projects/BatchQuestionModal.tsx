import {
  Button,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Switch,
  Tooltip,
  message,
} from "antd";
import {
  CloseOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useEffect, useState } from "react";
import {
  createCompetitor,
  deleteCompetitor,
  getProject,
  listCompetitors,
  putKeywords,
  putPlatforms,
  putPrompts,
  triggerRun,
  updateCompetitor,
  updateProject,
  updateSchedule,
  type CompetitorOut,
  type ProjectDetailOut,
  type ProjectPlatform,
  type SlotOut,
} from "../../api/projects";

type DeliveryMode = "web" | "mobile";

interface PlatformCardConfig {
  enabled: boolean;
  delivery_mode: DeliveryMode;
  thinking_mode: boolean;
  screenshot: boolean;
}

interface ModelCardMeta {
  name: string;
  logo: string;
  bg: string;
  fg: string;
}

const PLATFORM_CATALOG: ModelCardMeta[] = [
  { name: "豆包", logo: "豆", bg: "#1e40af", fg: "#ffffff" },
  { name: "元宝", logo: "元", bg: "#dc2626", fg: "#ffffff" },
  { name: "DeepSeek", logo: "D", bg: "#0891b2", fg: "#ffffff" },
  { name: "百度文心", logo: "文", bg: "#2563eb", fg: "#ffffff" },
  { name: "通义千问", logo: "通", bg: "#7c3aed", fg: "#ffffff" },
  { name: "腾讯混元", logo: "混", bg: "#059669", fg: "#ffffff" },
  { name: "抖音豆包", logo: "抖", bg: "#0f172a", fg: "#ffffff" },
  { name: "Kimi", logo: "K", bg: "#0f172a", fg: "#ffffff" },
  { name: "夸克", logo: "夸", bg: "#7c3aed", fg: "#ffffff" },
  { name: "智谱清言", logo: "智", bg: "#ea580c", fg: "#ffffff" },
  { name: "秘塔AI", logo: "M", bg: "#1f2937", fg: "#ffffff" },
  { name: "ChatGPT", logo: "G", bg: "#10b981", fg: "#ffffff" },
];

function Chip(props: {
  text: string;
  onRemove?: () => void;
  placeholder?: boolean;
  onClick?: () => void;
}) {
  const { text, onRemove, placeholder, onClick } = props;
  const baseStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "3px 10px",
    borderRadius: 4,
    fontSize: 13,
    lineHeight: 1.4,
    cursor: onClick ? "pointer" : "default",
  };
  return (
    <span
      onClick={onClick}
      style={
        placeholder
          ? {
              ...baseStyle,
              background: "#fafafa",
              border: "1px dashed var(--border-strong)",
              color: "var(--text-quaternary)",
            }
          : {
              ...baseStyle,
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              color: "var(--brand-blue)",
            }
      }
    >
      {text}
      {onRemove && !placeholder && (
        <CloseOutlined
          style={{ fontSize: 10, opacity: 0.55, marginLeft: 2 }}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        />
      )}
    </span>
  );
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
        marginBottom: 8,
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

function Field(props: {
  label: string;
  extra?: React.ReactNode;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ marginBottom: 10, ...props.style }}>
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

function Card(props: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "#fff",
        borderRadius: 8,
        padding: 18,
        marginBottom: 14,
        ...props.style,
      }}
    >
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
      destroyOnClose
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

  // form state
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [questions, setQuestions] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<Record<string, PlatformCardConfig>>({});
  const [modelFilterAll, setModelFilterAll] = useState(true);
  const [thinkingMode, setThinkingMode] = useState(false);
  const [screenshotMode, setScreenshotMode] = useState(false);
  const [comboMode, setComboMode] = useState(false);

  const [frequency, setFrequency] = useState<"start" | "daily">("daily");
  const [dayInterval, setDayInterval] = useState(1);
  const [questionPosition, setQuestionPosition] = useState<"national_random" | "fixed">(
    "national_random",
  );
  const [regionCodesText, setRegionCodesText] = useState("");
  const [sentiment, setSentiment] = useState<"on" | "off">("on");
  const [ranking, setRanking] = useState("overall");
  const [pushCustomer, setPushCustomer] = useState<string | undefined>(undefined);
  const [migrate, setMigrate] = useState(false);

  // competitor / keyword modal state
  const [competitorModal, setCompetitorModal] = useState<
    { mode: "add" } | { mode: "edit"; target: CompetitorOut } | null
  >(null);
  const [keywordModal, setKeywordModal] = useState<
    { mode: "add" } | { mode: "edit"; index: number; original: string } | null
  >(null);
  // shows the last touched competitor in the read-only input box
  const [competitorDisplay, setCompetitorDisplay] = useState("");

  useEffect(() => {
    if (!open) return;
    setData(null);
    setCompetitors([]);
    setName("");
    setBrand("");
    setQuestions("");
    setKeywords([]);
    setPlatforms({});
    setQuestionPosition("national_random");
    setRegionCodesText("");
    setSentiment("on");
    setFrequency("daily");
    setDayInterval(1);
    setRanking("overall");
    setPushCustomer(undefined);
    setMigrate(false);
    setCompetitorDisplay("");
    setCompetitorModal(null);
    setKeywordModal(null);

    if (projectId === undefined) return;
    setLoading(true);
    (async () => {
      try {
        const d = await getProject(projectId);
        setData(d);
        setName(d.name);
        setBrand(d.keywords[0] ?? "");
        setQuestions(d.prompts.join("\n"));
        setKeywords(d.keywords);
        setPlatforms(() => {
          const init: Record<string, PlatformCardConfig> = {};
          for (const p of d.platforms) {
            init[p.platform] = {
              enabled: true,
              delivery_mode: p.delivery_mode,
              thinking_mode: p.thinking_mode,
              screenshot: p.screenshot === 1,
            };
          }
          return init;
        });
        setFrequency(d.schedule_enabled ? "daily" : "start");
        setQuestionPosition(d.region_strategy);
        setRegionCodesText((d.region_codes ?? []).join(","));
        setSentiment(d.sentiment_enabled ? "on" : "off");
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
        thinking_mode: false,
        screenshot: false,
      };
      return { ...prev, [name]: { ...cur, delivery_mode: mode } };
    });
  };

  // ---- competitor CRUD via API (must persist) ----
  const confirmCompetitor = async (value: string) => {
    if (!competitorModal) return;
    if (projectId === undefined) return;
    try {
      if (competitorModal.mode === "add") {
        await createCompetitor(projectId, { name: value });
      } else {
        await updateCompetitor(projectId, competitorModal.target.id, { name: value });
      }
      const comp = await listCompetitors(projectId);
      setCompetitors(comp.items);
      setCompetitorDisplay(value);
      setCompetitorModal(null);
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
      if (competitorDisplay && competitors.find((c) => c.id === id)?.name === competitorDisplay) {
        setCompetitorDisplay("");
      }
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

  // ---- save actions ----
  const collectPayloads = () => {
    const questionList = questions
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const platformsOut: ProjectPlatform[] = PLATFORM_CATALOG.filter(
      (m) => platforms[m.name]?.enabled,
    ).map((m, i) => {
      const c = platforms[m.name]!;
      return {
        platform: m.name,
        mode: c.delivery_mode,
        delivery_mode: c.delivery_mode,
        thinking_mode: c.thinking_mode || thinkingMode,
        screenshot: c.screenshot || screenshotMode ? 1 : 0,
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
    try {
      await updateProject(data.id, {
        name: name.trim(),
        status: "disabled",
        sentiment_enabled: sentiment === "on",
        region_strategy: questionPosition,
        region_codes: regionCodes,
      });
      await putPrompts(data.id, questionList);
      await putKeywords(data.id, keywords);
      await putPlatforms(data.id, platformsOut);
      message.success("已保存为草稿");
      onSaved();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const saveAndRun = async () => {
    if (!data) return;
    const { questionList, platformsOut, regionCodes } = collectPayloads();
    if (questionList.length === 0) {
      message.warning("请先填写监控问题");
      return;
    }
    if (platformsOut.length === 0) {
      message.warning("请至少选择 1 个模型");
      return;
    }
    try {
      await updateProject(data.id, {
        name: name.trim(),
        status: "active",
        sentiment_enabled: sentiment === "on",
        region_strategy: questionPosition,
        region_codes: regionCodes,
      });
      await putPrompts(data.id, questionList);
      await putKeywords(data.id, keywords);
      await putPlatforms(data.id, platformsOut);
      if (frequency === "start") {
        await updateSchedule(data.id, { schedule_enabled: false, slots: [] });
      } else if (data.slots.length > 0) {
        const slots: SlotOut[] = data.slots;
        await updateSchedule(data.id, {
          schedule_enabled: true,
          slots: slots.map((s) => ({ hour: s.hour, minute: s.minute })),
        });
      }
      try {
        await triggerRun(data.id);
        message.success("已保存并触发执行");
      } catch (err) {
        const e = err as { response?: { status?: number; data?: { detail?: string } } };
        if (e?.response?.status === 409) {
          message.success("已保存,5 分钟内已执行过,已跳过本次触发");
        } else {
          message.warning(
            e?.response?.data?.detail || (err as Error).message || "已保存,但触发失败",
          );
        }
      }
      onSaved();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const enabledCount = PLATFORM_CATALOG.filter((m) => platforms[m.name]?.enabled).length;
  const questionList = questions.split("\n").map((s) => s.trim()).filter(Boolean);
  const questionCount = questionList.length;
  const subtasks = questionCount * enabledCount;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={1440}
      centered
      closable={false}
      destroyOnClose
      styles={{
        body: { padding: 0 },
        content: { padding: 0, overflow: "hidden", borderRadius: 10 },
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
          padding: "16px 24px",
          background: "#f5f6f8",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 380px",
            gap: 14,
          }}
        >
          {/* ============= LEFT COLUMN ============= */}
          <div>
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
                  <Input
                    placeholder="点击添加监控品牌"
                    value={brand}
                    onChange={(e) => setBrand(e.target.value)}
                  />
                </div>
              </div>
            </Card>

            {/* ---- Card 2: 竞品品牌 (read-only input + chip list) ---- */}
            <Card>
              <SectionTitle title="竞品品牌" />
              <div style={{ position: "relative", marginBottom: 10 }}>
                <Input
                  readOnly
                  value={competitorDisplay}
                  placeholder="点击右侧 + 图标添加竞品品牌"
                  style={{ paddingRight: 38 }}
                  onClick={() => {
                    if (projectId === undefined) {
                      message.info("请先保存项目后再添加竞品");
                      return;
                    }
                    setCompetitorModal({ mode: "add" });
                  }}
                />
                <span
                  onClick={() => {
                    if (projectId === undefined) {
                      message.info("请先保存项目后再添加竞品");
                      return;
                    }
                    setCompetitorModal({ mode: "add" });
                  }}
                  style={{
                    position: "absolute",
                    right: 10,
                    top: "50%",
                    transform: "translateY(-50%)",
                    width: 22,
                    height: 22,
                    borderRadius: 4,
                    background: "var(--brand-blue)",
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    cursor: projectId === undefined ? "not-allowed" : "pointer",
                    opacity: projectId === undefined ? 0.5 : 1,
                  }}
                >
                  <PlusOutlined style={{ fontSize: 12 }} />
                </span>
              </div>
              <Space size={6} wrap>
                {competitors.length === 0 ? (
                  <Chip text="暂未添加" placeholder />
                ) : (
                  competitors.map((c) => (
                    <Chip
                      key={c.id}
                      text={c.name}
                      onClick={() => setCompetitorModal({ mode: "edit", target: c })}
                      onRemove={() => removeCompetitor(c.id)}
                    />
                  ))
                )}
              </Space>
            </Card>

            {/* ---- Card 3: 核心词 (list) + 监控问题 ---- */}
            <Card style={{ marginBottom: 0 }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)", gap: 18 }}>
                {/* 核心词 list */}
                <div>
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
                      border: "1px solid var(--border-light)",
                      borderRadius: 6,
                      overflow: "hidden",
                    }}
                  >
                    {keywords.length === 0 ? (
                      <div
                        style={{
                          padding: "20px 12px",
                          textAlign: "center",
                          color: "var(--text-quaternary)",
                          fontSize: 13,
                        }}
                      >
                        暂无核心词,点击右上角新增
                      </div>
                    ) : (
                      keywords.map((k, i) => (
                        <div
                          key={`${k}-${i}`}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            padding: "8px 12px",
                            borderBottom:
                              i === keywords.length - 1 ? "none" : "1px solid var(--border-light)",
                            background: i % 2 === 0 ? "#fff" : "#fafbfc",
                          }}
                        >
                          <span
                            onClick={() =>
                              setKeywordModal({ mode: "edit", index: i, original: k })
                            }
                            style={{
                              flex: 1,
                              fontSize: 13,
                              color: "var(--text-primary)",
                              cursor: "pointer",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                            title={k}
                          >
                            {k}
                          </span>
                          <CloseOutlined
                            onClick={() => removeKeyword(i)}
                            style={{
                              color: "var(--text-tertiary)",
                              fontSize: 12,
                              cursor: "pointer",
                              padding: 4,
                            }}
                          />
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* 监控问题 textarea */}
                <div>
                  <SectionTitle title="监控问题" required />
                  <Input.TextArea
                    placeholder={
                      "每行输入一个监控问题，换行分隔\n例如：\n哪个智能客服系统最好用？\nAI智能和人工客服哪个效果更好？\n如何提升客服效率？"
                    }
                    value={questions}
                    onChange={(e) => setQuestions(e.target.value)}
                    rows={10}
                    style={{ fontSize: 13, lineHeight: 1.7 }}
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
            {/* ---- 模型选择 ---- */}
            <Card>
              <SectionTitle
                title="模型选择"
                required
                extra={
                  <Space size={8} wrap>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: 12,
                        color: "var(--text-secondary)",
                      }}
                    >
                      <Switch size="small" checked={modelFilterAll} onChange={setModelFilterAll} />
                      全部模型
                    </span>
                    <Button
                      size="small"
                      type={thinkingMode ? "primary" : "default"}
                      onClick={() => setThinkingMode(!thinkingMode)}
                      style={
                        thinkingMode
                          ? {
                              background: "var(--brand-blue)",
                              borderColor: "var(--brand-blue)",
                            }
                          : undefined
                      }
                    >
                      豆包思考
                    </Button>
                    <Button
                      size="small"
                      type={screenshotMode ? "primary" : "default"}
                      onClick={() => setScreenshotMode(!screenshotMode)}
                      style={
                        screenshotMode
                          ? {
                              background: "var(--brand-blue)",
                              borderColor: "var(--brand-blue)",
                            }
                          : undefined
                      }
                    >
                      拍照助手
                    </Button>
                    <span style={{ position: "relative", display: "inline-block" }}>
                      <Button
                        size="small"
                        type={comboMode ? "primary" : "default"}
                        onClick={() => setComboMode(!comboMode)}
                        style={
                          comboMode
                            ? {
                                background: "var(--brand-blue)",
                                borderColor: "var(--brand-blue)",
                              }
                            : undefined
                        }
                      >
                        组合排序
                      </Button>
                      <span
                        style={{
                          position: "absolute",
                          top: -8,
                          right: -8,
                          background: comboMode ? "#fff" : "var(--brand-blue)",
                          color: comboMode ? "var(--brand-blue)" : "#fff",
                          fontSize: 10,
                          padding: "1px 4px",
                          borderRadius: 3,
                          fontWeight: 500,
                          lineHeight: 1.2,
                          border: comboMode ? "1px solid var(--brand-blue)" : "none",
                        }}
                      >
                        Step组合
                      </span>
                    </span>
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
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: 8,
                }}
              >
                {PLATFORM_CATALOG.map((m) => {
                  const cfg = platforms[m.name]?.enabled ? platforms[m.name] : null;
                  return (
                    <div
                      key={m.name}
                      onClick={() => togglePlatform(m.name)}
                      style={{
                        border: `1px solid ${cfg ? "var(--brand-blue)" : "var(--border-default)"}`,
                        borderRadius: 8,
                        padding: "6px 4px",
                        cursor: "pointer",
                        background: cfg ? "#eff6ff" : "#fff",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 2,
                        transition: "all 0.15s",
                      }}
                    >
                      <div
                        style={{
                          width: 26,
                          height: 26,
                          borderRadius: "50%",
                          background: m.bg,
                          color: m.fg,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontWeight: 600,
                          fontSize: 12,
                        }}
                      >
                        {m.logo}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          fontWeight: 500,
                          color: cfg ? "var(--brand-blue)" : "var(--text-primary)",
                        }}
                      >
                        {m.name}
                      </div>
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          setPlatformDelivery(
                            m.name,
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
                    </div>
                  );
                })}
              </div>
            </Card>

            {/* ---- settings panel ---- */}
            <Card style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                block
                onClick={saveDraft}
                disabled={!data}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                  marginBottom: 16,
                  fontWeight: 500,
                }}
              >
                保存
              </Button>

              <Field label="监控频次">
                <Segmented
                  block
                  value={frequency}
                  onChange={(v) => setFrequency(v as "start" | "daily")}
                  options={[
                    { label: "开始", value: "start" },
                    { label: "每日", value: "daily" },
                  ]}
                />
                <div
                  style={{
                    marginTop: 10,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <InputNumber
                    min={0}
                    max={30}
                    value={dayInterval}
                    onChange={(v) => setDayInterval(Number(v ?? 0))}
                    style={{ width: "100%" }}
                    disabled={frequency === "start"}
                  />
                  <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>天</span>
                </div>
              </Field>

              <Field label="提问位置">
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
                    placeholder="地域代码,逗号分隔,如 110000,310000"
                    value={regionCodesText}
                    onChange={(e) => setRegionCodesText(e.target.value)}
                    style={{ marginTop: 8 }}
                    size="small"
                  />
                )}
              </Field>

              <Field label="情感倾向">
                <Select
                  value={sentiment}
                  onChange={(v) => setSentiment(v)}
                  options={[
                    { value: "on", label: "开启分析" },
                    { value: "off", label: "关闭分析" },
                  ]}
                  style={{ width: "100%" }}
                />
              </Field>

              <Field label="排名设置">
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
              </Field>

              <Field
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
              </Field>

              <Field
                label="迁移设置"
                style={{ marginBottom: 0 }}
                extra={
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Switch size="small" checked={migrate} onChange={setMigrate} />
                    <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>同步</span>
                  </span>
                }
              >
                <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                  {migrate ? "已开启同步" : "未开启同步"}
                </div>
              </Field>
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
          <Button onClick={saveDraft} disabled={!data}>
            保存草稿({subtasks}份待存)
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={saveAndRun}
            disabled={!data}
            style={{
              background: "var(--brand-blue)",
              borderColor: "var(--brand-blue)",
            }}
          >
            保存并立即执行
          </Button>
        </Space>
      </div>

      {/* ===== competitor add/edit modal ===== */}
      <NameEditModal
        open={competitorModal !== null}
        title={
          competitorModal?.mode === "edit"
            ? "编辑竞品品牌"
            : "新增竞品品牌"
        }
        initial={
          competitorModal?.mode === "edit" ? competitorModal.target.name : ""
        }
        onCancel={() => setCompetitorModal(null)}
        onConfirm={confirmCompetitor}
      />

      {/* ===== keyword add/edit modal ===== */}
      <NameEditModal
        open={keywordModal !== null}
        title={keywordModal?.mode === "edit" ? "编辑核心词" : "新增核心词"}
        initial={keywordModal?.mode === "edit" ? keywordModal.original : ""}
        onCancel={() => setKeywordModal(null)}
        onConfirm={confirmKeyword}
      />
    </Modal>
  );
}
