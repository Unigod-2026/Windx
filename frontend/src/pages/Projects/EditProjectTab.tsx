import {
  Anchor,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  createCompetitor,
  deleteCompetitor,
  getProject,
  listCompetitors,
  putPlatforms,
  putPrompts,
  putWeeklySchedule,
  updateCompetitor,
  updateProject,
  type CompetitorOrigin,
  type CompetitorOut,
  type CompetitorPayload,
  type CompetitorStatus,
  type ProjectDetailOut,
  type ProjectPlatform,
  type PromptInPayload,
  type WizardDay,
} from "../../api/projects";
import { WIZARD_MODELS, type WizardModelOption } from "./wizardConfig";

interface Props {
  projectId: number;
}

const labelStyle: CSSProperties = {
  display: "block",
  marginBottom: 4,
  fontSize: 14,
  fontWeight: 500,
};

// Select mode="tags" can emit non-string entries; drop them before comparing.
const normalizeAliases = (a: string[] | null | undefined) =>
  (a ?? []).filter((x): x is string => typeof x === "string");

// Apply at: initial useState seed, both sides of dirty comparison, the
// putPrompts payload. Trim prevents accidental " " vs "" diffs.
const normalizePrompts = (ps: PromptInPayload[]) =>
  ps.map((p) => ({
    prompt: (p.prompt ?? "").trim(),
    category: p.category ?? null,
    status: p.status ?? "monitoring",
  }));

const PROMPT_LIMIT = 50;
const LIMIT_WARNING = `已达上限 ${PROMPT_LIMIT} 个`;

async function runSave(
  setSaving: (b: boolean) => void,
  successMsg: string,
  fn: () => Promise<unknown>,
  onSaved: () => void,
) {
  setSaving(true);
  try {
    await fn();
    message.success(successMsg);
    onSaved();
  } catch (e) {
    message.error((e as Error).message || "保存失败");
  } finally {
    setSaving(false);
  }
}

type FilterTab = "all" | "manual" | "auto_discovered";

const ORIGIN_LABELS: Record<CompetitorOrigin, { text: string; color: string }> = {
  manual: { text: "手动添加", color: "blue" },
  auto_discovered: { text: "Agent 发现", color: "purple" },
};

const STATUS_LABELS: Record<CompetitorStatus, { text: string; color: string }> = {
  confirmed: { text: "已确认", color: "green" },
  pending: { text: "待确认", color: "orange" },
  dismissed: { text: "已忽略", color: "default" },
};

