import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  RocketOutlined,
} from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import dayjs from "dayjs";
import {
  createCompetitor,
  deleteCompetitor,
  deleteProject,
  getProject,
  getSchedule,
  listCompetitors,
  listRuns,
  putKeywords,
  putPlatforms,
  putPrompts,
  toggleSchedule,
  triggerRun,
  updateCompetitor,
  updateProject,
  updateSchedule,
  type CompetitorOut,
  type CompetitorPayload,
  type ProjectDetailOut,
  type ProjectPlatform,
  type ScheduleRunOut,
  type SlotOut,
} from "../../api/projects";
import { listCustomers, type Customer } from "../../api/customers";

const { Title } = Typography;

type DeliveryMode = "web" | "mobile";
type RegionStrategy = "fixed" | "national_random";

const PLATFORM_CATALOG: string[] = [
  "deepseek",
  "doubao-pro",
  "kimi",
  "文心一言",
  "通义千问",
  "智谱 GLM",
  "混元",
  "Qwen-Max",
  "ERNIE-4.0",
];

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  success: { color: "green", text: "成功" },
  failed: { color: "red", text: "失败" },
  partial_completed: { color: "warning", text: "部分完成" },
  skipped: { color: "default", text: "已跳过" },
  queued: { color: "processing", text: "排队中" },
  running: { color: "orange", text: "执行中" },
};

function StatusTag({ status }: { status: string }) {
  const cfg = STATUS_TAG[status] ?? { color: "default", text: status };
  return <Tag color={cfg.color}>{cfg.text}</Tag>;
}

function formatTime(v: string | null | undefined) {
  return v ? dayjs(v).format("YYYY-MM-DD HH:mm") : "—";
}

