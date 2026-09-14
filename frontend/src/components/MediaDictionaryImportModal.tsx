/**
 * 官方媒体字典导入 modal —— 三段结构:
 * 1. 上传:antd Upload 接住 .xlsx,beforeUpload 调 preview API,进入预览态
 * 2. 预览表格:host / media_name / category / 状态(新增|更新)
 *    + 无效行折叠提示(展开看 invalid_rows)
 * 3. 确认导入:POST /import,单事务 upsert,返回 inserted / updated / total
 *
 * Props 由父组件控制 open / onClose / onImported;
 * onImported 回调里父组件应刷新 dictTotal(用 listMediaDictionary())。
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
  importMediaDictionary,
  previewMediaDictionaryImport,
  type MediaDictionaryImportPreview,
  type MediaDictionaryImportResult,
  type MediaDictionaryInvalidReason,
} from "../api/admin";

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: (result: MediaDictionaryImportResult) => void;
}

type Phase = "idle" | "previewing" | "previewed" | "importing";

const REASON_LABEL: Record<MediaDictionaryInvalidReason, string> = {
  empty_host: "域名缺失",
  invalid_host: "域名无效(需含 .)",
  empty_name: "媒体名称缺失",
  empty_category: "媒体分类缺失",
  duplicate_in_file: "文件内重复",
};

export default function MediaDictionaryImportModal({
  open,
  onClose,
  onImported,
}: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [preview, setPreview] = useState<MediaDictionaryImportPreview | null>(null);
  const [importing, setImporting] = useState(false);
  // 保存最近一次上传的 File,确认导入时复用(避免重复解析)
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
      // 仅 .xlsx,后端会二次校验。
      if (!file.name.toLowerCase().endsWith(".xlsx")) {
        message.error("仅支持 .xlsx 文件");
        return Upload.LIST_IGNORE;
      }
      if (file.size > 5 * 1024 * 1024) {
        message.error("文件超过 5MB 上限");
        return Upload.LIST_IGNORE;
      }
      setPhase("previewing");
      setStagedFile(file);
      try {
        const prev = await previewMediaDictionaryImport(file);
        setPreview(prev);
        setPhase("previewed");
      } catch (err) {
        message.error((err as Error).message || "解析失败");
        setPhase("idle");
        setStagedFile(null);
      }
      return false; // 阻止 antd 自动上传
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
      const result = await importMediaDictionary(stagedFile);
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
        status: preview.update_hosts.includes(e.host) ? "更新" : "新增",
      }))
    : [];

  return (
    <Modal
      open={open}
      title="导入官方媒体字典"
      okText={importing ? "导入中..." : "确认导入"}
      cancelText="取消"
      width={720}
      destroyOnHidden
      onCancel={handleClose}
      okButtonProps={{
        disabled: phase !== "previewed" || !preview || preview.entries.length === 0,
        loading: importing,
      }}
      onOk={handleImport}
    >
      {/* 顶部:上传区(预览态下隐藏,因为已经选了文件) */}
      {phase === "idle" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Alert
            type="info"
            showIcon
            message="支持格式"
            description="仅 .xlsx 文件,大小 5MB 以内。文件需包含三列:域名、媒体名称、媒体分类(顺序不限)。"
          />
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>选择 .xlsx 文件</Button>
          </Upload>
        </div>
      )}

      {/* 预览态 */}
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
  preview: MediaDictionaryImportPreview | null;
  entriesWithStatus: Array<{
    host: string;
    media_name: string;
    category: string;
    status: string;
  }>;
  onChangeFile: () => void;
}

function PreviewBlock({ preview, entriesWithStatus, onChangeFile }: PreviewBlockProps) {
  if (!preview) {
    return <Empty description="解析失败" />;
  }

  const newCount = preview.new_hosts.length;
  const updateCount = preview.update_hosts.length;
  const invalidCount = preview.invalid_rows.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* 摘要条 */}
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
        {invalidCount > 0 && (
          <Tag color="orange">无效 {invalidCount}</Tag>
        )}
        <Button size="small" type="link" onClick={onChangeFile}>
          重新选择文件
        </Button>
      </div>

      {/* 无效行折叠提示 */}
      {invalidCount > 0 && (
        <Collapse
          ghost
          items={[
            {
              key: "invalid",
              label: <span style={{ color: "#fa8c16" }}>查看 {invalidCount} 条无效行(将被跳过)</span>,
              children: (
                <Table
                  size="small"
                  rowKey="row"
                  pagination={{ pageSize: 10, size: "small" }}
                  dataSource={preview.invalid_rows}
                  columns={[
                    { title: "行号", dataIndex: "row", width: 70 },
                    { title: "域名", dataIndex: "raw_host", ellipsis: true },
                    {
                      title: "原因",
                      dataIndex: "reason",
                      width: 130,
                      render: (r: MediaDictionaryInvalidReason) => REASON_LABEL[r] ?? r,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      )}

      {/* 预览表 */}
      <Table
        size="small"
        rowKey="host"
        pagination={{ pageSize: 10, size: "small" }}
        dataSource={entriesWithStatus}
        columns={[
          { title: "域名", dataIndex: "host", width: 200, ellipsis: true },
          { title: "媒体名称", dataIndex: "media_name", width: 180 },
          { title: "媒体分类", dataIndex: "category", width: 130 },
          {
            title: "状态",
            dataIndex: "status",
            width: 80,
            render: (s: string) => (
              <Tag color={s === "新增" ? "green" : "blue"} style={{ margin: 0 }}>
                {s}
              </Tag>
            ),
          },
        ]}
      />
    </div>
  );
}
