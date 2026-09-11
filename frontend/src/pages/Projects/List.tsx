import {
  Button,
  Card,
  Input,
  Modal,
  Select,
  Switch,
  Table,
  Tag,
  Tooltip,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSetCurrentProject } from "../../auth/ProjectContext";
import dayjs from "dayjs";
import {
  deleteProject,
  getProject,
  listProjects,
  listRuns,
  toggleSchedule,
  triggerRun,
  type ProjectDetailOut,
  type ProjectOut,
  type ScheduleRunOut,
} from "../../api/projects";
import { listCustomers, type Customer } from "../../api/customers";
import BatchQuestionModal from "./BatchQuestionModal";
import TaskDetailModal from "./TaskDetailModal";

interface RowDetail {
  prompts: number;
  platforms: string[];
  lastRun: ScheduleRunOut | null;
}

const STATUS_TAG: Record<string, { color: string; bg: string; text: string }> = {
  success: { color: "#16a34a", bg: "#dcfce7", text: "成功" },
  failed: { color: "#dc2626", bg: "#fee2e2", text: "失败" },
  partial_completed: { color: "#ea580c", bg: "#ffedd5", text: "部分完成" },
  skipped: { color: "#6b7280", bg: "#f3f4f6", text: "跳过" },
  queued: { color: "#2563eb", bg: "#dbeafe", text: "排队" },
  running: { color: "#2563eb", bg: "#dbeafe", text: "执行中" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_TAG[status] ?? { color: "#6b7280", bg: "#f3f4f6", text: status };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 8px",
        borderRadius: 4,
        fontSize: 12,
        color: cfg.color,
        background: cfg.bg,
        fontWeight: 500,
        lineHeight: 1.6,
      }}
    >
      {cfg.text}
    </span>
  );
}

// Per-letter pastel avatar colors used in the mockup.
const AVATAR_PALETTE = [
  { bg: "#dbeafe", fg: "#1d4ed8" }, // blue
  { bg: "#dcfce7", fg: "#16a34a" }, // green
  { bg: "#fee2e2", fg: "#dc2626" }, // red
  { bg: "#fef3c7", fg: "#d97706" }, // amber
  { bg: "#ede9fe", fg: "#7c3aed" }, // purple
  { bg: "#fce7f3", fg: "#db2777" }, // pink
  { bg: "#cffafe", fg: "#0891b2" }, // cyan
  { bg: "#ffedd5", fg: "#ea580c" }, // orange
];

function avatarFor(seed: string): { bg: string; fg: string } {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length];
}

function formatTime(v: string | null) {
  return v ? dayjs(v).format("YYYY-MM-DD HH:mm") : "—";
}

function relative(v: string | null): string {
  if (!v) return "";
  const ms = dayjs(v).valueOf() - Date.now();
  const abs = Math.abs(ms);
  const future = ms > 0;
  const sec = Math.round(abs / 1000);
  const min = Math.round(sec / 60);
  const hr = Math.round(min / 60);
  const day = Math.round(hr / 24);
  let body = "";
  if (abs < 60_000) body = `${sec}秒`;
  else if (abs < 3_600_000) body = `${min}分钟`;
  else if (abs < 86_400_000) body = `${hr}小时${min % 60}分钟`;
  else body = `${day}天${hr % 24}小时`;
  return future ? `${body}后` : `${body}前`;
}

function renderRunSummary(r: ScheduleRunOut): string {
  // Only meaningful once the run has actually produced subtasks.
  if (r.total_count === 0) return "";
  const parts: string[] = [`${r.success_count}/${r.total_count} 完成`];
  if (r.failed_count > 0) parts.push(`${r.failed_count} 失败`);
  if (r.partial_count > 0) parts.push(`${r.partial_count} 部分`);
  return parts.join(" · ");
}

