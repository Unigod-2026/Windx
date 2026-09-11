// 待审核页面 —— 客户看到自己的「新建项目」申请,super_admin 看到全部。
//
// 设计原则:
// - 后端已按 session 强制 tenant 范围(``customer_admin`` 只看到自己的,
//   ``super_admin`` 看全部),前端不再二次过滤,只渲染。
// - 默认筛选 ``status=pending``,管理员进来先看到需要处理的;客户进来
//   默认看自己的待审核 + 最近的已处理结果。
// - 点品牌列 / 「查看」按钮 → 跳到项目详情页(``/admin/projects/{id}``),
//   编辑器组件按 ``status`` 自动决定读写权限;审批动作通过独立的
//   approve / reject / withdraw 操作处理(目前暂未挂到详情页 footer,后续
//   在 BatchQuestionModal 改造中接入)。

import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Empty,
  Select,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { listProjects, type ProjectOut } from "../../api/projects";
import { listCustomers, type Customer } from "../../api/customers";
import { useAuth } from "../../auth/AuthProvider";
import BatchQuestionModal from "../Projects/BatchQuestionModal";
import "./PendingProjectsList.css";

type ProjectLifecycleStatus = "pending" | "active" | "rejected" | "disabled";

const STATUS_META: Record<
  ProjectLifecycleStatus,
  { color: string; bg: string; text: string }
> = {
  pending: { color: "#d97706", bg: "#fef3c7", text: "待审核" },
  active: { color: "#16a34a", bg: "#dcfce7", text: "已通过" },
  rejected: { color: "#dc2626", bg: "#fee2e2", text: "已驳回" },
  disabled: { color: "#6b7280", bg: "#f3f4f6", text: "已停用" },
};

const STATUS_OPTIONS: { value: ProjectLifecycleStatus | ""; label: string }[] = [
  { value: "", label: "全部" },
  { value: "pending", label: "待审核" },
  { value: "active", label: "已通过" },
  { value: "rejected", label: "已驳回" },
];

export default function PendingProjectsList() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  // 点击行 / 「查看项目」直接打开 BatchQuestionModal —— 共用
  // 「监控项目」列表的详情体验(由 modal 自身根据 status/role
  // 分支展示审批 / 编辑 / 只读)。
  const [modalProjectId, setModalProjectId] = useState<number | undefined>(undefined);

  const [items, setItems] = useState<ProjectOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ProjectLifecycleStatus | "">(
    "pending",
  );

  const [customerMap, setCustomerMap] = useState<Record<number, Customer>>({});

  const customerMapMemo = useMemo(() => customerMap, [customerMap]);

  const loadCustomers = async () => {
    if (!isSuper) return;
    try {
      const data = await listCustomers({ page: 1, size: 200 });
      const m: Record<number, Customer> = {};
      data.items.forEach((c) => {
        m[c.id] = c;
      });
      setCustomerMap(m);
    } catch {
      // 静默 —— 列表只显示「客户 #id」回退字符串。
    }
  };

  const load = async (p = page) => {
    setLoading(true);
    try {
      // Pre-20260908_0002: ``listPendingProjects`` hit ``/api/pending-projects``
      // and returned shadow-table rows. The merged surface instead goes
      // through the project list with ``status=pending|active|rejected``.
      // ``active`` here covers the historical "approved" rows.
      const data = await listProjects({
        page: p,
        size: pageSize,
        status: (statusFilter || undefined) as
          | "pending"
          | "active"
          | "rejected"
          | "disabled"
          | undefined,
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
    loadCustomers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load(1);
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const goToProject = (id: number) => {
    setModalProjectId(id);
  };

  const columns: ColumnsType<ProjectOut> = [
    {
      title: "项目",
      dataIndex: "name",
      width: 220,
      render: (name: string, record) => (
        <button
          type="button"
          onClick={() => goToProject(record.id)}
          style={{
            background: "none",
            border: 0,
            padding: 0,
            color: "var(--brand-blue)",
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          {name || "(未填)"}
        </button>
      ),
    },
    {
      title: "客户",
      dataIndex: "customer_id",
      width: 160,
      render: (cid: number) => {
        const c = customerMapMemo[cid];
        return c ? c.name : `客户 #${cid}`;
      },
    },
    {
      title: "问题数",
      dataIndex: "prompts_count",
      width: 80,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: ProjectLifecycleStatus) => {
        const meta = STATUS_META[s] ?? STATUS_META.active;
        return (
          <span
            style={{
              display: "inline-block",
              padding: "1px 8px",
              borderRadius: 4,
              fontSize: 12,
              color: meta.color,
              background: meta.bg,
              fontWeight: 500,
              lineHeight: 1.6,
            }}
          >
            {meta.text}
          </span>
        );
      },
    },
    {
      title: "提交时间",
      dataIndex: "submitted_at",
      width: 160,
      render: (v: string | null) => {
        if (!v) return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        return dayjs(v).format("YYYY-MM-DD HH:mm");
      },
    },
    {
      title: "审核时间",
      dataIndex: "reviewed_at",
      width: 160,
      render: (v: string | null, record) => {
        if (!v) return <span style={{ color: "var(--text-quaternary)" }}>—</span>;
        return (
          <div>
            <div>{dayjs(v).format("YYYY-MM-DD HH:mm")}</div>
            {record.review_note && (
              <div
                style={{
                  fontSize: 12,
                  color: "var(--text-tertiary)",
                  marginTop: 2,
                  maxWidth: 220,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={record.review_note}
              >
                {record.review_note}
              </div>
            )}
          </div>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => goToProject(record.id)}
          >
            查看项目
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
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              margin: 0,
              color: "var(--text-primary)",
            }}
          >
            待审核项目
          </h1>
          <div
            style={{
              fontSize: 13,
              color: "var(--text-tertiary)",
              marginTop: 4,
            }}
          >
            {isSuper
              ? "审核客户提交的新建项目申请,通过后会创建真实项目。"
              : "查看您提交的新建项目申请的处理状态。"}
          </div>
        </div>
        <Space>
          <Select
            value={statusFilter}
            onChange={(v) => setStatusFilter(v as ProjectLifecycleStatus | "")}
            options={STATUS_OPTIONS}
            style={{ width: 120 }}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => load(page)}
            loading={loading}
          >
            刷新
          </Button>
        </Space>
      </div>

      <Card bordered={false} styles={{ body: { padding: 0 } }}>
        <Table<ProjectOut>
          rowKey="id"
          loading={loading}
          dataSource={items}
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
          locale={{
            emptyText: (
              <Empty
                description={
                  statusFilter
                    ? `暂无「${STATUS_META[statusFilter as ProjectLifecycleStatus]?.text ?? statusFilter}」的申请`
                    : "暂无申请"
                }
              />
            ),
          }}
        />
      </Card>

      <BatchQuestionModal
        open={modalProjectId !== undefined}
        projectId={modalProjectId}
        onClose={() => setModalProjectId(undefined)}
        onSaved={() => {
          // 审批 / 撤回 / 重新提交 / 保存草稿都会触发;刷新当前页列表。
          load(page);
        }}
      />
    </div>
  );
}
