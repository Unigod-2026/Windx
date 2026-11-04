/**
 * 导入历史 —— 左侧「数据中心」组下的项目级 tab。
 *
 * 每条记录 = 「一份文件内容 × 一个项目」的导入批次：
 *   - 导入出错时，这里能回看这次到底发生了什么（完整错误清单 + 一键复制）
 *   - 「撤销」把这次导入写入的行全部删掉，项目回到导入前
 *
 * 见 docs/superpowers/specs/2026-11-04-import-history-design.md。
 */

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  deleteImportBatch,
  getImportBatch,
  listImportBatches,
  type ImportBatchDetail,
  type ImportBatchSummary,
} from "../../api/imports";
import {
  apiErrorText,
  batchStatusLabel,
  batchStatusTone,
} from "./importPreview";
import ImportErrorGroups from "./ImportErrorGroups";
import "./ImportHistoryTab.css";

interface Props {
  projectId: number;
}

export default function ImportHistoryTab({ projectId }: Props) {
  const [batches, setBatches] = useState<ImportBatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ImportBatchDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  // 撤销目标单独锁一份 —— 连点两行时两次 fetch 是并发的，后返回的响应会
  // 覆盖共享的 detail，撤销就会删错批次（不可逆操作）。
  const [pending, setPending] = useState<ImportBatchDetail | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [undoing, setUndoing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listImportBatches(projectId);
      setBatches(data.items);
    } catch (err) {
      setError(apiErrorText(err, "加载导入历史失败"));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (batchId: string) => {
    try {
      const d = await getImportBatch(projectId, batchId);
      setDetail(d);
      setDetailOpen(true);
    } catch (err) {
      message.error(apiErrorText(err, "读取导入详情失败"));
    }
  };

  /** 列表里的「撤销」：取到影响数字后直接开确认框，不叠开详情框。
   *  取到的这份单独存进 pending —— 撤销只认 pending，不读共享的 detail。 */
  const openConfirm = async (batchId: string) => {
    try {
      const d = await getImportBatch(projectId, batchId);
      setPending(d);
      setConfirmOpen(true);
    } catch (err) {
      message.error(apiErrorText(err, "读取导入详情失败"));
    }
  };

  const handleUndo = async () => {
    if (!pending) return;
    setUndoing(true);
    try {
      await deleteImportBatch(projectId, pending.id);
      message.success("已撤销这次导入");
      setConfirmOpen(false);
      setDetailOpen(false);
      setDetail(null);
      setPending(null);
      await load();
    } catch (err) {
      message.error(apiErrorText(err, "撤销失败"));
    } finally {
      setUndoing(false);
    }
  };

  const columns: TableColumnsType<ImportBatchSummary> = [
    {
      title: "导入时间",
      dataIndex: "updated_at",
      width: 170,
      render: (v: string) => new Date(v).toLocaleString("zh-CN"),
    },
    {
      title: "文件名",
      dataIndex: "file_name",
      ellipsis: true,
      render: (v: string) => <span title={v}>{v}</span>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (v: string) => (
        <Tag color={batchStatusTone(v)}>{batchStatusLabel(v)}</Tag>
      ),
    },
    {
      title: "最近一次写入",
      dataIndex: "totals",
      width: 130,
      render: (t: Record<string, number>) => t.importable_rows ?? 0,
    },
    {
      title: "覆盖日期",
      dataIndex: "dates",
      width: 200,
      render: (d: string[]) => (d.length ? `${d[0]} ~ ${d[d.length - 1]}` : "—"),
    },
    {
      title: "操作",
      key: "actions",
      width: 140,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => openDetail(row.id)}>
            预览
          </Button>
          <Button
            size="small"
            type="link"
            danger
            onClick={() => openConfirm(row.id)}
          >
            撤销
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="imh">
      <div className="imh-head">
        <div className="imh-title">导入历史</div>
        <div className="imh-sub">
          每次导入都会留痕。导入出错时这里能看清被挡下的行与原因；导错了可以撤销，把项目恢复到导入前。
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

      <Spin spinning={loading}>
        {batches.length === 0 && !loading ? (
          <Empty description="还没有导入记录" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            columns={columns}
            dataSource={batches}
            pagination={{ pageSize: 10, size: "small" }}
          />
        )}
      </Spin>

      {/* ---- 详情 ---- */}
      <Modal
        open={detailOpen}
        title="导入详情"
        width={860}
        footer={[
          <Button key="close" onClick={() => setDetailOpen(false)}>
            关闭
          </Button>,
          <Button
            key="undo"
            type="primary"
            danger
            onClick={() => {
              setDetailOpen(false);
              void openConfirm(detail?.id ?? "");
            }}
          >
            撤销这次导入
          </Button>,
        ]}
        onCancel={() => setDetailOpen(false)}
      >
        {detail && (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="文件">{detail.file_name}</Descriptions.Item>
              <Descriptions.Item label="大小">
                {(detail.file_size / 1024).toFixed(1)} KB
              </Descriptions.Item>
              <Descriptions.Item label="内容哈希">
                {detail.file_hash.slice(0, 12)}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={batchStatusTone(detail.status)}>
                  {batchStatusLabel(detail.status)}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="导入人">
                {detail.created_by || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="导入次数">{detail.attempts} 次</Descriptions.Item>
              <Descriptions.Item label="最近导入">
                {new Date(detail.updated_at).toLocaleString("zh-CN")}
              </Descriptions.Item>
              <Descriptions.Item label="覆盖日期">
                {detail.dates.length ? detail.dates.join("、") : "—"}
              </Descriptions.Item>
            </Descriptions>

            <div className="imh-totals">
              解析 {detail.totals.total_rows ?? 0} · 可导入{" "}
              {detail.totals.importable_rows ?? 0} · 阻断{" "}
              {detail.totals.blocked_rows ?? 0} · 任务 {detail.totals.tasks ?? 0} ·
              子任务 {detail.totals.subtasks ?? 0} · 提及{" "}
              {detail.totals.brand_mentions ?? 0} · 引用{" "}
              {detail.totals.citations ?? 0}
            </div>

            {detail.warnings.length > 0 && (
              <Alert
                type="info"
                showIcon
                message="导入时的提示"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {detail.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                }
              />
            )}

            {detail.errors.length > 0 ? (
              <div>
                <div className="imh-section-title">
                  被阻断的行（{detail.totals.blocked_rows ?? 0} 行）
                </div>
                <ImportErrorGroups groups={detail.errors} />
              </div>
            ) : (
              <Alert type="success" showIcon message="这次导入没有阻断行" />
            )}
          </Space>
        )}
      </Modal>

      {/* ---- 撤销确认 ---- */}
      <Modal
        open={confirmOpen}
        title="撤销这次导入"
        okText="确认撤销"
        cancelText="取消"
        okButtonProps={{ danger: true, loading: undoing }}
        onCancel={() => setConfirmOpen(false)}
        onOk={handleUndo}
      >
        {pending && (
          <Space direction="vertical" size={8}>
            <Alert
              type="warning"
              showIcon
              message="撤销会永久删除这次导入写入的数据，无法撤销。"
            />
            <div className="imh-impact">
              将删除 <strong>{pending.delete_impact.tasks}</strong> 个任务、
              <strong>{pending.delete_impact.subtasks}</strong> 个子任务、
              <strong>{pending.delete_impact.brand_mentions}</strong> 条品牌提及、
              <strong>{pending.delete_impact.runs}</strong> 条执行记录。
            </div>
            <div className="imh-impact-hint">
              删除后项目会回到导入前的状态。重新导入同一份文件即可重新入库。
            </div>
          </Space>
        )}
      </Modal>
    </div>
  );
}