function BrandSection({
  detail,
  onSaved,
}: {
  detail: ProjectDetailOut;
  onSaved: () => void;
}) {
  const [brand, setBrand] = useState(detail.brand ?? "");
  const [aliases, setAliases] = useState<string[]>(
    normalizeAliases(detail.aliases),
  );
  const [saving, setSaving] = useState(false);
  const dirty =
    brand !== (detail.brand ?? "") ||
    JSON.stringify(normalizeAliases(aliases)) !==
      JSON.stringify(normalizeAliases(detail.aliases));

  const save = () =>
    runSave(setSaving, "已保存品牌信息", async () => {
      await updateProject(detail.id, {
        brand,
        aliases: normalizeAliases(aliases),
      });
    }, onSaved);

  return (
    <Card
      id="brand"
      title="① 品牌信息"
      extra={
        <Button
          type="primary"
          onClick={save}
          loading={saving}
          disabled={!dirty || saving}
        >
          保存
        </Button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <label style={labelStyle}>
            品牌名<span style={{ color: "#ff4d4f" }}> *</span>
          </label>
          <Input
            value={brand}
            onChange={(e) => setBrand(e.target.value)}
            placeholder="如:薇诺娜"
          />
        </div>
        <div>
          <label style={labelStyle}>别名</label>
          <Select
            mode="tags"
            style={{ width: "100%" }}
            value={aliases}
            onChange={(next: string[]) => setAliases(normalizeAliases(next))}
            placeholder="输入后回车添加"
            tokenSeparators={[","]}
          />
        </div>
      </div>
    </Card>
  );
}

function QuestionsSection({
  detail,
  onSaved,
}: {
  detail: ProjectDetailOut;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<PromptInPayload[]>(
    normalizePrompts(
      detail.prompts.map((p) => ({
        prompt: p.prompt,
        category: p.category ?? null,
        status: p.status,
      })),
    ),
  );
  const [bulk, setBulk] = useState("");
  const [saving, setSaving] = useState(false);

  const serverPrompts = normalizePrompts(
    detail.prompts.map((p) => ({
      prompt: p.prompt,
      category: p.category ?? null,
      status: p.status,
    })),
  );
  const dirty = JSON.stringify(draft) !== JSON.stringify(serverPrompts);

  const addBulk = () => {
    const lines = bulk
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (lines.length === 0) return;
    const room = PROMPT_LIMIT - draft.length;
    if (room <= 0) {
      message.warning(LIMIT_WARNING);
      return;
    }
    const accepting = lines.slice(0, room);
    setDraft([
      ...draft,
      ...accepting.map((text) => ({
        prompt: text,
        category: null,
        status: "monitoring" as const,
      })),
    ]);
    if (accepting.length < lines.length) {
      message.warning(LIMIT_WARNING);
    }
    setBulk("");
  };

  const save = () =>
    runSave(setSaving, "已保存监控问题", async () => {
      await putPrompts(detail.id, normalizePrompts(draft));
    }, onSaved);

  const updateRow = (
    idx: number,
    patch: Partial<PromptInPayload>,
  ) => {
    setDraft(draft.map((d, i) => (i === idx ? { ...d, ...patch } : d)));
  };

  const removeRow = (idx: number) => {
    Modal.confirm({
      title: "删除问题",
      content: `确认删除「${draft[idx].prompt}」?`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => setDraft(draft.filter((_, i) => i !== idx)),
    });
  };

  return (
    <Card
      id="questions"
      title={`② 监控问题 (${draft.length} / ${PROMPT_LIMIT})`}
      extra={
        <Button
          type="primary"
          onClick={save}
          loading={saving}
          disabled={!dirty || saving}
        >
          保存
        </Button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Input.TextArea
          rows={4}
          value={bulk}
          onChange={(e) => setBulk(e.target.value)}
          placeholder="每行一个问题,粘贴后点击「添加问题」"
        />
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            type="primary"
            onClick={addBulk}
            disabled={!bulk.trim()}
          >
            添加问题
          </Button>
          <Button
            type="text"
            onClick={() => setDraft([])}
            disabled={draft.length === 0}
          >
            清空
          </Button>
        </div>
        <Table
          rowKey={(_r, idx) => String(idx)}
          size="small"
          dataSource={draft}
          pagination={false}
          columns={[
            {
              title: "问题",
              dataIndex: "prompt",
              width: "40%",
              render: (text, _r, idx) => (
                <Input
                  value={text}
                  onChange={(e) =>
                    updateRow(idx!, { prompt: e.target.value })
                  }
                />
              ),
            },
            {
              title: "分类",
              dataIndex: "category",
              width: 160,
              render: (v, _r, idx) => (
                <Select
                  allowClear
                  value={v ?? undefined}
                  onChange={(nv) =>
                    updateRow(idx!, { category: nv ?? null })
                  }
                  options={(detail.category_taxonomy ?? []).map((c) => ({
                    value: c,
                    label: c,
                  }))}
                  placeholder="选择"
                  style={{ width: "100%" }}
                />
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 120,
              render: (v, _r, idx) => (
                <Select
                  value={v}
                  onChange={(nv: PromptInPayload["status"]) =>
                    updateRow(idx!, { status: nv })
                  }
                  options={[
                    { value: "monitoring", label: "监控中" },
                    { value: "paused", label: "已暂停" },
                    { value: "archived", label: "已归档" },
                  ]}
                  style={{ width: "100%" }}
                />
              ),
            },
            {
              title: "操作",
              width: 80,
              render: (_v, _r, idx) => (
                <Button
                  type="text"
                  danger
                  onClick={() => removeRow(idx!)}
                >
                  删除
                </Button>
              ),
            },
          ]}
        />
      </div>
    </Card>
  );
}

const EMPTY_DRAFT: CompetitorPayload = {
  name: "",
  note: null,
  aliases: [],
  origin: "manual",
  status: "confirmed",
};

function CompetitorsSection({
  projectId,
}: {
  projectId: number;
}) {
  const [items, setItems] = useState<CompetitorOut[]>([]);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [editOpen, setEditOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<CompetitorPayload>(EMPTY_DRAFT);

  const reload = async () => {
    try {
      const data = await listCompetitors(projectId);
      setItems(data.items);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const filtered = useMemo(() => {
    if (filter === "all") return items;
    return items.filter((c) => c.origin === filter);
  }, [items, filter]);

  const counts = useMemo(() => {
    const total = items.length;
    const manual = items.filter((c) => c.origin === "manual").length;
    const auto = items.filter((c) => c.origin === "auto_discovered").length;
    return { total, manual, auto };
  }, [items]);

  const openCreate = () => {
    setEditingId(null);
    setDraft({ ...EMPTY_DRAFT });
    setEditOpen(true);
  };

  const openEdit = (c: CompetitorOut) => {
    setEditingId(c.id);
    setDraft({
      name: c.name,
      note: c.note,
      aliases: c.aliases ?? [],
      origin: c.origin,
      status: c.status,
    });
    setEditOpen(true);
  };

  const closeModal = () => {
    setEditOpen(false);
    setEditingId(null);
  };

  const onSave = async () => {
    const name = draft.name.trim();
    if (!name) {
      message.warning("请输入品牌名");
      return;
    }
    const payload: CompetitorPayload = {
      name,
      note: draft.note?.trim() || null,
      aliases: draft.aliases ?? [],
      origin: draft.origin ?? "manual",
      status: draft.status ?? "confirmed",
    };
    try {
      if (editingId === null) {
        await createCompetitor(projectId, payload);
        message.success("已新增");
      } else {
        await updateCompetitor(projectId, editingId, payload);
        message.success("已保存");
      }
      closeModal();
      await reload();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const onDelete = (c: CompetitorOut) => {
    Modal.confirm({
      title: "删除竞品",
      content: `确认删除「${c.name}」?删除后不再监控此品牌。`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteCompetitor(projectId, c.id);
          setItems((prev) => prev.filter((x) => x.id !== c.id));
          message.success("已删除");
        } catch (err) {
          message.error((err as Error).message || "删除失败");
        }
      },
    });
  };

  const confirmPending = async (c: CompetitorOut) => {
    try {
      await updateCompetitor(projectId, c.id, {
        ...c,
        status: "confirmed",
        origin: "manual",
      });
      setItems((prev) =>
        prev.map((x) =>
          x.id === c.id ? { ...x, status: "confirmed", origin: "manual" } : x,
        ),
      );
      message.success("已确认");
    } catch (err) {
      message.error((err as Error).message || "操作失败");
    }
  };

  const dismissPending = async (c: CompetitorOut) => {
    try {
      await updateCompetitor(projectId, c.id, {
        ...c,
        status: "dismissed",
      });
      setItems((prev) =>
        prev.map((x) =>
          x.id === c.id ? { ...x, status: "dismissed" } : x,
        ),
      );
      message.success("已忽略");
    } catch (err) {
      message.error((err as Error).message || "操作失败");
    }
  };

  const onAliasesChange = (next: string[]) => {
    const cleaned = (next ?? []).filter(
      (x): x is string => typeof x === "string",
    );
    const seen = new Set<string>();
    const deduped: string[] = [];
    let dropped = 0;
    for (const v of cleaned) {
      const current = v;
      if (seen.has(current)) {
        dropped++;
        continue;
      }
      seen.add(current);
      deduped.push(current);
    }
    if (dropped > 0) {
      message.warning(`已忽略 ${dropped} 个重复别名`);
    }
    setDraft({ ...draft, aliases: deduped });
  };

  const columns: ColumnsType<CompetitorOut> = [
    {
      title: "品牌名称",
      dataIndex: "name",
      render: (name: string, record) => (
        <div>
          <div style={{ fontWeight: 500 }}>{name}</div>
          {record.note && (
            <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
              {record.note}
            </div>
          )}
          {record.aliases && record.aliases.length > 0 && (
            <div style={{ marginTop: 4 }}>
              {record.aliases.slice(0, 3).map((a) => (
                <Tag key={a} style={{ margin: 0 }}>
                  {a}
                </Tag>
              ))}
              {record.aliases.length > 3 && (
                <Tag style={{ margin: 0 }}>+{record.aliases.length - 3}</Tag>
              )}
            </div>
          )}
        </div>
      ),
    },
    {
      title: "添加方式",
      dataIndex: "origin",
      width: 110,
      render: (origin: CompetitorOrigin) => (
        <Tag color={ORIGIN_LABELS[origin].color}>{ORIGIN_LABELS[origin].text}</Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (status: CompetitorStatus) => (
        <Tag color={STATUS_LABELS[status].color}>{STATUS_LABELS[status].text}</Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 200,
      render: (_v, record) => (
        <Space size={4}>
          {record.status === "pending" && (
            <>
              <Tooltip title="确认纳入监控">
                <Button
                  type="text"
                  size="small"
                  icon={<CheckCircleOutlined style={{ color: "#16a34a" }} />}
                  onClick={() => confirmPending(record)}
                />
              </Tooltip>
              <Tooltip title="忽略">
                <Button
                  type="text"
                  size="small"
                  icon={<CloseCircleOutlined style={{ color: "#6b7280" }} />}
                  onClick={() => dismissPending(record)}
                />
              </Tooltip>
            </>
          )}
          <Tooltip title="编辑">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEdit(record)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => onDelete(record)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <Card
      id="competitors"
      title="③ 竞品"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreate}
          style={{ background: "var(--brand-blue)", borderColor: "var(--brand-blue)" }}
        >
          新增竞品
        </Button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as FilterTab)}
          options={[
            { label: `全部 (${counts.total})`, value: "all" },
            { label: `手动 (${counts.manual})`, value: "manual" },
            { label: `Agent 发现 (${counts.auto})`, value: "auto_discovered" },
          ]}
        />
        {filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              filter === "all"
                ? "尚未配置竞品"
                : filter === "auto_discovered"
                ? "暂无 Agent 自动发现的竞品"
                : "暂无手动添加的竞品"
            }
            style={{ padding: 32 }}
          />
        ) : (
          <Table
            rowKey="id"
            size="middle"
            dataSource={filtered}
            columns={columns}
            pagination={false}
          />
        )}
      </div>

      <Modal
        open={editOpen}
        title={editingId === null ? "新增竞品" : "编辑竞品"}
        okText="保存"
        cancelText="取消"
        onCancel={closeModal}
        onOk={onSave}
        destroyOnHidden
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
          <div>
            <label style={labelStyle}>
              品牌名称<span style={{ color: "#ff4d4f" }}> *</span>
            </label>
            <Input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="例如:珂润 Curel"
            />
          </div>
          <div>
            <label style={labelStyle}>备注</label>
            <Input
              value={draft.note ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, note: e.target.value || null })
              }
              placeholder="选填,例如:品类 / 渠道 / 重点关注点"
            />
          </div>
          <div>
            <label style={labelStyle}>别名(用于 AI 回答中的同义召回)</label>
            <Select
              mode="tags"
              style={{ width: "100%" }}
              value={draft.aliases ?? []}
              onChange={onAliasesChange}
              placeholder="输入后回车添加"
              tokenSeparators={[","]}
            />
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>添加方式</label>
              <Select
                style={{ width: "100%" }}
                value={draft.origin ?? "manual"}
                onChange={(v) =>
                  setDraft({ ...draft, origin: v as CompetitorOrigin })
                }
                options={[
                  { value: "manual", label: "手动添加" },
                  { value: "auto_discovered", label: "Agent 发现" },
                ]}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>状态</label>
              <Select
                style={{ width: "100%" }}
                value={draft.status ?? "confirmed"}
                onChange={(v) =>
                  setDraft({ ...draft, status: v as CompetitorStatus })
                }
                options={[
                  { value: "confirmed", label: "已确认" },
                  { value: "pending", label: "待确认" },
                  { value: "dismissed", label: "已忽略" },
                ]}
              />
            </div>
          </div>
        </div>
      </Modal>
    </Card>
  );
}

function ModelsSection({
  detail,
  onSaved,
}: {
  detail: ProjectDetailOut;
  onSaved: () => void;
}) {
  // "enabled" = which base model codes have at least one web row in detail.platforms
  const initialEnabled = new Set(
    detail.platforms
      .filter((p) => p.delivery_mode === "web")
      .map((p) => p.platform),
  );
  // "mobile" = any platform row has delivery_mode=mobile
  const initialMobile = detail.platforms.some((p) => p.delivery_mode === "mobile");
  // "thinking" = any platform row has thinking_mode=true
  const initialThinking = detail.platforms.some((p) => p.thinking_mode);

  const [enabled, setEnabled] = useState<Set<string>>(initialEnabled);
  const [mobile, setMobile] = useState(initialMobile);
  const [thinking, setThinking] = useState(initialThinking);
  const [saving, setSaving] = useState(false);

  const dirty =
    enabled.size !== initialEnabled.size ||
    ![...enabled].every((v) => initialEnabled.has(v)) ||
    mobile !== initialMobile ||
    thinking !== initialThinking;

  const setMobileAndValidate = (next: boolean) => {
    if (next && !mobile) {
      // 勾选「移动端」前校验:已选模型中是否有无移动版的(Kimi / 蚂蚁阿福);
      // 有则阻断勾选并提示,避免下游写出 platform=kimi + DeliveryMode.MOBILE
      // 这种找不到对应 modelCode 的组合。
      const noMobile = WIZARD_MODELS.filter(
        (m) => enabled.has(m.value) && !m.hasMobile,
      );
      if (noMobile.length > 0) {
        message.error(
          `已选模型「${noMobile.map((m) => m.name).join("、")}」无移动端版本,无法监控移动端`,
        );
        return;
      }
    }
    setMobile(next);
  };

  const toggleModel = (m: WizardModelOption) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(m.value)) next.delete(m.value);
      else next.add(m.value);
      // 取消勾选时若 mobile 仍开启且该模型无移动版,不影响 — 已开启的 mobile 仅在用户主动打开时校验。
      return next;
    });
  };

  const buildPlatforms = (): ProjectPlatform[] => {
    const rows: ProjectPlatform[] = [];
    for (const m of WIZARD_MODELS) {
      if (!enabled.has(m.value)) continue;
      const codes = mobile && m.hasMobile ? [m.value, m.mobileCode!] : [m.value];
      const modes = thinking ? [false, true] : [false];
      for (const code of codes) {
        for (const t of modes) {
          rows.push({
            // ``platform`` 是 UI 用的逻辑模型名,永远用 value;远端 API
            // 代码放 ``platform_code``。原先 ``platform: code`` 把 API
            // code 写到 platform 列,mobile 行就成了 ``qianwen_mobile``,
            // 污染分组语义。
            platform: m.value,
            platform_code: code,
            mode: t ? "reasoning" : "standard",
            delivery_mode: code === m.mobileCode ? "mobile" : "web",
            thinking_mode: t,
            screenshot: 0,
          });
        }
      }
    }
    return rows;
  };

  const save = () =>
    runSave(setSaving, "已保存监控模型", async () => {
      await putPlatforms(detail.id, buildPlatforms());
    }, onSaved);

  return (
    <Card
      id="models"
      title={`④ 监控模型 (${enabled.size} / ${WIZARD_MODELS.length})`}
      extra={
        <Button
          type="primary"
          onClick={save}
          loading={saving}
          disabled={!dirty || saving}
        >
          保存
        </Button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <label style={labelStyle}>终端</label>
            <Segmented
              value={mobile ? "mobile" : "pc"}
              onChange={(v) => setMobileAndValidate(v === "mobile")}
              options={[
                { value: "pc", label: "PC 端" },
                { value: "mobile", label: "移动端" },
              ]}
            />
          </div>
          <div>
            <label style={labelStyle}>模式</label>
            <Segmented
              value={thinking ? "think" : "fast"}
              onChange={(v) => setThinking(v === "think")}
              options={[
                { value: "fast", label: "快速模式" },
                { value: "think", label: "思考模式" },
              ]}
            />
          </div>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(7, 1fr)",
            gap: 12,
          }}
        >
          {WIZARD_MODELS.map((m) => {
            const on = enabled.has(m.value);
            return (
              <Card
                key={m.value}
                size="small"
                hoverable
                role="button"
                tabIndex={0}
                aria-pressed={on}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleModel(m);
                  }
                }}
                onClick={() => toggleModel(m)}
                style={{
                  cursor: "pointer",
                  borderColor: on ? m.color : undefined,
                  boxShadow: on ? `0 0 0 2px ${m.color}` : undefined,
                }}
                styles={{ body: { padding: 12 } }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    minHeight: 32,
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: m.color,
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontWeight: 500 }}>{m.name}</span>
                  {on && (
                    <span style={{ marginLeft: "auto", color: m.color }}>
                      ✓
                    </span>
                  )}
                </div>
                {!m.hasMobile && (
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--text-tertiary)",
                      marginTop: 4,
                    }}
                  >
                    无移动端
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function MonitorSection({
  detail,
  onSaved,
}: {
  detail: ProjectDetailOut;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(detail.schedule_enabled);
  // Per-mode schedule map. ``fast`` / ``think`` are independent so a
  // project can monitor its 快速平台 on weekdays and its 思考平台 only
  // on weekends. ``null`` means "this mode is not scheduled".
  const initialSchedule: Partial<
    Record<"fast" | "think", { freq: "w1" | "w2" | "wn"; days: WizardDay[] } | null>
  > = {
    fast: detail.monitor_schedule?.fast
      ? {
          freq: detail.monitor_schedule.fast.freq,
          days: [...detail.monitor_schedule.fast.days],
        }
      : null,
    think: detail.monitor_schedule?.think
      ? {
          freq: detail.monitor_schedule.think.freq,
          days: [...detail.monitor_schedule.think.days],
        }
      : null,
  };
  const [schedules, setSchedules] = useState(initialSchedule);
  const [saving, setSaving] = useState(false);

  // 终端 / 模式 由④监控模型决定,这里只展示不可编辑的 Segmented,
  // 移动端有任一 platform 行 / 思考模式有任一 thinking_mode=true 即可。
  const mobileOn = detail.platforms.some((p) => p.delivery_mode === "mobile");
  const thinkingOn = detail.platforms.some((p) => p.thinking_mode);

  const updateMode = (
    modeKey: "fast" | "think",
    next: { freq: "w1" | "w2" | "wn"; days: WizardDay[] } | null,
  ) => setSchedules((prev) => ({ ...prev, [modeKey]: next }));

  const dirty =
    enabled !== detail.schedule_enabled ||
    schedules.fast?.freq !== (detail.monitor_schedule?.fast?.freq ?? null) ||
    JSON.stringify(schedules.fast?.days ?? []) !==
      JSON.stringify(detail.monitor_schedule?.fast?.days ?? []) ||
    schedules.think?.freq !== (detail.monitor_schedule?.think?.freq ?? null) ||
    JSON.stringify(schedules.think?.days ?? []) !==
      JSON.stringify(detail.monitor_schedule?.think?.days ?? []);

  const save = () =>
    runSave(setSaving, "已保存监控配置", async () => {
      await putWeeklySchedule(detail.id, {
        schedule_enabled: enabled,
        monitor_schedule: schedules,
      });
    }, onSaved);

  return (
    <Card
      id="monitor"
      title="⑤ 监控配置"
      extra={
        <Space>
          <span style={{ color: "var(--text-secondary)" }}>启用调度</span>
          <Switch checked={enabled} onChange={setEnabled} />
          <Button
            type="primary"
            onClick={save}
            loading={saving}
            disabled={!dirty || saving}
          >
            保存
          </Button>
        </Space>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          <div>
            <label style={labelStyle}>终端(由监控模型决定,只读)</label>
            <Segmented
              value={mobileOn ? "mobile" : "pc"}
              disabled
              options={[
                { value: "pc", label: "PC 端" },
                { value: "mobile", label: "移动端" },
              ]}
            />
          </div>
          <div>
            <label style={labelStyle}>模式(由监控模型决定,只读)</label>
            <Segmented
              value={thinkingOn ? "think" : "fast"}
              disabled
              options={[
                { value: "fast", label: "快速模式" },
                { value: "think", label: "思考模式" },
              ]}
            />
          </div>
        </div>
        <div
          style={{
            fontSize: 12,
            color: "var(--text-tertiary)",
            marginTop: -4,
          }}
        >
          每个模式可以独立配置监控频率;关闭调度的模式不会出现在 cron 里。
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 16,
          }}
        >
          {(["fast", "think"] as const).map((modeKey) => (
            <MonitorModeCard
              key={modeKey}
              modeKey={modeKey}
              entry={schedules[modeKey] ?? null}
              onChange={(next) => updateMode(modeKey, next)}
            />
          ))}
        </div>
      </div>
    </Card>
  );
}

