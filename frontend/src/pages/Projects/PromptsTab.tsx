import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Empty,
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
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import {
  getProject,
  putPrompts,
  type PromptInPayload,
  type PromptOut,
  type ProjectDetailOut,
} from "../../api/projects";

interface Props {
  projectId: number;
}

const STATUS_LABELS: Record<PromptOut["status"], { text: string; color: string }> = {
  monitoring: { text: "监控中", color: "green" },
  paused: { text: "已暂停", color: "orange" },
  archived: { text: "已归档", color: "default" },
};

/**
 * 问题管理 — 列出当前项目的所有监控问题,支持新增/编辑/状态切换。
 * Persists the entire list via ``PUT /prompts`` (full-replace per the
 * existing API contract).
 */
export default function PromptsTab({ projectId }: Props) {
  const [detail, setDetail] = useState<ProjectDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState<PromptInPayload>({
    prompt: "",
    category: null,
    status: "monitoring",
  });

  const reload = async () => {
    setLoading(true);
    try {
      const data = await getProject(projectId);
      setDetail(data);
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

  const prompts = useMemo(() => detail?.prompts ?? [], [detail]);

  const persist = async (next: PromptOut[]) => {
    try {
      await putPrompts(
        projectId,
        next.map((p) => ({
          prompt: p.prompt,
          category: p.category ?? null,
          status: p.status,
        })),
      );
      message.success("已保存");
      await reload();
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const openCreate = () => {
    setEditingIndex(null);
    setDraft({ prompt: "", category: null, status: "monitoring" });
    setEditOpen(true);
  };

  const openEdit = (idx: number) => {
    const p = prompts[idx];
    setEditingIndex(idx);
    setDraft({
      prompt: p.prompt,
      category: p.category ?? null,
      status: p.status,
    });
    setEditOpen(true);
  };

  const onSaveDraft = async () => {
    const trimmed = draft.prompt.trim();
    if (!trimmed) {
      message.warning("请输入问题内容");
      return;
    }
    const next = [...prompts];
    const entry: PromptOut = {
      id: editingIndex !== null ? next[editingIndex].id : 0,
      prompt: trimmed,
      category: draft.category ?? null,
      status: draft.status ?? "monitoring",
      sort:
        editingIndex !== null
          ? next[editingIndex].sort
          : (next[next.length - 1]?.sort ?? 0) + 1,
    };
    if (editingIndex === null) {
      next.push(entry);
    } else {
      next[editingIndex] = entry;
    }
    setEditOpen(false);
    await persist(next);
  };

  const onDelete = (idx: number) => {
    Modal.confirm({
      title: "删除问题",
      content: `确认删除「${prompts[idx].prompt}」?`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        const next = prompts.filter((_, i) => i !== idx);
        await persist(next);
      },
    });
  };

  const toggleStatus = async (idx: number, next: PromptOut["status"]) => {
    const updated = [...prompts];
    updated[idx] = { ...updated[idx], status: next };
    await persist(updated);
  };

  const columns: ColumnsType<PromptOut> = [
    {
      title: "问题",
      dataIndex: "prompt",
      ellipsis: true,
      render: (text, record) => (
        <div>
          <div style={{ fontWeight: 500 }}>{text}</div>
          {record.category && (
            <Tag color="blue" style={{ marginTop: 4 }}>
              {record.category}
            </Tag>
          )}
        </div>
      ),
    },
    {
      title: "分类",
      dataIndex: "category",
      width: 120,
      render: (v) => (v ? <Tag color="blue">{v}</Tag> : <span style={{ color: "var(--text-quaternary)" }}>—</span>),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 140,
      render: (status: PromptOut["status"], _record, idx) => {
        const meta = STATUS_LABELS[status];
        return (
          <Select
            value={status}
            onChange={(v) => toggleStatus(idx!, v)}
            style={{ width: 120 }}
            options={[
              { value: "monitoring", label: "监控中" },
              { value: "paused", label: "已暂停" },
              { value: "archived", label: "已归档" },
            ]}
            tagRender={() => (
              <Tag color={meta.color} style={{ margin: 0 }}>
                {meta.text}
              </Tag>
            )}
          />
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 110,
      render: (_v, _r, idx) => (
        <Space size={4}>
          <Tooltip title="编辑">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEdit(idx!)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => onDelete(idx!)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  if (loading && !detail) {
    return <Card loading />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
          共 {prompts.length} 个监控问题 · 修改后立即生效
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreate}
          style={{ background: "var(--brand-blue)", borderColor: "var(--brand-blue)" }}
        >
          新建问题
        </Button>
      </div>

      <Card styles={{ body: { padding: 0 } }}>
        {prompts.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="尚未配置监控问题"
            style={{ padding: 32 }}
          >
            <Button type="primary" onClick={openCreate} icon={<PlusOutlined />}>
              新建问题
            </Button>
          </Empty>
        ) : (
          <Table
            rowKey="id"
            size="middle"
            dataSource={prompts}
            columns={columns}
            pagination={false}
          />
        )}
      </Card>

      <Modal
        open={editOpen}
        title={editingIndex === null ? "新建问题" : "编辑问题"}
        okText="保存"
        cancelText="取消"
        onCancel={() => setEditOpen(false)}
        onOk={onSaveDraft}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <div>
            <div style={{ marginBottom: 4, fontSize: 13 }}>问题内容</div>
            <Input.TextArea
              autoFocus
              rows={3}
              value={draft.prompt}
              onChange={(e) =>
                setDraft((d) => ({ ...d, prompt: e.target.value }))
              }
              placeholder="例如:敏感肌护肤品牌推荐"
            />
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ marginBottom: 4, fontSize: 13 }}>分类标签</div>
              <Select
                allowClear
                placeholder={
                  (detail?.category_taxonomy ?? []).length > 0
                    ? "选择或留空"
                    : "请先在「编辑监控项目」里配置分类"
                }
                style={{ width: "100%" }}
                value={draft.category ?? undefined}
                onChange={(v) =>
                  setDraft((d) => ({ ...d, category: v ?? null }))
                }
                options={(detail?.category_taxonomy ?? []).map((c) => ({
                  value: c,
                  label: c,
                }))}
              />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ marginBottom: 4, fontSize: 13 }}>状态</div>
              <Select
                style={{ width: "100%" }}
                value={draft.status}
                onChange={(v) =>
                  setDraft((d) => ({
                    ...d,
                    status: v as PromptOut["status"],
                  }))
                }
                options={[
                  { value: "monitoring", label: "监控中" },
                  { value: "paused", label: "已暂停" },
                  { value: "archived", label: "已归档" },
                ]}
              />
            </div>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            <Switch
              size="small"
              checked={draft.status === "monitoring"}
              onChange={(v) =>
                setDraft((d) => ({
                  ...d,
                  status: v ? "monitoring" : "paused",
                }))
              }
              style={{ marginRight: 6 }}
            />
            状态切换会同时保存(草稿态生效)
          </div>
        </Space>
      </Modal>
    </div>
  );
}
