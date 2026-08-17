import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Empty,
  Modal,
  Progress,
  Spin,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  CaretDownOutlined,
  CaretRightOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import {
  getTaskSubtasks,
  getTasks,
  type ProjectTaskOut,
  type SubtaskOut,
} from "../../api/projects";

interface Props {
  open: boolean;
  projectId: number | undefined;
  projectName: string;
  onClose: () => void;
}

const STATUS_TAG: Record<string, { color: string; bg: string; text: string }> = {
  pending: { color: "#6b7280", bg: "#f3f4f6", text: "等待中" },
  processing: { color: "#2563eb", bg: "#dbeafe", text: "进行中" },
  assigned: { color: "#2563eb", bg: "#dbeafe", text: "已派发" },
  completed: { color: "#16a34a", bg: "#dcfce7", text: "已完成" },
  partial_completed: { color: "#ea580c", bg: "#ffedd5", text: "部分完成" },
  failed: { color: "#dc2626", bg: "#fee2e2", text: "失败" },
  stopped: { color: "#6b7280", bg: "#f3f4f6", text: "已停止" },
  error: { color: "#dc2626", bg: "#fee2e2", text: "异常" },
};

const SUBTASK_TAG: Record<string, { color: string; bg: string; text: string }> = {
  pending: { color: "#6b7280", bg: "#f3f4f6", text: "等待中" },
  processing: { color: "#2563eb", bg: "#dbeafe", text: "进行中" },
  completed: { color: "#16a34a", bg: "#dcfce7", text: "已完成" },
  failed: { color: "#dc2626", bg: "#fee2e2", text: "失败" },
};

