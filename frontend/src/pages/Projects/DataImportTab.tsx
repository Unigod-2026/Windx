/**
 * 数据导入 —— 项目级 tab，位于左侧菜单「数据中心」组下。
 *
 * 三段式：
 * 1. 上传：拖拽/点击选 .xlsx，beforeUpload 直接调 preview 接口
 * 2. 预览核对：对账条 + 三张 sheet 的分区统计 + 行级错误折叠
 * 3. 导入：按勾选的 sheet 落库，回填结果摘要
 *
 * 页面只消费后端返回的「事实数据」；项目配置（问题 / 竞品 / 模型 / 核心词）
 * 一律以项目现状为准，对不上的行进错误日志 —— 详见
 * docs/superpowers/specs/2026-11-04-data-import-design.md。
 */

import { useCallback, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Upload,
  message,
} from "antd";
import type { TableColumnsType, UploadProps } from "antd";
import { CloudUploadOutlined, CopyOutlined } from "@ant-design/icons";
import {
  applyImportData,
  previewImportData,
  type ImportErrorGroup,
  type ImportPreview,
  type ImportResult,
  type ImportSheetKey,
  type SheetPreview,
} from "../../api/imports";
import {
  apiErrorText,
  describeErrorGroup,
  describeTotals,
  sheetTone,
  toneLabel,
} from "./importPreview";
import "./DataImportTab.css";

type Phase = "idle" | "previewing" | "previewed" | "importing" | "done";

const MAX_BYTES = 10 * 1024 * 1024;

interface Props {
  projectId: number;
  projectName?: string;
  projectBrand?: string;
}

