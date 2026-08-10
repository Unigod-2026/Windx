import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import dayjs from "dayjs";
import {
  createProject,
  getProject,
  listProjects,
  listRuns,
  toggleSchedule,
  triggerRun,
  type ProjectOut,
  type RunSummary,
} from "../../api/projects";
import { listCustomers, type Customer } from "../../api/customers";

interface CreateFormValues {
  customer_id: number;
  name: string;
  code: string;
  description?: string;
}

interface RowDetail {
  platforms: string[];
  lastRun: RunSummary | null;
}

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

function formatTime(v: string | null) {
  return v ? dayjs(v).format("YYYY-MM-DD HH:mm") : "—";
}

export default function ProjectsList() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ProjectOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [customerFilter, setCustomerFilter] = useState<number | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<"active" | "disabled" | undefined>(undefined);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [details, setDetails] = useState<Record<number, RowDetail>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm<CreateFormValues>();

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
    } catch (err) {
      // ignore — filter will just lack labels
    }
  };

  const load = async (p = page) => {
    setLoading(true);
    try {
      const data = await listProjects({
        page: p,
        size: pageSize,
        customer_id: customerFilter,
        status: statusFilter,
      });
      setItems(data.items);
      setTotal(data.total);
      // fetch detail + last run for visible rows in parallel
      const next: Record<number, RowDetail> = {};
      await Promise.all(
        data.items.map(async (it) => {
          try {
            const [detail, runs] = await Promise.all([
              getProject(it.id).catch(() => null),
              listRuns(it.id, { page: 1, size: 1 }).catch(() => null),
            ]);
            next[it.id] = {
              platforms: detail?.platforms?.map((p) => p.platform) ?? [],
              lastRun: runs?.items?.[0]
                ? {
                    id: runs.items[0].id,
                    status: runs.items[0].status,
                    triggered_at: runs.items[0].triggered_at,
                    finished_at: runs.items[0].finished_at,
                  }
                : null,
            };
          } catch {
            next[it.id] = { platforms: [], lastRun: null };
          }
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
  }, [customerFilter, statusFilter]);

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
    createForm.resetFields();
    setCreateOpen(true);
  };

  const onCreate = async () => {
    try {
      const v = await createForm.validateFields();
      await createProject(v.customer_id, {
        name: v.name,
        code: v.code,
        description: v.description || null,
      });
      message.success("已创建");
      setCreateOpen(false);
      load(1);
      setPage(1);
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      message.error((err as Error).message || "创建失败");
    }
  };

  const onToggle = async (record: ProjectOut, enabled: boolean) => {
    try {
      await toggleSchedule(record.id, enabled);
      message.success(enabled ? "已启用调度" : "已停用调度");
      load(page);
    } catch (err) {
      message.error((err as Error).message || "操作失败");
    }
  };

  const onTrigger = async (record: ProjectOut) => {
    try {
      const r = await triggerRun(record.id);
      message.success("已开始执行");
      // refresh short status
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

  const columns: ColumnsType<ProjectOut> = [
    {
      title: "项目",
      dataIndex: "name",
      render: (name: string, record) => {
        const customer = customerMap[record.customer_id];
        return (
          <div>
            <Link
              to={`/admin/projects/${record.id}`}
              style={{
                color: "var(--brand-blue)",
                fontWeight: 500,
                lineHeight: 1.4,
              }}
            >
              {name}
            </Link>
            <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
              {customer?.name ?? `客户 #${record.customer_id}`} · 编号 {record.code}
            </div>
          </div>
        );
      },
    },
    {
      title: "模型",
      key: "platforms",
      width: 130,
      render: (_, record) => {
        const d = details[record.id];
        const count = d?.platforms?.length ?? 0;
        if (count === 0) {
          return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        }
        return (
          <Tooltip title={d!.platforms.join("、")}>
            <Tag color="blue">{count} 个</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: "调度",
      key: "scheduleEnabled",
      width: 90,
      render: (_, record) => (
        <Switch
          checked={record.schedule_enabled}
          onChange={(v) => onToggle(record, v)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      ),
    },
    {
      title: "下一执行",
      dataIndex: "next_run_at",
      width: 170,
      render: (v: string | null, record) => {
        if (!record.schedule_enabled) {
          return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        }
        return (
          <span style={{ color: "var(--brand-blue)", fontSize: 13 }}>
            {formatTime(v)}
          </span>
        );
      },
    },
    {
      title: "最近一次",
      key: "lastRun",
      width: 110,
      render: (_, record) => {
        const r = details[record.id]?.lastRun;
        if (!r) {
          return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        }
        return <StatusTag status={r.status} />;
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 180,
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            onClick={() => navigate(`/admin/projects/${record.id}`)}
          >
            打开
          </Button>
          <Button
            size="small"
            type="link"
            icon={<ThunderboltOutlined />}
            onClick={() => onTrigger(record)}
          >
            立即执行
          </Button>
        </Space>
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
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>项目管理</h1>
          <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginTop: 4 }}>
            配置监控问题、模型与每日调度时间
          </div>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
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
          }}
        >
          <Input.Search
            placeholder="搜索项目名 / 编号"
            allowClear
            style={{ width: 240 }}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={(v) => setKeyword(v)}
          />
          <Select
            placeholder="全部客户"
            allowClear
            style={{ width: 200 }}
            value={customerFilter}
            onChange={(v) => setCustomerFilter(v)}
            options={customers.map((c) => ({ value: c.id, label: c.name }))}
            showSearch
            optionFilterProp="label"
          />
          <Select
            placeholder="项目状态"
            allowClear
            style={{ width: 140 }}
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            options={[
              { value: "active", label: "启用" },
              { value: "disabled", label: "停用" },
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
            showTotal: (t) => `共 ${t} 个项目`,
            onChange: (p) => {
              setPage(p);
              load(p);
            },
          }}
        />
      </Card>

      <Modal
        open={createOpen}
        title="新建项目"
        okText="创建"
        cancelText="取消"
        onCancel={() => setCreateOpen(false)}
        onOk={onCreate}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="customer_id"
            label="所属客户"
            rules={[{ required: true, message: "请选择客户" }]}
          >
            <Select
              placeholder="选择客户"
              options={customers.map((c) => ({ value: c.id, label: c.name }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: "请输入项目名称" }]}
          >
            <Input placeholder="例如:品牌形象监控" />
          </Form.Item>
          <Form.Item
            name="code"
            label="项目编号"
            rules={[{ required: true, message: "请输入项目编号" }]}
          >
            <Input placeholder="客户内唯一,例如 PROJ-0001" />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea rows={3} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
