/**
 * 自有文章引用分析 —— xlsx 导入 URL 列表 modal。
 *
 * 对应 index.html:1303 「导入 URL 列表」按钮。流程跟
 * :file:`./MediaDictionaryImportModal.tsx` 同款三段结构:
 * 1. 上传:antd Upload 接住 .xlsx,beforeUpload 调 preview 接口
 * 2. 预览:URL / 标题 / 发布日期 / 状态(新增|更新)表格 + 无效行折叠
 * 3. 确认:POST /import 单事务 upsert,返回 inserted / updated / total
 *
 * 字段差异:
 * - xlsx 列固定 3 列:URL / 标题 / 发布日期(YYYY-MM-DD,可空)
 * - preview / result shape 见 :file:`../api/projects.ts` 的
 *   ``OwnArticleImportPreview`` / ``OwnArticleImportResult``。
 */

import { useState } from "react";
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Modal,
  Spin,
  Table,
  Tag,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import {
  importOwnArticles,
  previewOwnArticlesImport,
  type OwnArticleImportPreview,
  type OwnArticleImportResult,
  type OwnArticleInvalidReason,
} from "../api/projects";

interface Props {
  projectId: number;
  open: boolean;
  onClose: () => void;
  onImported: (result: OwnArticleImportResult) => void;
}

type Phase = "idle" | "previewing" | "previewed" | "importing";

const REASON_LABEL: Record<OwnArticleInvalidReason, string> = {
  empty_url: "URL 缺失",
  invalid_url: "URL 无效(需含域名)",
  duplicate_in_file: "文件内重复",
};

const MAX_XLSX_BYTES = 5 * 1024 * 1024;

export default function OwnArticlesImportModal({
  projectId,
  open,
  onClose,
  onImported,
}: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [preview, setPreview] = useState<OwnArticleImportPreview | null>(null);
  const [importing, setImporting] = useState(false);
  const [stagedFile, setStagedFile] = useState<File | null>(null);

  const reset = () => {
    setPhase("idle");
    setPreview(null);
    setImporting(false);
    setStagedFile(null);
  };

  const handleClose = () => {
    if (importing) return;
    reset();
    onClose();
  };

  const uploadProps: UploadProps = {
    accept: ".xlsx",
    multiple: false,
    showUploadList: false,
    beforeUpload: async (file) => {
      if (!file.name.toLowerCase().endsWith(".xlsx")) {
        message.error("仅支持 .xlsx 文件");
        return Upload.LIST_IGNORE;
      }
      if (file.size > MAX_XLSX_BYTES) {
        message.error("文件超过 5MB 上限");
        return Upload.LIST_IGNORE;
      }
      setPhase("previewing");
      setStagedFile(file);
      try {
        const prev = await previewOwnArticlesImport(projectId, file);
        setPreview(prev);
        setPhase("previewed");
      } catch (err) {
        message.error((err as Error).message || "解析失败");
        setPhase("idle");
        setStagedFile(null);
      }
      return false;
    },
  };

  const handleImport = async () => {
    if (!stagedFile || !preview) return;
    if (preview.entries.length === 0) {
      message.warning("没有可导入的有效行");
      return;
    }
    setImporting(true);
    try {
      const result = await importOwnArticles(projectId, stagedFile);
      message.success(
        `导入完成:新增 ${result.inserted} 条,更新 ${result.updated} 条`,
      );
      onImported(result);
      reset();
      onClose();
    } catch (err) {
      message.error((err as Error).message || "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const entriesWithStatus = preview
    ? preview.entries.map((e) => ({
        ...e,
        status: preview.update_urls.includes(e.url) ? "更新" : "新增",
      }))
    : [];

  return (
    <Modal
      open={open}
      title="导入自有文章 URL 列表"
      okText={importing ? "导入中..." : "确认导入"}
      cancelText="取消"
      width={720}
      destroyOnHidden
      onCancel={handleClose}
      okButtonProps={{
        disabled:
          phase !== "previewed" || !preview || preview.entries.length === 0,
        loading: importing,
      }}
      onOk={handleImport}
    >
      {phase === "idle" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Alert
            type="info"
            showIcon
            message="支持格式"
            description="仅 .xlsx 文件,大小 5MB 以内。文件需包含三列:URL、标题、发布日期(YYYY-MM-DD,可空)。"
          />
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>选择 .xlsx 文件</Button>
          </Upload>
        </div>
      )}

      {(phase === "previewing" || phase === "previewed") && (
        <Spin spinning={phase === "previewing"} tip="解析中...">
          <PreviewBlock
            preview={preview}
            entriesWithStatus={entriesWithStatus}
            onChangeFile={() => {
              setPhase("idle");
              setPreview(null);
              setStagedFile(null);
            }}
          />
        </Spin>
      )}
    </Modal>
  );
}

interface PreviewBlockProps {
  preview: OwnArticleImportPreview | null;
  entriesWithStatus: Array<{
    url: string;
    title: string;
    publish_date: string | null;
    status: string;
  }>;
  onChangeFile: () => void;
}

function PreviewBlock({ preview, entriesWithStatus, onChangeFile }: PreviewBlockProps) {
  if (!preview) {
    return <Empty description="解析失败" />;
  }

  const newCount = preview.new_urls.length;
  const updateCount = preview.update_urls.length;
  const invalidCount = preview.invalid_rows.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          padding: "10px 14px",
          background: "var(--bg-page, #fafafa)",
          border: "1px solid var(--border-light, #f0f0f0)",
          borderRadius: 6,
        }}
      >
        <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          共解析 <strong>{entriesWithStatus.length}</strong> 条
        </span>
        <Tag color="green">新增 {newCount}</Tag>
        <Tag color="blue">更新 {updateCount}</Tag>
        {invalidCount > 0 && <Tag color="orange">无效 {invalidCount}</Tag>}
        <Button size="small" type="link" onClick={onChangeFile}>
          重新选择文件
        </Button>
      </div>

      {invalidCount > 0 && (
        <Collapse
          ghost
          items={[
            {
              key: "invalid",
              label: (
                <span style={{ color: "#fa8c16" }}>
                  查看 {invalidCount} 条无效行(将被跳过)
                </span>
              ),
              children: (
                <Table
                  size="small"
                  rowKey="row"
                  pagination={{ pageSize: 10, size: "small" }}
                  dataSource={preview.invalid_rows}
                  columns={[
                    { title: "行号", dataIndex: "row", width: 70 },
                    { title: "URL", dataIndex: "raw_url", ellipsis: true },
                    {
                      title: "原因",
                      dataIndex: "reason",
                      width: 160,
                      render: (r: OwnArticleInvalidReason) => REASON_LABEL[r] ?? r,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      )}

      <Table
        size="small"
        rowKey="url"
        pagination={{ pageSize: 10, size: "small" }}
        dataSource={entriesWithStatus}
        columns={[
          { title: "URL", dataIndex: "url", width: 280, ellipsis: true },
          { title: "标题", dataIndex: "title", ellipsis: true },
          {
            title: "发布日期",
            dataIndex: "publish_date",
            width: 120,
            render: (d: string | null) => d ?? "—",
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 80,
            render: (s: string) => (
              <Tag
                color={s === "新增" ? "green" : "blue"}
                style={{ margin: 0 }}
              >
                {s}
              </Tag>
            ),
          },
        ]}
      />
    </div>
  );
}