export default function ProjectsList() {
  const setCurrentProjectId = useSetCurrentProject();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [items, setItems] = useState<ProjectOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [customerFilter, setCustomerFilter] = useState<number | undefined>(undefined);
  // 「监控项目」页面只看 status=active 行;筛选 dropdown 改按调度状态过滤:
  // 启用 = schedule_enabled=true(正在跑),停用 = false(暂停调度)。
  const [scheduleFilter, setScheduleFilter] = useState<boolean | undefined>(undefined);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [details, setDetails] = useState<Record<number, RowDetail>>({});
  // 新建项目 —— 已迁移到独立页面 ``/admin/new-project``,这里只跳过去。
  // modal state — when set, opens BatchQuestionModal over the list page
  const [modalProjectId, setModalProjectId] = useState<number | undefined>(undefined);
  const [taskDetailId, setTaskDetailId] = useState<number | undefined>(undefined);

  // Auto-open modal from URL ?open=<id> (used by the /projects/:id route's
  // redirect so legacy links still work). After consumption we strip the
  // param so a refresh doesn't re-trigger.
  useEffect(() => {
    const open = searchParams.get("open");
    if (open && /^\d+$/.test(open)) {
      setModalProjectId(Number(open));
      const next = new URLSearchParams(searchParams);
      next.delete("open");
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, setSearchParams]);

  // Publish the active project to ProjectContext whenever the in-place
  // modal is opened (via row click or auto-open from ?open=<id>) so the
  // sidebar's 数据洞察 / 数据中心 / 系统 groups stay visible after the
  // user closes the modal or navigates to 管理组 items.
  useEffect(() => {
    if (modalProjectId !== undefined) setCurrentProjectId(modalProjectId);
  }, [modalProjectId, setCurrentProjectId]);

  const customerMap = useMemo(() => {
    const m: Record<number, Customer> = {};
    customers.forEach((c) => {
      m[c.id] = c;
    });
    return m;
  }, [customers]);

  const loadCustomers = async () => {
    try {
      const data = await listCustomers({ page: 1, size: 100 });
      setCustomers(data.items);
    } catch {
      // ignore — filter will just lack labels
    }
  };

  const ingestDetail = async (projectId: number): Promise<RowDetail | null> => {
    try {
      const [detail, runs] = await Promise.all([
        getProject(projectId).catch(() => null as ProjectDetailOut | null),
        listRuns(projectId, { page: 1, size: 1 }).catch(() => null),
      ]);
      return {
        prompts: detail?.prompts?.length ?? 0,
        platforms: detail?.platforms?.map((p) => p.platform) ?? [],
        lastRun: runs?.items?.[0] ?? null,
      };
    } catch {
      return null;
    }
  };

  const load = async (p = page) => {
    setLoading(true);
    try {
      const data = await listProjects({
        page: p,
        size: pageSize,
        customer_id: customerFilter,
        status: "active",
        schedule_enabled: scheduleFilter,
      });
      setItems(data.items);
      setTotal(data.total);
      const next: Record<number, RowDetail> = {};
      await Promise.all(
        data.items.map(async (it) => {
          const d = await ingestDetail(it.id);
          next[it.id] = d ?? { prompts: 0, platforms: [], lastRun: null };
        }),
      );
      setDetails(next);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCustomers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load(1);
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerFilter, scheduleFilter]);

  const filtered = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return items;
    return items.filter(
      (p) =>
        p.name.toLowerCase().includes(k) ||
        (p.code ?? "").toLowerCase().includes(k),
    );
  }, [items, keyword]);

  const openCreate = () => {
    // 列表页头部「新建项目」按钮 —— 直接跳到独立向导页。
    navigate("/admin/new-project");
  };

  const onToggle = async (record: ProjectOut, enabled: boolean) => {
    try {
      await toggleSchedule(record.id, enabled);
      message.success(enabled ? "已启用调度" : "已停用调度");
      load(page);
    } catch (err) {
      const e = err as { response?: { status?: number; data?: { detail?: string } } };
      message.error(e?.response?.data?.detail || (err as Error).message || "操作失败");
    }
  };

  const onTrigger = async (record: ProjectOut) => {
    try {
      const res = await triggerRun(record.id);
      const count = 1 + (res.think_run_id ? 1 : 0);
      message.success(count > 1 ? `已开始执行 (${count} 个任务)` : "已开始执行");
      load(page);
    } catch (err) {
      const e = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e?.response?.status === 409) {
        message.warning("5 分钟内已执行过,已跳过");
      } else {
        message.error(e?.response?.data?.detail || (err as Error).message || "触发失败");
      }
    }
  };

  const onDelete = (record: ProjectOut) => {
    Modal.confirm({
      title: "确认删除项目",
      content: `项目「${record.name}」删除后将不可恢复,确定继续吗?`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteProject(record.id);
          message.success("已删除");
          load(page);
        } catch (err) {
          message.error((err as Error).message || "删除失败");
        }
      },
    });
  };

  const columns: ColumnsType<ProjectOut> = [
    {
      title: "项目",
      dataIndex: "name",
      width: 280,
      render: (name: string, record) => {
        const customer = customerMap[record.customer_id];
        const a = avatarFor(record.code || name);
        const letter = (name?.trim().charAt(0) ?? "?").toUpperCase();
        return (
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 8,
                background: a.bg,
                color: a.fg,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 16,
                fontWeight: 600,
                flexShrink: 0,
              }}
            >
              {letter}
            </div>
            <div style={{ minWidth: 0 }}>
              <button
                type="button"
                onClick={() => setModalProjectId(record.id)}
                style={{
                  background: "none",
                  border: 0,
                  padding: 0,
                  color: "var(--brand-blue)",
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: "pointer",
                  lineHeight: 1.4,
                }}
              >
                {name}
              </button>
              <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
                {customer?.name ?? `客户 #${record.customer_id}`}
              </div>
            </div>
          </div>
        );
      },
    },
    {
      title: "问题数",
      key: "prompts",
      width: 80,
      render: (_, record) => {
        const n = details[record.id]?.prompts ?? 0;
        return (
          <span
            style={{
              color: n > 0 ? "var(--text-primary)" : "var(--text-quaternary)",
              fontWeight: 500,
            }}
          >
            {n}
          </span>
        );
      },
    },
    {
      title: "模型",
      key: "platforms",
      width: 180,
      render: (_, record) => {
        const ps = details[record.id]?.platforms ?? [];
        if (ps.length === 0) {
          return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        }
        return (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {ps.slice(0, 4).map((p) => (
              <Tag key={p} color="blue" style={{ margin: 0 }}>
                {p}
              </Tag>
            ))}
            {ps.length > 4 && (
              <Tooltip title={ps.slice(4).join("、")}>
                <Tag style={{ margin: 0 }}>×{ps.length - 4}</Tag>
              </Tooltip>
            )}
          </div>
        );
      },
    },
    {
      title: "调度",
      key: "scheduleEnabled",
      width: 80,
      render: (_, record) => (
        <Switch
          checked={record.schedule_enabled}
          onChange={(v) => onToggle(record, v)}
          size="small"
        />
      ),
    },
    {
      title: "下一执行",
      dataIndex: "next_run_at",
      width: 160,
      render: (v: string | null, record) => {
        if (!record.schedule_enabled) {
          return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        }
        return (
          <div>
            <div style={{ color: "var(--brand-blue)", fontSize: 13, fontWeight: 500 }}>
              {formatTime(v)}
            </div>
            <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginTop: 2 }}>
              {relative(v)}
            </div>
          </div>
        );
      },
    },
    {
      title: "最近一次",
      key: "lastRun",
      width: 140,
      render: (_, record) => {
        const r = details[record.id]?.lastRun;
        if (!r) {
          return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        }
        const summary = renderRunSummary(r);
        return (
          <div>
            <StatusBadge status={r.status} />
            <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginTop: 2 }}>
              {relative(r.triggered_at)}
            </div>
            {summary && (
              <div
                style={{
                  color: "var(--text-tertiary)",
                  fontSize: 12,
                  marginTop: 2,
                  whiteSpace: "nowrap",
                }}
              >
                {summary}
              </div>
            )}
          </div>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 180,
      render: (_, record) => (
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Tooltip title="立即执行">
            <Button
              type="text"
              size="small"
              icon={<ThunderboltOutlined style={{ color: "var(--brand-blue)" }} />}
              onClick={() => onTrigger(record)}
            />
          </Tooltip>
          <Tooltip title="编辑监控项目">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined style={{ color: "var(--text-secondary)" }} />}
              onClick={() => setModalProjectId(record.id)}
            />
          </Tooltip>
          <Tooltip title="任务详情">
            <Button
              type="text"
              size="small"
              icon={<FileTextOutlined style={{ color: "var(--text-secondary)" }} />}
              onClick={() => setTaskDetailId(record.id)}
            />
          </Tooltip>
          <Tooltip title="删除项目">
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => onDelete(record)}
            />
          </Tooltip>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0, color: "var(--text-primary)" }}>
            监控项目
          </h1>
          <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginTop: 4 }}>
            配置监控问题、配置调度、查看执行历史
          </div>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreate}
          style={{ background: "var(--brand-blue)", borderColor: "var(--brand-blue)" }}
        >
          新建项目
        </Button>
      </div>

      <Card bordered={false} styles={{ body: { padding: 16 } }}>
        <div
          style={{
            display: "flex",
            gap: 12,
            marginBottom: 12,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <Input.Search
            placeholder="搜索项目名 / 关键词"
            allowClear
            style={{ width: 280 }}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={(v) => setKeyword(v)}
          />
          <Select
            placeholder="全部客户"
            allowClear
            style={{ width: 180 }}
            value={customerFilter}
            onChange={(v) => setCustomerFilter(v)}
            options={customers.map((c) => ({ value: c.id, label: c.name }))}
            showSearch
            optionFilterProp="label"
          />
          <Select
            placeholder="全部调度"
            allowClear
            style={{ width: 140 }}
            value={scheduleFilter}
            onChange={(v) => setScheduleFilter(v)}
            options={[
              { value: true, label: "启用" },
              { value: false, label: "停用" },
            ]}
          />
        </div>
        <Table<ProjectOut>
          rowKey="id"
          loading={loading}
          dataSource={filtered}
          columns={columns}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条 · 每页 ${pageSize} 条`,
            onChange: (p) => {
              setPage(p);
              load(p);
            },
          }}
        />
      </Card>

      <BatchQuestionModal
        open={modalProjectId !== undefined}
        projectId={modalProjectId}
        onClose={() => setModalProjectId(undefined)}
        onSaved={() => {
          load(page);
        }}
      />

      <TaskDetailModal
        open={taskDetailId !== undefined}
        projectId={taskDetailId}
        projectName={
          taskDetailId !== undefined
            ? items.find((p) => p.id === taskDetailId)?.name ?? ""
            : ""
        }
        onClose={() => setTaskDetailId(undefined)}
      />
    </div>
  );
}