/** 单个模式的 freq + days 编辑卡片,AntD inline 版。 */
function MonitorModeCard(props: {
  modeKey: "fast" | "think";
  entry: { freq: "w1" | "w2" | "wn"; days: WizardDay[] } | null;
  onChange: (
    next: { freq: "w1" | "w2" | "wn"; days: WizardDay[] } | null,
  ) => void;
}) {
  const { modeKey, entry, onChange } = props;
  const modeLabel = modeKey === "fast" ? "快速" : "思考";
  if (!entry) {
    return (
      <div
        style={{
          padding: 16,
          border: "1px dashed var(--border-default)",
          borderRadius: 8,
          background: "#fafafa",
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>
          {modeLabel}模式调度
        </div>
        <div
          style={{
            fontSize: 12,
            color: "var(--text-tertiary)",
            marginBottom: 12,
          }}
        >
          未启用 —— 不会在 cron 中触发
        </div>
        <Button onClick={() => onChange({ freq: "w1", days: [] })}>
          启用{modeLabel}模式调度
        </Button>
      </div>
    );
  }
  const maxDays = entry.freq === "w1" ? 1 : entry.freq === "w2" ? 2 : 7;
  return (
    <div
      style={{
        padding: 16,
        border: "1px solid var(--border-default)",
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 500 }}>
          {modeLabel}模式调度
        </span>
        <Button
          type="link"
          size="small"
          onClick={() => onChange(null)}
          style={{ padding: 0 }}
        >
          关闭调度
        </Button>
      </div>
      <div>
        <label style={labelStyle}>采集频率</label>
        <div
          style={{
            display: "flex",
            flexWrap: "nowrap",
            gap: 6,
            width: "100%",
          }}
        >
          {(
            [
              { value: "w1", label: "一周一次", hint: "每周固定 1 天采集" },
              { value: "w2", label: "一周两次", hint: "每周固定 2 天采集" },
              { value: "wn", label: "一周多次", hint: "每周 1~7 天自由勾选,最多 7 次" },
            ] as const
          ).map((opt) => {
            const active = entry.freq === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() =>
                  onChange({
                    freq: opt.value as "w1" | "w2" | "wn",
                    days: [] as WizardDay[],
                  })
                }
                style={{
                  flex: "1 1 0",
                  minWidth: 0,
                  width: 0,
                  padding: "6px 4px",
                  border: `1px solid ${active ? "var(--brand-blue)" : "var(--border-default)"}`,
                  borderRadius: 6,
                  background: active ? "#eff6ff" : "#fff",
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 1,
                  transition: "all 0.15s",
                }}
              >
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 500,
                    color: active ? "var(--brand-blue)" : "var(--text-primary)",
                  }}
                >
                  {opt.label}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--text-tertiary)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: "100%",
                  }}
                >
                  {opt.hint}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div>
        <label style={labelStyle}>采集日期(最多 {maxDays} 天)</label>
        <Checkbox.Group
          value={entry.days}
          onChange={(v) => {
            const next = v as WizardDay[];
            if (next.length > maxDays) {
              message.warning(`最多只能选 ${maxDays} 天`);
            }
            onChange({ freq: entry.freq, days: next.slice(0, maxDays) });
          }}
          options={[
            { value: "1", label: "周一" },
            { value: "2", label: "周二" },
            { value: "3", label: "周三" },
            { value: "4", label: "周四" },
            { value: "5", label: "周五" },
            { value: "6", label: "周六" },
            { value: "7", label: "周日" },
          ]}
        />
      </div>
    </div>
  );
}

export default function EditProjectTab({ projectId }: Props) {
  const [detail, setDetail] = useState<ProjectDetailOut | null>(null);

  const reload = () => {
    getProject(projectId)
      .then(setDetail)
      .catch((err) => {
        // null on error is OK: the Card sections below won't render until detail
        // loads, and we already showed the error toast. Keeps the failure mode
        // predictable instead of leaving a stale detail on screen.
        message.error((err as Error).message || "项目加载失败");
        setDetail(null);
      });
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (!detail) return <Card loading />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card styles={{ body: { padding: "12px 16px" } }}>
        <Anchor
          items={[
            { key: "brand", href: "#brand", title: "品牌信息" },
            { key: "questions", href: "#questions", title: "监控问题" },
            { key: "competitors", href: "#competitors", title: "竞品" },
            { key: "models", href: "#models", title: "监控模型" },
            { key: "monitor", href: "#monitor", title: "监控配置" },
          ]}
        />
      </Card>

      <BrandSection detail={detail} onSaved={reload} />
      <QuestionsSection detail={detail} onSaved={reload} />
      <CompetitorsSection projectId={projectId} />
      <ModelsSection detail={detail} onSaved={reload} />
      <MonitorSection detail={detail} onSaved={reload} />
    </div>
  );
}