export default function DataImportTab({
  projectId,
  projectName,
  projectBrand,
}: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [selected, setSelected] = useState<ImportSheetKey[]>([]);
  // 切换勾选后的重新预览 —— 页面上的数字必须跟真正要写入的量一致
  const [repreviewing, setRepreviewing] = useState(false);

  const selectedCount = useMemo(() => {
    if (!preview) return 0;
    return preview.sheets
      .filter((s) => s.selected)
      .reduce((n, s) => n + s.importable_rows, 0);
  }, [preview]);

  const loadPreview = useCallback(
    async (f: File, sheets?: ImportSheetKey[]) => {
      const p = await previewImportData(projectId, f, sheets);
      setPreview(p);
      return p;
    },
    [projectId],
  );

  const uploadProps: UploadProps = {
    accept: ".xlsx",
    multiple: false,
    showUploadList: false,
    beforeUpload: async (f) => {
      if (!f.name.toLowerCase().endsWith(".xlsx")) {
        message.error("仅支持 .xlsx 文件");
        return Upload.LIST_IGNORE;
      }
      if (f.size > MAX_BYTES) {
        message.error("文件超过 10MB 上限");
        return Upload.LIST_IGNORE;
      }
      setPhase("previewing");
      setFile(f);
      try {
        const p = await loadPreview(f);
        setSelected(
          p.sheets.filter((s) => s.total_rows > 0).map((s) => s.key),
        );
        setPhase("previewed");
      } catch (err) {
        message.error(apiErrorText(err, "解析失败"));
        setPhase("idle");
        setFile(null);
      }
      return false; // 阻止 antd 自动上传
    },
  };

  /** 切换勾选 —— 重新预览，让「可导入 N 行」始终等于真正会写入的量。 */
  const handleToggle = async (key: ImportSheetKey, on: boolean) => {
    const next = on
      ? [...selected, key]
      : selected.filter((k) => k !== key);
    setSelected(next);
    if (!file) return;
    setRepreviewing(true);
    try {
      await loadPreview(file, next);
    } catch (err) {
      message.error(apiErrorText(err, "重新预览失败"));
    } finally {
      setRepreviewing(false);
    }
  };

  const handleApply = async () => {
    if (!file || !preview) return;
    if (selected.length === 0) {
      message.warning("至少选择一张 sheet");
      return;
    }
    setPhase("importing");
    try {
      const r = await applyImportData(projectId, file, selected);
      setResult(r);
      setPhase("done");
      message.success("导入完成");
    } catch (err) {
      message.error(apiErrorText(err, "导入失败"));
      setPhase("previewed");
    }
  };

  const reset = () => {
    setPhase("idle");
    setFile(null);
    setPreview(null);
    setResult(null);
    setSelected([]);
  };

  return (
    <div className="dit">
      {/* ---- 当前项目上下文：导入永远作用于当前选中的项目 ---- */}
      <div className="dit-context">
        <div className="dit-context-item">
          <span className="dit-context-label">当前项目</span>
          <span className="dit-context-value">{projectName || "—"}</span>
        </div>
        <div className="dit-context-item">
          <span className="dit-context-label">监控品牌</span>
          <span className="dit-context-value">
            <em>{projectBrand || "—"}</em>
          </span>
        </div>
        {preview && (
          <div className="dit-context-item">
            <span className="dit-context-label">文件</span>
            <span className="dit-context-value">{preview.file_name}</span>
          </div>
        )}
      </div>

      {phase === "idle" || phase === "previewing" ? (
        <>
          <Spin spinning={phase === "previewing"} tip="解析中...">
            <div className="dit-upload">
              <Upload {...uploadProps}>
                <div className="dit-upload-icon">
                  <CloudUploadOutlined />
                </div>
                <div className="dit-upload-title">导入 .xlsx 文件</div>
                <div className="dit-upload-hint">点击选择，或把文件拖到这里</div>
              </Upload>
            </div>
          </Spin>
          <Alert
            type="info"
            showIcon
            message="文件需包含三张 sheet：问题问答 / 竞品分析 / 引用媒体"
            description="单文件上限 10MB。数据会写入当前项目，不会影响其他项目。文件里引用了项目没有配置的问题、竞品或模型时，那些行会被跳过并列入错误日志。"
          />
        </>
      ) : (
        preview && (
          <Spin spinning={repreviewing} tip="重新核算中...">
            {/* ---- 对账条：外部列 → 平台内部字段 ---- */}
            <div className="dit-reconcile">
              <div className="dit-reconcile-head">字段对账</div>
              {preview.mapping.map((m) => (
                <div className="dit-reconcile-row" key={m.source}>
                  <span className="dit-reconcile-src">{m.source}</span>
                  <span className="dit-reconcile-link" />
                  <span className="dit-reconcile-target">{m.target}</span>
                  <span className="dit-reconcile-note">{m.note}</span>
                </div>
              ))}
            </div>

            {preview.missing_sheets.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={`文件里没有这些 sheet：${preview.missing_sheets.join("、")}`}
                description="缺少的 sheet 会被跳过，不影响其它 sheet 的导入。"
              />
            )}

            {preview.warnings.length > 0 && (
              <Alert
                type="info"
                showIcon
                message="以下内容与项目配置不完全一致，已按归一化匹配"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.warnings.map((w) => (
                      <li key={w.message}>{w.message}</li>
                    ))}
                  </ul>
                }
              />
            )}

            {/* ---- 汇总条 ---- */}
            <div className="dit-summary">
              <span>{describeTotals(preview.totals)}</span>
              <Tag color="blue">任务 {preview.totals.tasks}</Tag>
              <Tag color="blue">子任务 {preview.totals.subtasks}</Tag>
              <Tag color="blue">提及 {preview.totals.brand_mentions}</Tag>
              <Tag color="blue">引用 {preview.totals.citations}</Tag>
              <Button
                size="small"
                type="link"
                style={{ marginLeft: "auto" }}
                onClick={reset}
              >
                重新选择文件
              </Button>
            </div>

            {/* ---- 三张 sheet 分区 ---- */}
            {preview.sheets.map((sheet) => (
              <SheetSection
                key={sheet.key}
                sheet={sheet}
                errors={preview.errors.filter((g) => g.sheet === sheet.title)}
                checked={selected.includes(sheet.key)}
                onToggle={(on) => handleToggle(sheet.key, on)}
              />
            ))}

            {result && (
              <Alert
                type="success"
                showIcon
                message="导入完成"
                description={
                  <span className="dit-num">
                    任务 +{result.tasks_created} / 更新 {result.tasks_updated}；子任务 +
                    {result.subtasks_created} / 更新 {result.subtasks_updated}；提及 +
                    {result.brand_mentions_written}；引用 +{result.citations_written}；跳过{" "}
                    {result.skipped_rows} 行
                  </span>
                }
              />
            )}

            {/* ---- 动作条 ---- */}
            <div className="dit-actions">
              <Button onClick={reset}>重新选择文件</Button>
              <div className="dit-actions-spacer" />
              <Button
                type="primary"
                loading={phase === "importing"}
                disabled={phase === "done"}
                onClick={handleApply}
              >
                导入 {selectedCount} 行
              </Button>
            </div>
          </Spin>
        )
      )}
    </div>
  );
}