function StatusBadge({
  status,
  map = STATUS_TAG,
}: {
  status: string | null | undefined;
  map?: Record<string, { color: string; bg: string; text: string }>;
}) {
  const cfg = map[status ?? ""] ?? {
    color: "#6b7280",
    bg: "#f3f4f6",
    text: status ?? "-",
  };
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

function taskProgress(task: ProjectTaskOut): number {
  const total = task.total_items ?? 0;
  if (total <= 0) return 0;
  const done = (task.completed_items ?? 0) + (task.failed_items ?? 0);
  return Math.min(100, Math.round((done / total) * 100));
}

function formatDateTime(v: string | null): string {
  if (!v) return "-";
  const d = dayjs(v);
  return d.isValid() ? d.format("MM-DD HH:mm:ss") : v;
}

export default function TaskDetailModal({
  open,
  projectId,
  projectName,
  onClose,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<ProjectTaskOut[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [subtasksByTask, setSubtasksByTask] = useState<
    Record<string, SubtaskOut[]>
  >({});
  const [subtasksLoading, setSubtasksLoading] = useState<
    Record<string, boolean>
  >({});

  // Filter to the last 7 days (calendar days, server local time) and
  // sort newest-first so the most recent run sits at the top.
  const recentTasks = useMemo(() => {
    const cutoff = dayjs().subtract(7, "day");
    return tasks
      .filter((t) => {
        if (!t.created_local_at) return true;
        return dayjs(t.created_local_at).isAfter(cutoff);
      })
      .sort((a, b) => {
        const ta = a.created_local_at ? dayjs(a.created_local_at).valueOf() : 0;
        const tb = b.created_local_at ? dayjs(b.created_local_at).valueOf() : 0;
        return tb - ta;
      });
  }, [tasks]);

  useEffect(() => {
    if (!open || projectId === undefined) return;
    setLoading(true);
    setExpanded({});
    setSubtasksByTask({});
    getTasks(projectId, { page: 1, size: 100 })
      .then((res) => setTasks(res.items))
      .catch((err: Error) => message.error(err.message || "加载失败"))
      .finally(() => setLoading(false));
  }, [open, projectId]);

  const toggle = async (task: ProjectTaskOut) => {
    const isOpen = expanded[task.task_id];
    setExpanded((prev) => ({ ...prev, [task.task_id]: !prev[task.task_id] }));
    if (!isOpen && !subtasksByTask[task.task_id] && projectId !== undefined) {
      setSubtasksLoading((prev) => ({ ...prev, [task.task_id]: true }));
      try {
        const res = await getTaskSubtasks(projectId, task.task_id);
        setSubtasksByTask((prev) => ({ ...prev, [task.task_id]: res.items }));
      } catch (err) {
        message.error((err as Error).message || "加载子任务失败");
      } finally {
        setSubtasksLoading((prev) => ({ ...prev, [task.task_id]: false }));
      }
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={960}
      title={null}
      destroyOnClose
    >
      <div style={{ padding: "4px 4px 16px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            marginBottom: 4,
          }}
        >
          <h2
            style={{
              fontSize: 18,
              fontWeight: 600,
              margin: 0,
              color: "var(--text-primary)",
            }}
          >
            任务详情
          </h2>
          <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
            {projectName} · 近 7 天
          </span>
        </div>
        <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
          点击行可展开子任务列表,查看每条子任务的模型 / prompt / 错误信息
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin />
        </div>
      ) : recentTasks.length === 0 ? (
        <Empty description="近 7 天暂无任务" />
      ) : (
        <div
          style={{
            border: "1px solid var(--border-color, #e5e7eb)",
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "32px 130px 110px 1fr 160px 160px",
              padding: "10px 14px",
              background: "var(--bg-secondary, #f9fafb)",
              fontSize: 12,
              fontWeight: 600,
              color: "var(--text-tertiary)",
              borderBottom: "1px solid var(--border-color, #e5e7eb)",
            }}
          >
            <div />
            <div>task_id</div>
            <div>状态</div>
            <div>进度</div>
            <div>创建时间</div>
            <div>完成时间</div>
          </div>

          {recentTasks.map((task) => {
            const isOpen = !!expanded[task.task_id];
            const subs = subtasksByTask[task.task_id];
            const isLoadingSubs = !!subtasksLoading[task.task_id];
            const total = task.total_items ?? 0;
            const completed = task.completed_items ?? 0;
            const failed = task.failed_items ?? 0;
            return (
              <div key={task.task_id}>
                <div
                  onClick={() => toggle(task)}
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "32px 130px 110px 1fr 160px 160px",
                    padding: "12px 14px",
                    fontSize: 13,
                    cursor: "pointer",
                    borderBottom: isOpen
                      ? "1px dashed var(--border-color, #e5e7eb)"
                      : "1px solid var(--border-color, #e5e7eb)",
                    background: isOpen
                      ? "var(--bg-secondary, #f9fafb)"
                      : "transparent",
                    alignItems: "center",
                  }}
                >
                  <div style={{ color: "var(--text-tertiary)" }}>
                    {isOpen ? <CaretDownOutlined /> : <CaretRightOutlined />}
                  </div>
                  <Tooltip title={task.task_id}>
                    <div
                      style={{
                        fontFamily:
                          "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {task.task_id.slice(0, 8)}…
                    </div>
                  </Tooltip>
                  <div>
                    <StatusBadge status={task.status} />
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Progress
                      percent={taskProgress(task)}
                      size="small"
                      style={{ flex: 1, margin: 0 }}
                      strokeColor={
                        task.status === "failed" || failed > 0
                          ? "#dc2626"
                          : "var(--brand-blue, #2563eb)"
                      }
                      showInfo={false}
                    />
                    <span
                      style={{
                        fontSize: 12,
                        color: "var(--text-secondary)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {completed}/{total || "?"}
                      {failed > 0 ? (
                        <span style={{ color: "#dc2626" }}> · 失败 {failed}</span>
                      ) : null}
                    </span>
                  </div>
                  <div style={{ color: "var(--text-secondary)" }}>
                    {formatDateTime(task.created_local_at)}
                  </div>
                  <div style={{ color: "var(--text-secondary)" }}>
                    {formatDateTime(task.remote_completed_at)}
                  </div>
                </div>

                {isOpen && (
                  <div
                    style={{
                      padding: "8px 14px 16px 60px",
                      background: "var(--bg-secondary, #fafafa)",
                      borderBottom: "1px solid var(--border-color, #e5e7eb)",
                    }}
                  >
                    {isLoadingSubs ? (
                      <Spin size="small" />
                    ) : !subs || subs.length === 0 ? (
                      <div
                        style={{
                          fontSize: 12,
                          color: "var(--text-tertiary)",
                          padding: "8px 0",
                        }}
                      >
                        暂无子任务详情(可能仍在派发中)
                      </div>
                    ) : (
                      <div style={{ display: "grid", gap: 8 }}>
                        {subs.map((s) => (
                          <div
                            key={s.subtask_id}
                            style={{
                              padding: 10,
                              borderRadius: 6,
                              border:
                                "1px solid var(--border-color, #e5e7eb)",
                              background: "#ffffff",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                gap: 12,
                                alignItems: "center",
                                flexWrap: "wrap",
                              }}
                            >
                              <StatusBadge status={s.status} map={SUBTASK_TAG} />
                              <Tag
                                color="blue"
                                style={{ margin: 0, fontSize: 12 }}
                              >
                                {s.platform ?? "?"}
                              </Tag>
                              <Tag
                                color="default"
                                style={{ margin: 0, fontSize: 12 }}
                              >
                                {s.mode ?? "?"}
                              </Tag>
                              <Tooltip title={s.subtask_id}>
                                <span
                                  style={{
                                    fontFamily:
                                      "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
                                    fontSize: 11,
                                    color: "var(--text-tertiary)",
                                  }}
                                >
                                  {s.subtask_id.slice(0, 8)}…
                                </span>
                              </Tooltip>
                              {s.page_screenshot ? (
                                <a
                                  href={s.page_screenshot}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ fontSize: 12 }}
                                >
                                  <LinkOutlined /> 截图
                                </a>
                              ) : null}
                            </div>
                            <div
                              style={{
                                marginTop: 6,
                                fontSize: 13,
                                color: "var(--text-primary)",
                                lineHeight: 1.5,
                              }}
                            >
                              {s.prompt ?? "(无 prompt)"}
                            </div>
                            {s.error_message ? (
                              <div
                                style={{
                                  marginTop: 6,
                                  fontSize: 12,
                                  color: "#dc2626",
                                  background: "#fef2f2",
                                  padding: "6px 10px",
                                  borderRadius: 4,
                                  whiteSpace: "pre-wrap",
                                  wordBreak: "break-word",
                                }}
                              >
                                {s.error_message}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: 16, textAlign: "right" }}>
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  );
}