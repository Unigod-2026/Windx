import {
  Alert,
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
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
  logo: string; // emoji or letter mark
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

function TagChip(props: {
  text: string;
  onRemove?: () => void;
  placeholder?: boolean;
}) {
  const { text, onRemove, placeholder } = props;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 10px",
        borderRadius: 4,
        background: placeholder ? "#f5f6f8" : "#eff6ff",
        border: placeholder ? "1px dashed var(--border-strong)" : "1px solid #bfdbfe",
        color: placeholder ? "var(--text-quaternary)" : "var(--brand-blue)",
        fontSize: 13,
      }}
    >
      {text}
      {onRemove && (
        <CloseOutlined
          style={{ fontSize: 10, cursor: "pointer", opacity: 0.6 }}
          onClick={onRemove}
        />
      )}
    </span>
  );
}

function SectionHeader(props: { title: string; required?: boolean; extra?: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 12,
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

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const navigate = useNavigate();

  const [data, setData] = useState<ProjectDetailOut | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorOut[]>([]);
  const [loading, setLoading] = useState(false);

  // local form state
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [questions, setQuestions] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [productBrands, setProductBrands] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<Record<string, PlatformCardConfig>>({});
  const [modelFilterAll, setModelFilterAll] = useState(true);
  const [thinkingMode, setThinkingMode] = useState(false);
  const [screenshotMode, setScreenshotMode] = useState(false);
  const [comboMode, setComboMode] = useState(false);

  const [frequency, setFrequency] = useState<"daily" | "once">("daily");
  const [dayInterval, setDayInterval] = useState(1);
  const [questionPosition, setQuestionPosition] = useState<"national_random" | "fixed">(
    "national_random",
  );
  const [regionCodesText, setRegionCodesText] = useState("");
  const [sentiment, setSentiment] = useState<"on" | "off">("on");
  const [ranking, setRanking] = useState("overall");

  const [competitorDraft, setCompetitorDraft] = useState("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [productDraft, setProductDraft] = useState("");
  const [editingCompetitor, setEditingCompetitor] = useState<CompetitorOut | null>(null);

  const load = async () => {
    if (!projectId) return;
    setLoading(true);
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
      setFrequency(d.schedule_enabled ? "daily" : "once");
      setDayInterval(1);
      setQuestionPosition(d.region_strategy);
      setRegionCodesText((d.region_codes ?? []).join(","));
      setSentiment(d.sentiment_enabled ? "on" : "off");
      setRanking("overall");
      const comp = await listCompetitors(projectId).catch(() => ({ items: [] as CompetitorOut[] }));
      setCompetitors(comp.items);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

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

  // ---- chip handlers ----
  const addKeyword = () => {
    const v = keywordDraft.trim();
    if (!v || keywords.includes(v)) return;
    setKeywords([...keywords, v]);
    setKeywordDraft("");
  };
  const addProduct = () => {
    const v = productDraft.trim();
    if (!v || productBrands.includes(v)) return;
    setProductBrands([...productBrands, v]);
    setProductDraft("");
  };

  // ---- competitor CRUD via API (must persist) ----
  const addCompetitor = async () => {
    const v = competitorDraft.trim();
    if (!v) return;
    try {
      await createCompetitor(projectId, { name: v });
      setCompetitorDraft("");
      const comp = await listCompetitors(projectId);
      setCompetitors(comp.items);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } };
      message.error(e?.response?.data?.detail || (err as Error).message || "新增失败");
    }
  };

  const removeCompetitor = async (id: number) => {
    try {
      await deleteCompetitor(projectId, id);
      const comp = await listCompetitors(projectId);
      setCompetitors(comp.items);
    } catch (err) {
      message.error((err as Error).message || "删除失败");
    }
  };

  const saveCompetitor = async (initial: CompetitorOut, name: string) => {
    try {
      await updateCompetitor(projectId, initial.id, { name });
      const comp = await listCompetitors(projectId);
      setCompetitors(comp.items);
      setEditingCompetitor(null);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } };
      message.error(e?.response?.data?.detail || (err as Error).message || "更新失败");
    }
  };

  // ---- bottom bar save actions ----
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
      await putKeywords(data.id, [...keywords, ...productBrands]);
      await putPlatforms(data.id, platformsOut);
      message.success("已保存为草稿");
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
      await putKeywords(data.id, [...keywords, ...productBrands]);
      await putPlatforms(data.id, platformsOut);
      // schedule: daily mode keeps existing slots, once mode disables
      if (frequency === "once") {
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
          message.warning(e?.response?.data?.detail || (err as Error).message || "已保存,但触发失败");
        }
      }
      navigate("/admin/projects");
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const estimateCost = useMemo(() => {
    const q = questions.split("\n").filter((s) => s.trim()).length;
    const p = PLATFORM_CATALOG.filter((m) => platforms[m.name]?.enabled).length;
    return q * p;
  }, [questions, platforms]);

  if (loading && !data) {
    return <div style={{ padding: 80, textAlign: "center" }}>加载中...</div>;
  }
  if (!data) {
    return (
      <div style={{ padding: 80, textAlign: "center", color: "var(--text-tertiary)" }}>
        项目不存在或加载失败
      </div>
    );
  }

  // enabled platform count for the model grid
  const enabledCount = PLATFORM_CATALOG.filter((m) => platforms[m.name]?.enabled).length;

  return (
    <div style={{ background: "#f5f6f8", minHeight: "calc(100vh - 64px)" }}>
      {/* ===== dark navy header bar ===== */}
      <div
        style={{
          background: "#0a2540",
          color: "#fff",
          padding: "16px 32px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          position: "sticky",
          top: 0,
          zIndex: 5,
        }}
      >
        <div style={{ fontSize: 18, fontWeight: 500 }}>批量添加问题</div>
        <Button
          type="text"
          icon={<CloseOutlined style={{ color: "#fff", fontSize: 18 }} />}
          onClick={() => navigate("/admin/projects")}
        />
      </div>

      <div style={{ padding: "20px 32px 100px" }}>
        {/* ===== top section: 3-col grid ===== */}
        <div
          style={{
            background: "#fff",
            borderRadius: 8,
            padding: 24,
            marginBottom: 16,
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 2fr",
              gap: 24,
              alignItems: "start",
            }}
          >
            {/* 监控名称 */}
            <div>
              <SectionHeader title="监控名称" required />
              <Input
                placeholder="请输入监控名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                size="large"
              />
            </div>
            {/* 监控品牌 */}
            <div>
              <SectionHeader title="监控品牌" required />
              <Input
                placeholder="点击添加监控品牌"
                value={brand}
                onChange={(e) => setBrand(e.target.value)}
                size="large"
              />
            </div>
            {/* 模型选择 */}
            <div>
              <SectionHeader
                title="模型选择"
                required
                extra={
                  <Space size={12}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-secondary)" }}>
                      <Switch
                        size="small"
                        checked={modelFilterAll}
                        onChange={setModelFilterAll}
                      />
                      全部模型
                    </span>
                    <Button
                      size="small"
                      type={thinkingMode ? "primary" : "default"}
                      onClick={() => setThinkingMode(!thinkingMode)}
                    >
                      豆包思考
                    </Button>
                    <Button
                      size="small"
                      type={screenshotMode ? "primary" : "default"}
                      onClick={() => setScreenshotMode(!screenshotMode)}
                    >
                      拍照助手
                    </Button>
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
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 10,
                }}
              >
                {PLATFORM_CATALOG.map((m) => {
                  const cfg = platforms[m.name]?.enabled
                    ? platforms[m.name]
                    : null;
                  return (
                    <div
                      key={m.name}
                      onClick={() => togglePlatform(m.name)}
                      style={{
                        border: `1px solid ${cfg ? "var(--brand-blue)" : "var(--border-default)"}`,
                        borderRadius: 8,
                        padding: 12,
                        cursor: "pointer",
                        background: cfg ? "#eff6ff" : "#fff",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 6,
                        transition: "all 0.15s",
                      }}
                    >
                      <div
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: "50%",
                          background: m.bg,
                          color: m.fg,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontWeight: 600,
                          fontSize: 14,
                        }}
                      >
                        {m.logo}
                      </div>
                      <div
                        style={{
                          fontSize: 13,
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
                          fontSize: 12,
                          color:
                            cfg?.delivery_mode === "mobile"
                              ? "var(--brand-orange)"
                              : "var(--text-tertiary)",
                          padding: "2px 8px",
                          border: `1px solid ${cfg?.delivery_mode === "mobile" ? "var(--brand-orange)" : "var(--border-default)"}`,
                          borderRadius: 4,
                          cursor: "pointer",
                        }}
                      >
                        {cfg?.delivery_mode === "mobile" ? "移动版" : "网页版"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* ===== middle section: 2-col body ===== */}
        <div
          style={{
            background: "#fff",
            borderRadius: 8,
            padding: 24,
            display: "grid",
            gridTemplateColumns: "2fr 1fr",
            gap: 24,
          }}
        >
          {/* Left column: tags + questions */}
          <div>
            {/* 竞品品牌 */}
            <div style={{ marginBottom: 24 }}>
              <SectionHeader
                title="竞品品牌"
                extra={
                  <Button
                    size="small"
                    type="link"
                    icon={<PlusOutlined />}
                    onClick={addCompetitor}
                  >
                    新增竞品
                  </Button>
                }
              />
              <Space size={6} wrap style={{ marginBottom: 8 }}>
                {competitors.length === 0 ? (
                  <TagChip text="暂未添加" placeholder />
                ) : (
                  competitors.map((c) => (
                    <span
                      key={c.id}
                      onClick={() => setEditingCompetitor(c)}
                      style={{ cursor: "pointer" }}
                    >
                      <TagChip
                        text={c.name}
                        onRemove={() => removeCompetitor(c.id)}
                      />
                    </span>
                  ))
                )}
              </Space>
              <Input
                placeholder="输入竞品名称后回车新增"
                value={competitorDraft}
                onChange={(e) => setCompetitorDraft(e.target.value)}
                onPressEnter={addCompetitor}
                style={{ maxWidth: 320 }}
              />
            </div>

            {/* 商品品牌 */}
            <div style={{ marginBottom: 24 }}>
              <SectionHeader
                title="商品品牌"
                extra={
                  <Button
                    size="small"
                    type="link"
                    icon={<PlusOutlined />}
                    onClick={addProduct}
                  >
                    新增品牌
                  </Button>
                }
              />
              <Space size={6} wrap style={{ marginBottom: 8 }}>
                {productBrands.length === 0 ? (
                  <TagChip text="暂未添加" placeholder />
                ) : (
                  productBrands.map((b) => (
                    <TagChip
                      key={b}
                      text={b}
                      onRemove={() => setProductBrands(productBrands.filter((x) => x !== b))}
                    />
                  ))
                )}
              </Space>
              <Input
                placeholder="请输入商品品牌"
                value={productDraft}
                onChange={(e) => setProductDraft(e.target.value)}
                onPressEnter={addProduct}
                style={{ maxWidth: 320 }}
              />
            </div>

            {/* 核心词 */}
            <div style={{ marginBottom: 24 }}>
              <SectionHeader
                title="核心词"
                extra={
                  <Button
                    size="small"
                    type="link"
                    icon={<PlusOutlined />}
                    onClick={addKeyword}
                  >
                    新增关键词
                  </Button>
                }
              />
              <Space size={6} wrap style={{ marginBottom: 8 }}>
                {keywords.length === 0 ? (
                  <TagChip text="请输入核心词" placeholder />
                ) : (
                  keywords.map((k) => (
                    <TagChip
                      key={k}
                      text={k}
                      onRemove={() => setKeywords(keywords.filter((x) => x !== k))}
                    />
                  ))
                )}
              </Space>
              <Input
                placeholder="输入关键词后回车新增"
                value={keywordDraft}
                onChange={(e) => setKeywordDraft(e.target.value)}
                onPressEnter={addKeyword}
                style={{ maxWidth: 320 }}
              />
            </div>

            {/* 监控问题 */}
            <div>
              <SectionHeader title="监控问题" required />
              <Input.TextArea
                placeholder={
                  "输入要监控的问题，每行一个问题\n例如：\n哪个智能客服系统最好用？\nAI智能和人工客服哪个效果更好？\n如何提升客服效率？"
                }
                value={questions}
                onChange={(e) => setQuestions(e.target.value)}
                rows={10}
                style={{ fontSize: 14 }}
              />
              <div
                style={{
                  fontSize: 12,
                  color: "var(--text-tertiary)",
                  marginTop: 8,
                  textAlign: "right",
                }}
              >
                已输入 {questions.split("\n").filter((s) => s.trim()).length} 个问题
              </div>
            </div>
          </div>

          {/* Right column: settings panel */}
          <div>
            <div
              style={{
                background: "#fafafa",
                borderRadius: 8,
                padding: 20,
              }}
            >
              <Button
                type="primary"
                block
                size="large"
                onClick={saveDraft}
                style={{
                  background: "var(--brand-blue)",
                  borderColor: "var(--brand-blue)",
                  marginBottom: 20,
                  fontWeight: 500,
                }}
              >
                保存
              </Button>

              {/* 循环频次 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginBottom: 8 }}>
                  循环频次
                </div>
                <Segmented
                  block
                  value={frequency}
                  onChange={(v) => setFrequency(v as "daily" | "once")}
                  options={[
                    { label: "每日重复", value: "daily" },
                    { label: "单次执行", value: "once" },
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
                    min={1}
                    max={30}
                    value={dayInterval}
                    onChange={(v) => setDayInterval(Number(v ?? 1))}
                    style={{ width: 80 }}
                    disabled={frequency === "once"}
                  />
                  <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>天 / 次</span>
                </div>
              </div>

              {/* 提问位置 */}
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
                  />
                )}
              </Field>

              {/* 情感倾向 */}
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

              {/* 排名设置 */}
              <Field
                label="排名设置"
                extra={
                  <a style={{ fontSize: 12, color: "var(--brand-blue)" }}>+ 退出客户</a>
                }
              >
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

              {/* 区域设置 */}
              <Field label="区域设置">
                <Select
                  placeholder="请选择区域"
                  options={[
                    { value: "national", label: "全国" },
                    { value: "north", label: "华北" },
                    { value: "east", label: "华东" },
                    { value: "south", label: "华南" },
                    { value: "northwest", label: "西北" },
                  ]}
                  style={{ width: "100%" }}
                />
              </Field>

              <Alert
                type="info"
                showIcon
                icon={<InfoCircleOutlined />}
                message="修改后保存即可生效。下次调度时间按当前频次计算。"
                style={{ marginTop: 16, fontSize: 12 }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ===== bottom action bar ===== */}
      <div
        style={{
          position: "fixed",
          bottom: 0,
          left: 220,
          right: 0,
          background: "#f5f6f8",
          borderTop: "1px solid var(--border-light)",
          padding: "12px 32px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-secondary)" }}>
          <span>预计费用:</span>
          <span style={{ fontSize: 16, fontWeight: 600, color: "var(--brand-blue)" }}>
            ¥0.00
          </span>
          <span style={{ color: "var(--text-tertiary)" }}>
            / 次 · {estimateCost} 个子任务
          </span>
          <Tooltip title="按当前问题 × 模型 计算,实际费用以远端 API 报价为准">
            <InfoCircleOutlined style={{ color: "var(--text-tertiary)", marginLeft: 4 }} />
          </Tooltip>
        </div>
        <Space size={12}>
          <Button onClick={() => navigate("/admin/projects")}>取消</Button>
          <Button onClick={saveDraft}>
            保存草稿 ({estimateCost})
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={saveAndRun}
            style={{
              background: "var(--brand-blue)",
              borderColor: "var(--brand-blue)",
            }}
          >
            保存并立即执行
          </Button>
        </Space>
      </div>

      {/* ===== edit competitor modal ===== */}
      <Modal
        open={editingCompetitor !== null}
        title="编辑竞品"
        okText="保存"
        cancelText="取消"
        onCancel={() => setEditingCompetitor(null)}
        onOk={async () => {
          if (!editingCompetitor) return;
          await saveCompetitor(editingCompetitor, editingCompetitor.name);
        }}
        destroyOnClose
      >
        {editingCompetitor && (
          <Input
            value={editingCompetitor.name}
            onChange={(e) =>
              setEditingCompetitor({ ...editingCompetitor, name: e.target.value })
            }
          />
        )}
      </Modal>
    </div>
  );
}

function Field(props: {
  label: string;
  extra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
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