interface SheetSectionProps {
  sheet: SheetPreview;
  errors: ImportErrorGroup[];
  checked: boolean;
  onToggle: (on: boolean) => void;
}

function SheetSection({ sheet, errors, checked, onToggle }: SheetSectionProps) {
  const tone = sheetTone(sheet, errors);
  const columns: TableColumnsType<Record<string, string>> = Object.keys(
    sheet.sample[0] ?? {},
  ).map((key) => ({
    title: key,
    dataIndex: key,
    ellipsis: true,
    render: (value: string) => value || "—",
  }));

  return (
    <section className={`dit-sheet dit-sheet--${tone}`}>
      <div className="dit-sheet-head">
        <span className="dit-sheet-title">{sheet.title}</span>
        <span className="dit-sheet-count">{sheet.total_rows} 行</span>
        <span className="dit-sheet-meta">
          {sheet.selected
            ? `可导入 ${sheet.importable_rows} · 阻断 ${sheet.blocked_rows} · 涉及 ${sheet.subtasks} 个子任务`
            : "未选择导入"}
        </span>
        {sheet.selected ? (
          <Tag color={tone === "error" ? "red" : tone === "warn" ? "gold" : "green"}>
            {toneLabel(tone)}
          </Tag>
        ) : (
          <Tag>未选择</Tag>
        )}
        <span className="dit-sheet-switch">
          <Switch
            checked={checked}
            size="small"
            disabled={sheet.total_rows === 0}
            onChange={onToggle}
          />
        </span>
      </div>

      {sheet.selected && errors.length > 0 && (
        <Collapse
          ghost
          items={[
            {
              key: "errors",
              label: (
                <span style={{ color: "#dc2626" }}>
                  查看 {sheet.blocked_rows} 行被阻断的原因
                </span>
              ),
              children: (
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  {errors.map((g) => (
                    <ErrorGroupBlock key={g.code} group={g} />
                  ))}
                </Space>
              ),
            },
          ]}
        />
      )}

      {sheet.sample.length > 0 ? (
        <Table
          size="small"
          rowKey={(_, index) => String(index)}
          columns={columns}
          pagination={{ pageSize: 10, size: "small" }}
          dataSource={sheet.sample}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有可预览的数据" />
      )}
    </section>
  );
}

function ErrorGroupBlock({ group }: { group: ImportErrorGroup }) {
  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(group.distinct.join("\n"));
      message.success(`已复制 ${group.distinct.length} 个名称`);
    } catch {
      message.error("复制失败，请手动选中下方文本");
    }
  };

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600 }}>
        {describeErrorGroup(group)}
      </div>
      {group.distinct.length > 0 && (
        <>
          <div className="dit-error-values">
            {group.distinct.join("、")}
          </div>
          <Button
            size="small"
            type="link"
            icon={<CopyOutlined />}
            onClick={copyAll}
            style={{ paddingLeft: 0 }}
          >
            复制全部 {group.distinct.length} 个名称
          </Button>
        </>
      )}
      <Table
        size="small"
        rowKey="row"
        pagination={{ pageSize: 5, size: "small" }}
        style={{ marginTop: 8 }}
        dataSource={group.samples}
        columns={[
          { title: "行号", dataIndex: "row", width: 70 },
          {
            title: "内容",
            dataIndex: "context",
            render: (ctx: Record<string, string>) =>
              Object.entries(ctx)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · "),
          },
        ]}
      />
    </div>
  );
}