function formatSlot(s: SlotOut | undefined) {
  if (!s) return "—";
  return `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
}

interface PromptsTabProps {
  projectId: number;
  prompts: string[];
  onSaved: () => void;
}

function PromptsTab({ projectId, prompts, onSaved }: PromptsTabProps) {
  const [list, setList] = useState<string[]>(prompts);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setList(prompts);
  }, [prompts]);

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (list.includes(v)) {
      message.warning("问题已存在");
      return;
    }
    setList([...list, v]);
    setDraft("");
  };

  const remove = (idx: number) => {
    setList(list.filter((_, i) => i !== idx));
  };

  const update = (idx: number, v: string) => {
    setList(list.map((p, i) => (i === idx ? v : p)));
  };

  const save = async () => {
    setSaving(true);
    try {
      const cleaned = list.map((s) => s.trim()).filter(Boolean);
      await putPrompts(projectId, cleaned);
      message.success("已保存");
      onSaved();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 12, display: "flex", gap: 8 }}>
        <Input
          placeholder="输入新问题,回车添加"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onPressEnter={add}
          style={{ maxWidth: 480 }}
        />
        <Button icon={<PlusOutlined />} onClick={add}>
          新增问题
        </Button>
      </div>
      <Table<string>
        rowKey={(_, i) => String(i)}
        dataSource={list}
        pagination={false}
        columns={[
          {
            title: "序号",
            key: "idx",
            width: 70,
            render: (_, __, i) => (
              <span style={{ color: "var(--text-tertiary)" }}>{i + 1}</span>
            ),
          },
          {
            title: "问题内容",
            key: "value",
            render: (_, __, i) => (
              <Input
                value={list[i]}
                onChange={(e) => update(i, e.target.value)}
                placeholder="例如:介绍 XX 品牌的主要优势"
              />
            ),
          },
          {
            title: "操作",
            key: "act",
            width: 80,
            render: (_, __, i) => (
              <Button
                size="small"
                type="link"
                danger
                icon={<DeleteOutlined />}
                onClick={() => remove(i)}
              >
                删除
              </Button>
            ),
          },
        ]}
      />
      <div
        style={{
          marginTop: 16,
          display: "flex",
          justifyContent: "flex-end",
        }}
      >
        <Button type="primary" loading={saving} onClick={save}>
          保存
        </Button>
      </div>
    </div>
  );
}

interface PlatformsTabProps {
  projectId: number;
  platforms: ProjectPlatform[];
  onSaved: () => void;
}

function PlatformsTab({ projectId, platforms, onSaved }: PlatformsTabProps) {
  // Per-platform config (需求文档 §3): delivery_mode + thinking_mode + screenshot.
  // Each platform card toggles inclusion + carries its own multi-dimensional config.
  const [enabled, setEnabled] = useState<Set<string>>(
    new Set(platforms.map((p) => p.platform)),
  );
  const [config, setConfig] = useState<
    Record<string, { delivery_mode: DeliveryMode; thinking_mode: boolean; screenshot: boolean }>
  >(() => {
    const init: Record<
      string,
      { delivery_mode: DeliveryMode; thinking_mode: boolean; screenshot: boolean }
    > = {};
    for (const p of platforms) {
      init[p.platform] = {
        delivery_mode: p.delivery_mode,
        thinking_mode: p.thinking_mode,
        screenshot: p.screenshot === 1,
      };
    }
    return init;
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setEnabled(new Set(platforms.map((p) => p.platform)));
    const init: Record<
      string,
      { delivery_mode: DeliveryMode; thinking_mode: boolean; screenshot: boolean }
    > = {};
    for (const p of platforms) {
      init[p.platform] = {
        delivery_mode: p.delivery_mode,
        thinking_mode: p.thinking_mode,
        screenshot: p.screenshot === 1,
      };
    }
    setConfig(init);
  }, [platforms]);

  const toggle = (p: string) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  };

  const updateConfig = (
    p: string,
    patch: Partial<{ delivery_mode: DeliveryMode; thinking_mode: boolean; screenshot: boolean }>,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [p]: { ...(prev[p] ?? { delivery_mode: "web", thinking_mode: false, screenshot: false }), ...patch },
    }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload: ProjectPlatform[] = Array.from(enabled).map((p, i) => {
        const c = config[p] ?? { delivery_mode: "web", thinking_mode: false, screenshot: false };
        return {
          platform: p,
          mode: c.delivery_mode,
          delivery_mode: c.delivery_mode,
          thinking_mode: c.thinking_mode,
          screenshot: c.screenshot ? 1 : 0,
          sort: i,
        };
      });
      await putPlatforms(projectId, payload);
      message.success("已保存");
      onSaved();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div
        style={{
          marginBottom: 16,
          padding: 12,
          background: "var(--bg-page)",
          borderRadius: 6,
          color: "var(--text-secondary)",
          fontSize: 13,
        }}
      >
        已选 <strong>{enabled.size}</strong> / {PLATFORM_CATALOG.length} 个模型。每个模型可独立设置投放端 (网页/移动端)、深度思考模式与是否截图,保存后下次执行生效。
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {PLATFORM_CATALOG.map((p) => {
          const on = enabled.has(p);
          const c = config[p] ?? { delivery_mode: "web", thinking_mode: false, screenshot: false };
          return (
            <div
              key={p}
              style={{
                border: `1px solid ${on ? "var(--brand-blue)" : "var(--border-light)"}`,
                borderRadius: 8,
                padding: 16,
                background: on ? "var(--brand-blue-50)" : "#fff",
                opacity: on ? 1 : 0.65,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 500,
                    color: on ? "var(--brand-blue)" : "var(--text-primary)",
                  }}
                >
                  {p}
                </div>
                <Switch
                  checked={on}
                  onChange={() => toggle(p)}
                  checkedChildren="启用"
                  unCheckedChildren="停用"
                  size="small"
                />
              </div>
              <div style={{ display: "grid", rowGap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--text-tertiary)", fontSize: 12, width: 70 }}>
                    投放端
                  </span>
                  <Radio.Group
                    size="small"
                    value={c.delivery_mode}
                    onChange={(e) => updateConfig(p, { delivery_mode: e.target.value })}
                    disabled={!on}
                  >
                    <Radio.Button value="web">网页</Radio.Button>
                    <Radio.Button value="mobile">移动端</Radio.Button>
                  </Radio.Group>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--text-tertiary)", fontSize: 12, width: 70 }}>
                    深度思考
                  </span>
                  <Switch
                    size="small"
                    checked={c.thinking_mode}
                    onChange={(v) => updateConfig(p, { thinking_mode: v })}
                    disabled={!on}
                  />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--text-tertiary)", fontSize: 12, width: 70 }}>
                    截图
                  </span>
                  <Switch
                    size="small"
                    checked={c.screenshot}
                    onChange={(v) => updateConfig(p, { screenshot: v })}
                    disabled={!on}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div
        style={{
          marginTop: 16,
          display: "flex",
          justifyContent: "flex-end",
        }}
      >
        <Button type="primary" loading={saving} onClick={save}>
          保存
        </Button>
      </div>
    </div>
  );
}

interface KeywordsTabProps {
  projectId: number;
  keywords: string[];
  onSaved: () => void;
}

function KeywordsTab({ projectId, keywords, onSaved }: KeywordsTabProps) {
  const [list, setList] = useState<string[]>(keywords);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setList(keywords);
  }, [keywords]);

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (list.includes(v)) {
      message.warning("关键词已存在");
      return;
    }
    setList([...list, v]);
    setDraft("");
  };

  const remove = (k: string) => {
    setList(list.filter((x) => x !== k));
  };

  const save = async () => {
    setSaving(true);
    try {
      const cleaned = list.map((s) => s.trim()).filter(Boolean);
      await putKeywords(projectId, cleaned);
      message.success("已保存");
      onSaved();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 12, display: "flex", gap: 8 }}>
        <Input
          placeholder="输入关键词,回车添加"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onPressEnter={add}
          style={{ maxWidth: 320 }}
        />
        <Button icon={<PlusOutlined />} onClick={add}>
          新增关键词
        </Button>
      </div>
      <div
        style={{
          padding: 16,
          background: "var(--bg-page)",
          borderRadius: 8,
          minHeight: 120,
        }}
      >
        {list.length === 0 ? (
          <span style={{ color: "var(--text-quaternary)" }}>暂无关键词</span>
        ) : (
          <Space wrap>
            {list.map((k) => (
              <Tag
                key={k}
                closable
                onClose={() => remove(k)}
                color="purple"
                style={{ padding: "4px 10px", fontSize: 13 }}
              >
                {k}
              </Tag>
            ))}
          </Space>
        )}
      </div>
      <div
        style={{
          marginTop: 16,
          display: "flex",
          justifyContent: "flex-end",
        }}
      >
        <Button type="primary" loading={saving} onClick={save}>
          保存
        </Button>
      </div>
    </div>
  );
}

interface CompetitorsTabProps {
  projectId: number;
  competitors: CompetitorOut[];
  onReload: () => void;
}

function CompetitorsTab({ projectId, competitors, onReload }: CompetitorsTabProps) {
  const [editing, setEditing] = useState<
    | { mode: "create"; initial: null }
    | { mode: "edit"; initial: CompetitorOut }
    | null
  >(null);

  const columns: ColumnsType<CompetitorOut> = [
    {
      title: "序号",
      key: "idx",
      width: 70,
      render: (_, __, i) => (
        <span style={{ color: "var(--text-tertiary)" }}>{i + 1}</span>
      ),
    },
    {
      title: "竞品名称",
      dataIndex: "name",
      render: (v: string) => <strong style={{ color: "var(--text-primary)" }}>{v}</strong>,
    },
    {
      title: "备注",
      dataIndex: "note",
      render: (v: string | null) =>
        v ? (
          <span style={{ color: "var(--text-secondary)" }}>{v}</span>
        ) : (
          <span style={{ color: "var(--text-quaternary)" }}>—</span>
        ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatTime(v),
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            icon={<EditOutlined />}
            onClick={() => setEditing({ mode: "edit", initial: record })}
          >
            编辑
          </Button>
          <Button
            size="small"
            type="link"
            danger
            icon={<DeleteOutlined />}
            onClick={() => {
              Modal.confirm({
                title: "确认删除?",
                content: `将删除竞品「${record.name}」`,
                okText: "删除",
                okButtonProps: { danger: true },
                cancelText: "取消",
                onOk: async () => {
                  try {
                    await deleteCompetitor(projectId, record.id);
                    message.success("已删除");
                    onReload();
                  } catch (err) {
                    message.error((err as Error).message || "删除失败");
                  }
                },
              });
            }}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div
        style={{
          marginBottom: 12,
          padding: 12,
          background: "var(--bg-page)",
          borderRadius: 6,
          color: "var(--text-secondary)",
          fontSize: 13,
        }}
      >
        监控项目下需要重点关注的竞品品牌,作为监控模型的种子词。每行一个,同一项目内名称唯一。
      </div>
      <div style={{ marginBottom: 12, display: "flex", justifyContent: "flex-end" }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setEditing({ mode: "create", initial: null })}
        >
          新增竞品
        </Button>
      </div>
      <Table<CompetitorOut>
        rowKey="id"
        dataSource={competitors}
        columns={columns}
        pagination={false}
        locale={{
          emptyText: <span style={{ color: "var(--text-quaternary)" }}>暂无竞品,点击右上角新增</span>,
        }}
      />
      <CompetitorEditModal
        open={editing !== null}
        mode={editing?.mode ?? "create"}
        initial={editing?.initial ?? null}
        projectId={projectId}
        onCancel={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          onReload();
        }}
      />
    </div>
  );
}

interface CompetitorEditModalProps {
  open: boolean;
  mode: "create" | "edit";
  initial: CompetitorOut | null;
  projectId: number;
  onCancel: () => void;
  onSaved: () => void;
}

function CompetitorEditModal({
  open,
  mode,
  initial,
  projectId,
  onCancel,
  onSaved,
}: CompetitorEditModalProps) {
  const [form] = Form.useForm<CompetitorPayload>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        name: initial?.name ?? "",
        note: initial?.note ?? "",
      });
    }
  }, [open, initial, form]);

  const submit = async () => {
    try {
      const v = await form.validateFields();
      setSaving(true);
      try {
        const payload: CompetitorPayload = {
          name: v.name.trim(),
          note: v.note?.trim() || null,
        };
        if (mode === "create") {
          await createCompetitor(projectId, payload);
        } else if (initial) {
          await updateCompetitor(projectId, initial.id, payload);
        }
        message.success(mode === "create" ? "已新增" : "已更新");
        onSaved();
      } finally {
        setSaving(false);
      }
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      const e = err as { response?: { data?: { detail?: string } } };
      message.error(e?.response?.data?.detail || (err as Error).message || "操作失败");
    }
  };

  return (
    <Modal
      open={open}
      title={mode === "create" ? "新增竞品" : "编辑竞品"}
      okText="保存"
      cancelText="取消"
      onCancel={onCancel}
      onOk={submit}
      confirmLoading={saving}
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="name"
          label="竞品名称"
          rules={[
            { required: true, message: "请输入竞品名称" },
            { max: 128, message: "不能超过 128 个字符" },
          ]}
        >
          <Input placeholder="例如:字节跳动" />
        </Form.Item>
        <Form.Item name="note" label="备注">
          <Input.TextArea rows={3} placeholder="选填,例如品牌定位或核心产品" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function RunsTab({ projectId }: { projectId: number }) {
  const [items, setItems] = useState<ScheduleRunOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  const load = async (p = page) => {
    setLoading(true);
    try {
      const data = await listRuns(projectId, {
        page: p,
        size: pageSize,
        status: statusFilter,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(1);
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const duration = (s: ScheduleRunOut) => {
    if (!s.started_at || !s.finished_at) return "—";
    const ms = dayjs(s.finished_at).diff(dayjs(s.started_at));
    if (ms < 1000) return `${ms}ms`;
    const sec = Math.round(ms / 1000);
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m${sec % 60}s`;
  };

  const columns: ColumnsType<ScheduleRunOut> = [
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: string) => <StatusTag status={s} />,
    },
    {
      title: "执行序号",
      key: "order",
      width: 100,
      render: (_, __, i) => `第 ${(page - 1) * pageSize + i + 1} 次`,
    },
    {
      title: "触发时间",
      dataIndex: "triggered_at",
      width: 170,
      render: (v: string) => formatTime(v),
    },
    {
      title: "触发方式",
      dataIndex: "trigger_type",
      width: 100,
      render: (v: string) =>
        v === "cron" ? <Tag>定时</Tag> : <Tag color="orange">手动</Tag>,
    },
    {
      title: "耗时",
      key: "duration",
      width: 100,
      render: (_, r) => duration(r),
    },
    {
      title: "任务 ID",
      dataIndex: "task_id",
      render: (v: number | null) =>
        v ? (
          <span style={{ color: "var(--brand-blue)" }}>#{v}</span>
        ) : (
          <span style={{ color: "var(--text-quaternary)" }}>—</span>
        ),
    },
    {
      title: "错误",
      dataIndex: "error_message",
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <span style={{ color: "var(--text-tertiary)", fontSize: 12 }}>
              {v.length > 30 ? `${v.slice(0, 30)}…` : v}
            </span>
          </Tooltip>
        ) : (
          <span style={{ color: "var(--text-quaternary)" }}>—</span>
        ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 12, display: "flex", gap: 12 }}>
        <Select
          placeholder="全部状态"
          allowClear
          style={{ width: 160 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "queued", label: "排队中" },
            { value: "running", label: "执行中" },
            { value: "success", label: "成功" },
            { value: "failed", label: "失败" },
            { value: "skipped", label: "已跳过" },
          ]}
        />
      </div>
      <Table<ScheduleRunOut>
        rowKey="id"
        loading={loading}
        dataSource={items}
        columns={columns}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 次`,
          onChange: (p) => {
            setPage(p);
            load(p);
          },
        }}
      />
    </div>
  );
}

interface InfoTabProps {
  data: ProjectDetailOut;
  customer: Customer | undefined;
  lastRunAt: string | null;
}

function InfoTab({ data, customer, lastRunAt }: InfoTabProps) {
  const rows: Array<[string, React.ReactNode]> = [
    [
      "客户名",
      customer ? (
        <Link to="/admin/customers" style={{ color: "var(--brand-blue)" }}>
          {customer.name}
        </Link>
      ) : (
        <span style={{ color: "var(--text-quaternary)" }}>—</span>
      ),
    ],
    ["项目编号", data.code],
    [
      "描述",
      data.description || (
        <span style={{ color: "var(--text-quaternary)" }}>—</span>
      ),
    ],
    ["创建时间", formatTime(data.created_at)],
    ["最近执行", formatTime(lastRunAt)],
    [
      "状态",
      data.status === "active" ? (
        <Tag color="green">启用</Tag>
      ) : (
        <Tag>停用</Tag>
      ),
    ],
    [
      "情感分析",
      data.sentiment_enabled ? (
        <Tag color="purple">已启用</Tag>
      ) : (
        <Tag>未启用</Tag>
      ),
    ],
    [
      "地域策略",
      data.region_strategy === "national_random" ? (
        <Tag color="orange">全国随机</Tag>
      ) : (
        <Tag>固定地域</Tag>
      ),
    ],
    [
      "地域代码",
      data.region_strategy === "fixed" ? (
        data.region_codes && data.region_codes.length > 0 ? (
          <Space wrap>
            {data.region_codes.map((c) => (
              <Tag key={c}>{c}</Tag>
            ))}
          </Space>
        ) : (
          <span style={{ color: "var(--text-quaternary)" }}>未配置</span>
        )
      ) : (
        <span style={{ color: "var(--text-tertiary)" }}>
          每次随机抽样,无需配置
        </span>
      ),
    ],
    [
      "关键词",
      <Space wrap key="tags">
        {data.keywords.length === 0 ? (
          <span style={{ color: "var(--text-quaternary)" }}>—</span>
        ) : (
          data.keywords.slice(0, 8).map((k) => <Tag key={k}>{k}</Tag>)
        )}
      </Space>,
    ],
  ];

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "120px 1fr",
        rowGap: 12,
        columnGap: 16,
        maxWidth: 720,
      }}
    >
      {rows.map(([label, value]) => (
        <div key={label} style={{ display: "contents" }}>
          <div
            style={{
              color: "var(--text-tertiary)",
              textAlign: "right",
            }}
          >
            {label}
          </div>
          <div>{value}</div>
        </div>
      ))}
    </div>
  );
}

interface SlotEditProps {
  open: boolean;
  slots: SlotOut[];
  enabled: boolean;
  onCancel: () => void;
  onSave: (slots: SlotOut[], enabled: boolean) => Promise<void>;
}

function SlotEditModal({ open, slots, enabled, onCancel, onSave }: SlotEditProps) {
  const [list, setList] = useState<SlotOut[]>(slots);
  const [en, setEn] = useState(enabled);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setList(slots);
    setEn(enabled);
  }, [slots, enabled, open]);

  const add = () => {
    if (list.length >= 2) {
      message.warning("最多 2 个时间点");
      return;
    }
    setList([...list, { slot_index: list.length + 1, hour: 9, minute: 0 }]);
  };

  const remove = (idx: number) => {
    setList(list.filter((_, i) => i !== idx));
  };

  const update = (idx: number, patch: Partial<SlotOut>) => {
    setList(list.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const save = async () => {
    if (en && list.length === 0) {
      message.error("启用调度至少需要 1 个时间点");
      return;
    }
    setSaving(true);
    try {
      await onSave(list, en);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title="修改每日执行时间"
      okText="保存"
      cancelText="取消"
      onCancel={onCancel}
      onOk={save}
      confirmLoading={saving}
      destroyOnClose
    >
      <div style={{ marginBottom: 16 }}>
        <Switch
          checked={en}
          onChange={setEn}
          checkedChildren="启用"
          unCheckedChildren="停用"
        />
        <span style={{ marginLeft: 12, color: "var(--text-secondary)" }}>
          {en ? "已启用" : "已停用"}
        </span>
      </div>
      {list.map((s, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            gap: 8,
            marginBottom: 8,
            alignItems: "center",
          }}
        >
          <span style={{ color: "var(--text-tertiary)", width: 60 }}>
            时间 {i + 1}
          </span>
          <InputNumber
            min={0}
            max={23}
            value={s.hour}
            onChange={(v) => update(i, { hour: Number(v ?? 0) })}
            style={{ width: 80 }}
          />
          <span>:</span>
          <InputNumber
            min={0}
            max={59}
            value={s.minute}
            onChange={(v) => update(i, { minute: Number(v ?? 0) })}
            style={{ width: 80 }}
          />
          <Button
            type="link"
            danger
            icon={<DeleteOutlined />}
            onClick={() => remove(i)}
          >
            删除
          </Button>
        </div>
      ))}
      <Button
        type="dashed"
        onClick={add}
        disabled={list.length >= 2}
        icon={<PlusOutlined />}
        block
      >
        新增时间点
      </Button>
    </Modal>
  );
}

interface BasicEditProps {
  open: boolean;
  data: ProjectDetailOut;
  onCancel: () => void;
  onSave: (payload: {
    name: string;
    description: string | null;
    status: "active" | "disabled";
    sentiment_enabled: boolean;
    region_strategy: RegionStrategy;
    region_codes: string[] | null;
  }) => Promise<void>;
}

function BasicEditModal({ open, data, onCancel, onSave }: BasicEditProps) {
  const [form] = Form.useForm<{
    name: string;
    description?: string;
    status: "active" | "disabled";
    sentiment_enabled: boolean;
    region_strategy: RegionStrategy;
    region_codes_text: string;
  }>();
  const [saving, setSaving] = useState(false);
  const strategy = Form.useWatch("region_strategy", form);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        name: data.name,
        description: data.description ?? "",
        status: data.status,
        sentiment_enabled: data.sentiment_enabled,
        region_strategy: data.region_strategy,
        region_codes_text: (data.region_codes ?? []).join(","),
      });
    }
  }, [open, data, form]);

  const submit = async () => {
    try {
      const v = await form.validateFields();
      const codes =
        v.region_strategy === "fixed" && v.region_codes_text
          ? v.region_codes_text
              .split(/[,\s]+/)
              .map((s) => s.trim())
              .filter(Boolean)
          : null;
      setSaving(true);
      try {
        await onSave({
          name: v.name,
          description: v.description?.trim() || null,
          status: v.status,
          sentiment_enabled: v.sentiment_enabled,
          region_strategy: v.region_strategy,
          region_codes: codes,
        });
      } finally {
        setSaving(false);
      }
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      message.error((err as Error).message || "保存失败");
    }
  };

  return (
    <Modal
      open={open}
      title="编辑基本信息"
      okText="保存"
      cancelText="取消"
      onCancel={onCancel}
      onOk={submit}
      confirmLoading={saving}
      destroyOnClose
      width={520}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="项目名称"
          rules={[{ required: true, message: "请输入项目名称" }]}
        >
          <Input />
        </Form.Item>
        <Form.Item name="description" label="项目描述">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="status" label="项目状态">
          <Select
            options={[
              { value: "active", label: "启用" },
              { value: "disabled", label: "停用" },
            ]}
          />
        </Form.Item>
        <div
          style={{
            borderTop: "1px dashed var(--border-light)",
            margin: "8px 0 16px",
          }}
        />
        <div style={{ marginBottom: 12, color: "var(--text-tertiary)", fontSize: 12 }}>
          高级设置
        </div>
        <Form.Item
          name="sentiment_enabled"
          label="情感分析"
          valuePropName="checked"
          tooltip="开启后会对每次 AI 回答打分并参与排序"
        >
          <Switch checkedChildren="开" unCheckedChildren="关" />
        </Form.Item>
        <Form.Item name="region_strategy" label="地域策略">
          <Radio.Group>
            <Radio.Button value="fixed">固定地域</Radio.Button>
            <Radio.Button value="national_random">全国随机</Radio.Button>
          </Radio.Group>
        </Form.Item>
        {strategy === "fixed" && (
          <Form.Item
            name="region_codes_text"
            label="地域代码"
            tooltip="行政区代码,如 110000(北京)、310000(上海)。逗号分隔"
          >
            <Input placeholder="例如:110000, 310000" />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const navigate = useNavigate();

  const [data, setData] = useState<ProjectDetailOut | null>(null);
  const [customer, setCustomer] = useState<Customer | undefined>(undefined);
  const [lastRunAt, setLastRunAt] = useState<string | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [slotEditOpen, setSlotEditOpen] = useState(false);
  const [basicEditOpen, setBasicEditOpen] = useState(false);

  const load = async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const d = await getProject(projectId);
      setData(d);
      const [cs, sched, comp] = await Promise.all([
        listCustomers({ page: 1, size: 200 }).catch(() => ({ items: [] as Customer[] })),
        getSchedule(projectId).catch(() => null),
        listCompetitors(projectId).catch(() => ({ items: [], total: 0 })),
      ]);
      setCustomer(cs.items.find((c) => c.id === d.customer_id));
      setLastRunAt(sched?.last_run?.triggered_at ?? null);
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

  const onToggleSchedule = async (v: boolean) => {
    if (!data) return;
    try {
      await toggleSchedule(data.id, v);
      message.success(v ? "已启用调度" : "已停用调度");
      load();
    } catch (err) {
      message.error((err as Error).message || "操作失败");
    }
  };

  const onTrigger = async () => {
    if (!data) return;
    try {
      await triggerRun(data.id);
      message.success("已开始执行");
      load();
    } catch (err) {
      const e = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e?.response?.status === 409) {
        message.warning("5 分钟内已执行过,已跳过");
      } else {
        message.error(e?.response?.data?.detail || (err as Error).message || "触发失败");
      }
    }
  };

  const onDelete = () => {
    if (!data) return;
    Modal.confirm({
      title: "确认停用该项目?",
      content: `项目「${data.name}」将被标记为停用,可在编辑中重新启用。`,
      okText: "确认停用",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteProject(data.id);
          message.success("已停用");
          navigate("/admin/projects");
        } catch (err) {
          message.error((err as Error).message || "操作失败");
        }
      },
    });
  };

  const onSaveSlots = async (slots: SlotOut[], enabled: boolean) => {
    if (!data) return;
    try {
      await updateSchedule(data.id, {
        schedule_enabled: enabled,
        slots: slots.map((s) => ({ hour: s.hour, minute: s.minute })),
      });
      if (enabled !== data.schedule_enabled) {
        await toggleSchedule(data.id, enabled);
      }
      message.success("已保存");
      setSlotEditOpen(false);
      load();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const onSaveBasic = async (payload: {
    name: string;
    description: string | null;
    status: "active" | "disabled";
    sentiment_enabled: boolean;
    region_strategy: RegionStrategy;
    region_codes: string[] | null;
  }) => {
    if (!data) return;
    await updateProject(data.id, payload);
    message.success("已保存");
    setBasicEditOpen(false);
    load();
  };

  if (loading && !data) {
    return <Card loading bordered={false} />;
  }

  if (!data) {
    return (
      <Card bordered={false}>
        <div style={{ color: "var(--text-tertiary)" }}>项目不存在或加载失败</div>
      </Card>
    );
  }

  const letter = data.name?.trim().charAt(0) ?? "?";

  const promptCount = data.prompts.length;
  const platformCount = data.platforms.length;
  const keywordCount = data.keywords.length;
  const competitorCount = competitors.length;
  const subtasks = promptCount * platformCount;

  const headerCard = (
    <Card
      bordered={false}
      styles={{ body: { padding: 24 } }}
      style={{ marginBottom: 16, borderRadius: 8 }}
    >
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: 8,
            background: "linear-gradient(135deg, var(--brand-blue-light), var(--brand-blue))",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 28,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {letter}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Title level={3} style={{ margin: 0, fontSize: 22 }}>
            {data.name}
          </Title>
          <div style={{ color: "var(--text-tertiary)", marginTop: 4, fontSize: 13 }}>
            {customer?.name ?? `客户 #${data.customer_id}`} · 编号 {data.code}
          </div>
          {data.description && (
            <div style={{ color: "var(--text-secondary)", marginTop: 8, fontSize: 13 }}>
              {data.description}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-end" }}>
          <Space>
            <Button
              type="primary"
              icon={<RocketOutlined />}
              style={{ background: "var(--brand-orange)", borderColor: "var(--brand-orange)" }}
              onClick={onTrigger}
            >
              立即执行
            </Button>
            <Button icon={<EditOutlined />} onClick={() => setBasicEditOpen(true)}>
              编辑基本信息
            </Button>
            <Button danger onClick={onDelete}>
              删除
            </Button>
          </Space>
        </div>
      </div>

      <div
        style={{
          marginTop: 20,
          paddingTop: 20,
          borderTop: "1px solid var(--border-light)",
          display: "flex",
          gap: 32,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <div>
          <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginBottom: 4 }}>
            调度状态
          </div>
          <Space>
            <Switch
              checked={data.schedule_enabled}
              onChange={onToggleSchedule}
              checkedChildren="开"
              unCheckedChildren="关"
            />
            <span style={{ color: "var(--text-secondary)" }}>
              {data.schedule_enabled ? "已启用" : "已停用"}
            </span>
          </Space>
        </div>
        <div>
          <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginBottom: 4 }}>
            下一执行
          </div>
          <div
            style={{
              color: data.schedule_enabled ? "var(--brand-blue)" : "var(--text-quaternary)",
              fontWeight: 500,
            }}
          >
            {data.schedule_enabled ? formatTime(data.next_run_at) : "—"}
          </div>
        </div>
        <div>
          <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginBottom: 4 }}>
            每日执行时间
          </div>
          <Space>
            {data.slots.length === 0 ? (
              <span style={{ color: "var(--text-quaternary)" }}>—</span>
            ) : (
              data.slots.map((s) => (
                <div
                  key={s.slot_index}
                  style={{
                    border: "1px solid var(--border-default)",
                    borderRadius: 4,
                    padding: "4px 10px",
                    fontSize: 13,
                    fontFamily: "monospace",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <ClockCircleOutlined style={{ color: "var(--brand-blue)" }} />
                  {formatSlot(s)}
                </div>
              ))
            )}
            <Button size="small" type="link" onClick={() => setSlotEditOpen(true)}>
              修改时间
            </Button>
          </Space>
        </div>
      </div>
    </Card>
  );

  const overviewCard = (
    <Card
      bordered={false}
      styles={{ body: { padding: 24 } }}
      style={{ marginBottom: 16, borderRadius: 8 }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 24,
        }}
      >
        <div>
          <Space style={{ marginBottom: 8 }}>
            <Tag color="blue" style={{ borderRadius: 11, padding: "0 8px" }}>
              监控问题
            </Tag>
            <Tag style={{ background: "var(--brand-blue-50)", borderColor: "var(--brand-blue-50)" }}>
              {promptCount}
            </Tag>
          </Space>
          <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8 }}>
            {promptCount === 0 ? (
              <span style={{ color: "var(--text-quaternary)" }}>尚未配置</span>
            ) : (
              data.prompts.slice(0, 3).map((p, i) => (
                <div
                  key={i}
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {i + 1}. {p}
                </div>
              ))
            )}
            {promptCount > 3 && (
              <div style={{ color: "var(--brand-blue)", marginTop: 4 }}>
                + {promptCount - 3} 个问题
              </div>
            )}
          </div>
        </div>
        <div>
          <Space style={{ marginBottom: 8 }}>
            <Tag color="orange" style={{ borderRadius: 11, padding: "0 8px" }}>
              AI 模型
            </Tag>
            <Tag style={{ background: "var(--brand-orange-50)", borderColor: "var(--brand-orange-50)" }}>
              {platformCount}
            </Tag>
          </Space>
          <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8 }}>
            {platformCount === 0 ? (
              <span style={{ color: "var(--text-quaternary)" }}>尚未配置</span>
            ) : (
              <Space wrap size={[4, 4]}>
                {data.platforms.map((p) => (
                  <Tag key={p.platform} color="orange">
                    {p.platform}
                  </Tag>
                ))}
              </Space>
            )}
          </div>
        </div>
        <div>
          <Space style={{ marginBottom: 8 }}>
            <Tag color="purple" style={{ borderRadius: 11, padding: "0 8px" }}>
              品牌关键字
            </Tag>
            <Tag style={{ background: "rgba(114, 46, 209, 0.08)", borderColor: "rgba(114, 46, 209, 0.08)" }}>
              {keywordCount}
            </Tag>
          </Space>
          <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8 }}>
            {keywordCount === 0 ? (
              <span style={{ color: "var(--text-quaternary)" }}>尚未配置</span>
            ) : (
              <Space wrap>
                {data.keywords.slice(0, 5).map((k) => (
                  <Tag key={k} color="purple">
                    {k}
                  </Tag>
                ))}
                {keywordCount > 5 && (
                  <span style={{ color: "var(--brand-blue)" }}>+ {keywordCount - 5}</span>
                )}
              </Space>
            )}
          </div>
        </div>
        <div>
          <Space style={{ marginBottom: 8 }}>
            <Tag color="cyan" style={{ borderRadius: 11, padding: "0 8px" }}>
              竞品
            </Tag>
            <Tag style={{ background: "rgba(6, 182, 212, 0.08)", borderColor: "rgba(6, 182, 212, 0.08)" }}>
              {competitorCount}
            </Tag>
          </Space>
          <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8 }}>
            {competitorCount === 0 ? (
              <span style={{ color: "var(--text-quaternary)" }}>尚未配置</span>
            ) : (
              competitors.slice(0, 3).map((c, i) => (
                <div
                  key={c.id}
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {i + 1}. {c.name}
                </div>
              ))
            )}
            {competitorCount > 3 && (
              <div style={{ color: "var(--brand-blue)", marginTop: 4 }}>
                + {competitorCount - 3} 个竞品
              </div>
            )}
          </div>
        </div>
      </div>
      <div
        style={{
          marginTop: 16,
          paddingTop: 16,
          borderTop: "1px dashed var(--border-light)",
          color: "var(--text-tertiary)",
          fontSize: 12,
        }}
      >
        每次执行会按此组合提交 API · {promptCount} 个问题 × {platformCount} 个模型 = {subtasks} 个子任务
      </div>
    </Card>
  );

  return (
    <div>
      <div style={{ marginBottom: 12, color: "var(--text-tertiary)", fontSize: 13 }}>
        <Link to="/admin/projects" style={{ color: "var(--text-tertiary)" }}>
          监控项目
        </Link>
        <span style={{ margin: "0 8px" }}>/</span>
        <strong style={{ color: "var(--text-primary)" }}>{data.name}</strong>
      </div>

      {headerCard}
      {overviewCard}

      <Card bordered={false} styles={{ body: { padding: "0 16px" } }} style={{ borderRadius: 8 }}>
        <Tabs
          defaultActiveKey="prompts"
          items={[
            {
              key: "prompts",
              label: "监控问题",
              children: (
                <div style={{ paddingTop: 16 }}>
                  <PromptsTab
                    projectId={data.id}
                    prompts={data.prompts}
                    onSaved={load}
                  />
                </div>
              ),
            },
            {
              key: "platforms",
              label: "AI 模型",
              children: (
                <div style={{ paddingTop: 16 }}>
                  <PlatformsTab
                    projectId={data.id}
                    platforms={data.platforms}
                    onSaved={load}
                  />
                </div>
              ),
            },
            {
              key: "keywords",
              label: "品牌关键字",
              children: (
                <div style={{ paddingTop: 16 }}>
                  <KeywordsTab
                    projectId={data.id}
                    keywords={data.keywords}
                    onSaved={load}
                  />
                </div>
              ),
            },
            {
              key: "competitors",
              label: (
                <span>
                  竞品信息
                  {competitorCount > 0 && (
                    <Tag style={{ marginLeft: 6 }}>{competitorCount}</Tag>
                  )}
                </span>
              ),
              children: (
                <div style={{ paddingTop: 16 }}>
                  <CompetitorsTab
                    projectId={data.id}
                    competitors={competitors}
                    onReload={() => {
                      listCompetitors(data.id)
                        .then((d) => setCompetitors(d.items))
                        .catch(() => undefined);
                    }}
                  />
                </div>
              ),
            },
            {
              key: "runs",
              label: "执行历史",
              children: (
                <div style={{ paddingTop: 16 }}>
                  <RunsTab projectId={data.id} />
                </div>
              ),
            },
            {
              key: "info",
              label: "基本信息",
              children: (
                <div style={{ paddingTop: 16, paddingBottom: 16 }}>
                  <InfoTab
                    data={data}
                    customer={customer}
                    lastRunAt={lastRunAt}
                  />
                </div>
              ),
            },
          ]}
        />
      </Card>

      <SlotEditModal
        open={slotEditOpen}
        slots={data.slots}
        enabled={data.schedule_enabled}
        onCancel={() => setSlotEditOpen(false)}
        onSave={onSaveSlots}
      />
      <BasicEditModal
        open={basicEditOpen}
        data={data}
        onCancel={() => setBasicEditOpen(false)}
        onSave={onSaveBasic}
      />
    </div>
  );
}