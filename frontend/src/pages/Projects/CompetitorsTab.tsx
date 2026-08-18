import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
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
import {
  createCompetitor,
  deleteCompetitor,
  listCompetitors,
  updateCompetitor,
  type CompetitorOrigin,
  type CompetitorOut,
  type CompetitorPayload,
  type CompetitorStatus,
} from "../../api/projects";
import AliasEditModal from "./AliasEditModal";

interface Props {
  projectId: number;
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

/**
 * 竞品管理 — 列出竞品 + Agent 自动发现。
 *
 * 顶部 Segmented 切换 "全部 / 手动 / Agent 发现"。底部表格 + 操作
 * 与 index.html 的 cmanage tab 一致(别名通过 AliasEditModal 弹窗
 * 编辑)。
 */
export default function CompetitorsTab({ projectId }: Props) {
  const [items, setItems] = useState<CompetitorOut[]>([]);
  const [, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [editOpen, setEditOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [aliasOpen, setAliasOpen] = useState<{ id: number; initial: string[] } | null>(null);
  const [form] = Form.useForm<CompetitorPayload>();

  const reload = async () => {
    setLoading(true);
    try {
      const data = await listCompetitors(projectId);
      setItems(data.items);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
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
    const pending = items.filter((c) => c.status === "pending").length;
    return { total, manual, auto, pending };
  }, [items]);

  const openCreate = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({ origin: "manual", status: "confirmed" });
    setEditOpen(true);
  };

  const openEdit = (c: CompetitorOut) => {
    setEditingId(c.id);
    form.setFieldsValue({
      name: c.name,
      note: c.note,
      aliases: c.aliases ?? [],
      origin: c.origin,
      status: c.status,
    });
    setEditOpen(true);
  };

  const onSave = async () => {
    try {
      const v = await form.validateFields();
      const payload: CompetitorPayload = {
        name: v.name.trim(),
        note: v.note?.trim() || null,
        aliases: v.aliases ?? [],
        origin: v.origin ?? "manual",
        status: v.status ?? "confirmed",
      };
      if (editingId === null) {
        await createCompetitor(projectId, payload);
        message.success("已新增");
      } else {
        await updateCompetitor(projectId, editingId, payload);
        message.success("已保存");
      }
      setEditOpen(false);
      await reload();
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
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
          message.success("已删除");
          await reload();
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
      message.success("已确认");
      await reload();
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
      message.success("已忽略");
      await reload();
    } catch (err) {
      message.error((err as Error).message || "操作失败");
    }
  };

  const onSaveAliases = async (next: string[]) => {
    if (!aliasOpen) return;
    const target = items.find((c) => c.id === aliasOpen.id);
    if (!target) return;
    try {
      await updateCompetitor(projectId, target.id, {
        ...target,
        aliases: next,
      });
      message.success("已保存别名");
      setAliasOpen(null);
      await reload();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
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
          <Tooltip title="编辑别名">
            <Button
              type="text"
              size="small"
              onClick={() =>
                setAliasOpen({ id: record.id, initial: record.aliases ?? [] })
              }
            >
              别名
            </Button>
          </Tooltip>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as FilterTab)}
          options={[
            { label: `全部 (${counts.total})`, value: "all" },
            { label: `手动 (${counts.manual})`, value: "manual" },
            { label: `Agent 发现 (${counts.auto})`, value: "auto_discovered" },
          ]}
        />
        {counts.pending > 0 && filter === "auto_discovered" && (
          <span style={{ fontSize: 13, color: "#ea580c" }}>
            有 {counts.pending} 个待确认的自动发现竞品
          </span>
        )}
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreate}
          style={{ background: "var(--brand-blue)", borderColor: "var(--brand-blue)" }}
        >
          新增竞品
        </Button>
      </div>

      <Card styles={{ body: { padding: 0 } }}>
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
          >
            {filter !== "auto_discovered" && (
              <Button type="primary" onClick={openCreate} icon={<PlusOutlined />}>
                新增竞品
              </Button>
            )}
          </Empty>
        ) : (
          <Table
            rowKey="id"
            size="middle"
            dataSource={filtered}
            columns={columns}
            pagination={false}
          />
        )}
      </Card>

      <Modal
        open={editOpen}
        title={editingId === null ? "新增竞品" : "编辑竞品"}
        okText="保存"
        cancelText="取消"
        onCancel={() => setEditOpen(false)}
        onOk={onSave}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="品牌名称"
            rules={[{ required: true, message: "请输入品牌名" }]}
          >
            <Input placeholder="例如:珂润 Curel" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input placeholder="选填,例如:品类 / 渠道 / 重点关注点" />
          </Form.Item>
          <Form.Item name="aliases" label="别名(用于 AI 回答中的同义召回)">
            <Select
              mode="tags"
              placeholder="按 Enter 添加多个别名"
              tokenSeparators={[","]}
            />
          </Form.Item>
          <div style={{ display: "flex", gap: 12 }}>
            <Form.Item name="origin" label="添加方式" style={{ flex: 1 }}>
              <Select
                options={[
                  { value: "manual", label: "手动添加" },
                  { value: "auto_discovered", label: "Agent 发现" },
                ]}
              />
            </Form.Item>
            <Form.Item name="status" label="状态" style={{ flex: 1 }}>
              <Select
                options={[
                  { value: "confirmed", label: "已确认" },
                  { value: "pending", label: "待确认" },
                  { value: "dismissed", label: "已忽略" },
                ]}
              />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <AliasEditModal
        open={aliasOpen !== null}
        title={
          aliasOpen
            ? `「${items.find((c) => c.id === aliasOpen.id)?.name ?? ""}」的别名`
            : ""
        }
        initial={aliasOpen?.initial ?? []}
        onCancel={() => setAliasOpen(null)}
        onConfirm={onSaveAliases}
      />
    </div>
  );
}
