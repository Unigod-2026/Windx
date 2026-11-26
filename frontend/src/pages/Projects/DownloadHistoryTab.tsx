/**
 * 下载历史 —— 项目级 tab,列出后台生成的导出任务。
 *
 * 导出在后台进程跑(可能几分钟),所以这一页要做两件事:
 *   1. 让人随时看到任务到哪一步了 —— 进行中的状态带脉冲点,不用盯着;
 *   2. 完成后一键下载,失败时能看到原因并原地重试。
 *
 * 见 docs/superpowers/specs/2026-11-26-export-mention-rate-design.md。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Space, Spin, Table, Tag, message } from "antd";
import type { TableColumnsType } from "antd";
import {
  createExport,
  deleteExport,
  downloadExport,
  getExport,
  listExports,
  type ExportParamsPayload,
  type ExportTaskSummary,
} from "../../api/exports";
import {
  exportStatusLabel,
  exportStatusTone,
  isExportActive,
} from "./exportStatus";
import "./DownloadHistoryTab.css";

interface Props {
  projectId: number;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(task: ExportTaskSummary): string {
  if (!task.started_at) return "—";
  const end = task.finished_at
    ? new Date(task.finished_at).getTime()
    : Date.now();
  const seconds = Math.max(
    0,
    Math.round((end - new Date(task.started_at).getTime()) / 1000),
  );
  if (seconds < 60) return `${seconds} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export default function DownloadHistoryTab({ projectId }: Props) {
  const [tasks, setTasks] = useState<ExportTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  // 轮询定时器挂在 ref 上 —— 组件卸载时要清掉,否则会对着已卸载的组件 setState。
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // load 返回这一轮的列表 —— 轮询循环靠返回值判断「还有没有进行中的任务」,
  // 不靠 state(state 更新和 await 之间的时序不可靠)。
  const load = useCallback(async (): Promise<ExportTaskSummary[]> => {
    try {
      const data = await listExports(projectId);
      setTasks(data.items);
      setError(null);
      return data.items;
    } catch (err) {
      setError((err as Error).message || "加载下载历史失败");
      return [];
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // 有进行中的任务就每 3 秒轮询一次,全部终态后停 —— 别一直空转。
  // 依赖只有 load(projectId 变了才重建),不依赖 tasks,否则每次 setTasks
  // 都会重建 effect 变成死循环。
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      const items = await load();
      if (cancelled) return;
      if (items.some((t) => isExportActive(t.status))) {
        timerRef.current = setTimeout(tick, 3000);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [load]);

  const handleDownload = async (task: ExportTaskSummary) => {
    setBusyId(task.id);
    try {
      await downloadExport(task.id, task.file_name || `导出_${task.id}.xlsx`);
      message.success("已下载");
    } catch (err) {
      message.error((err as Error).message || "下载失败");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (task: ExportTaskSummary) => {
    setBusyId(task.id);
    try {
      await deleteExport(task.id);
      message.success("已删除");
      await load();
    } catch (err) {
      message.error((err as Error).message || "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  const handleRetry = async (task: ExportTaskSummary) => {
    setBusyId(task.id);
    try {
      // 列表接口不返回 params(那是详情接口的字段)—— 先取详情拿到当初的
      // 筛选快照,再按同样的条件重提一个任务。
      const detail = await getExport(task.id);
      await createExport(
        projectId,
        detail.params as unknown as ExportParamsPayload,
      );
      message.success("已重新提交");
      await load();
    } catch (err) {
      message.error((err as Error).message || "重新提交失败");
    } finally {
      setBusyId(null);
    }
  };

  const columns: TableColumnsType<ExportTaskSummary> = [
    {
      title: "提交时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => (
        <span className="dlt-num">{new Date(v).toLocaleString("zh-CN")}</span>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 120,
      render: (v: string) =>
        isExportActive(v) ? (
          <span>
            <span className="dlt-pulse" aria-hidden="true" />
            {exportStatusLabel(v)}
          </span>
        ) : (
          <Tag color={exportStatusTone(v)}>{exportStatusLabel(v)}</Tag>
        ),
    },
    {
      title: "耗时",
      key: "duration",
      width: 110,
      render: (_, row) => (
        <span className="dlt-num">{formatDuration(row)}</span>
      ),
    },
    {
      title: "文件大小",
      dataIndex: "file_size",
      width: 100,
      render: (v: number | null) => (
        <span className="dlt-num">{formatSize(v)}</span>
      ),
    },
    {
      title: "说明",
      key: "note",
      render: (_, row) =>
        row.status === "failed" ? (
          <span title={row.error || undefined}>{row.error || "生成失败"}</span>
        ) : row.file_expired ? (
          "文件已过期"
        ) : null,
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_, row) => (
        <Space size={4}>
          {row.status === "success" && !row.file_expired && (
            <Button
              size="small"
              type="link"
              loading={busyId === row.id}
              onClick={() => void handleDownload(row)}
            >
              下载
            </Button>
          )}
          {row.status === "failed" && (
            <Button
              size="small"
              type="link"
              loading={busyId === row.id}
              onClick={() => void handleRetry(row)}
            >
              重试
            </Button>
          )}
          {row.status !== "pending" && row.status !== "running" && (
            <Button
              size="small"
              type="link"
              danger
              loading={busyId === row.id}
              onClick={() => void handleDelete(row)}
            >
              删除
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const activeCount = tasks.filter((t) => isExportActive(t.status)).length;
  const doneCount = tasks.filter((t) => t.status === "success").length;

  return (
    <div className="dlt">
      <div className="dlt-head">
        <div className="dlt-title">下载历史</div>
        <div className="dlt-sub">
          导出在后台生成，文件准备好后可以在这里下载。生成中的任务不会阻塞页面，超过
          7 天的文件会自动清理。
        </div>
      </div>

      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      )}

      {tasks.length > 0 && (
        <div className="dlt-counts">
          正在生成 {activeCount} 个 · 已完成 {doneCount} 个 · 共{" "}
          {tasks.length} 个
        </div>
      )}

      <Spin spinning={loading}>
        {tasks.length === 0 && !loading ? (
          <Empty description="还没有导出记录" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            columns={columns}
            dataSource={tasks}
            pagination={{ pageSize: 10, size: "small" }}
          />
        )}
      </Spin>
    </div>
  );
}
