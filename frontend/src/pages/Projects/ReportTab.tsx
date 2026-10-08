/**
 * 「周报」一级 tab —— 报告库列表 + 生成入口。
 *
 * 视觉:暖纸色背景,行式列表(非 card),衬线标题 + Inter 正文。
 *
 * 生成弹窗只要求模板 + 两个必填基线字段(日期 + 提及率);周期 /
 * 模型 / 问题全部沿用 GlobalToolbar 当前状态(spec §2.2 终态 +
 * 后续产品决策 —— 弹窗不重复 toolbar 的选择)。
 *
 * 操作:
 *   - 生成周报 → GenerateReportModal(模板 + 基线两个必填)
 *   - 打开 → admin 编辑视图(/reports/{id}),新标签页,需登录
 *   - 公网预览 / 复制链接 / 取消发布 → 仅已发布报告可见
 *     (草稿没有可对外分享的 token URL,不展示引用它的入口)
 */

import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  DatePicker,
  Form,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Tag,
  message,
} from "antd";
import { CopyOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs, { Dayjs } from "dayjs";
import {
  generateReport,
  getProjectBaseline,
  listReports,
  listTemplates,
  publicReportUrl,
  unpublishReport,
  type Report,
  type ReportTemplate,
} from "../../api/reports";
import { useToolbarFilter } from "../../components/ToolbarFilterContext";
import { parseOverviewKey } from "./platforms";
import "./ReportTab.css";

interface Props {
  projectId: number;
}

/** Resolve the report window from the toolbar's current date range.
 *  No range ⇒ "last 15 days", matching the preset the toolbar shows on
 *  first paint (and every other tab's fallback). The old 7-day fallback
 *  silently disagreed with the toolbar: the header read "近 15 天" while
 *  the report window was 7 days. */
function windowFromToolbar(
  range: ReturnType<typeof useToolbarFilter>["selectedDateRange"],
): { start: string; end: string } {
  const end = dayjs();
  if (!range) {
    return { start: end.subtract(14, "day").format("YYYY-MM-DD"), end: end.format("YYYY-MM-DD") };
  }
  if ("days" in range && typeof range.days === "number") {
    return {
      start: end.subtract(range.days - 1, "day").format("YYYY-MM-DD"),
      end: end.format("YYYY-MM-DD"),
    };
  }
  return { start: range.start, end: range.end };
}

/** Resolve the toolbar's model selection back to the raw
 *  ``Subtask.platform`` strings the backend expects. Compound keys
 *  like ``doubao__web__fast`` collapse to ``doubao``; ``mobile`` rows
 *  re-attach the ``_mobile`` suffix. ``null`` selection means
 *  "no filter" — backend interprets ``null`` / ``[]`` the same way
 *  (empty = no filter). */
function platformCodesFromToolbar(
  selected: string[] | null,
): string[] | undefined {
  if (!selected || selected.length === 0) return undefined;
  return selected.map((key) => {
    const parsed = parseOverviewKey(key);
    if (!parsed) return key;
    return parsed.delivery === "mobile" ? `${parsed.code}_mobile` : parsed.code;
  });
}

export default function ReportTab({ projectId }: Props) {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [genOpen, setGenOpen] = useState(false);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listReports(projectId);
      setReports(list.items);
    } catch (err) {
      setError((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  /** 在 admin 内打开周报 —— 新标签页走 ``/reports/:id``,不是 token 公网链接。
   *  新窗口确保查 / 编辑不会丢失列表页上下文(关闭预览后回到列表继续操作)。
   *  URL 故意不带 /admin/ 前缀:React Router v6 默认按 path-prefix 嵌套,
   *  `/admin/reports/:id` 会被识别为 /admin 的子路径并被 AppLayout 包住;
   *  /reports/:id 顶层路径独立匹配,无侧边栏。 */
  const openInAdmin = (id: number) => {
    window.open(`/reports/${id}`, "_blank", "noopener,noreferrer");
  };

  /** 已发布报告「公网预览」—— 用 token URL 在新标签页打开(无登录,纯 HTML)。
   *  与 ``openInAdmin`` 分开:运营要的是「外部看到的样子」才用这个。 */
  const openPublicPreview = (shareToken: string) => {
    window.open(publicReportUrl(shareToken), "_blank", "noopener,noreferrer");
  };

  const copyShareLink = async (shareToken: string) => {
    const url = publicReportUrl(shareToken);
    try {
      await navigator.clipboard.writeText(url);
      message.success("公开链接已复制");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        message.success("公开链接已复制");
      } catch {
        message.info(`请手动复制: ${url}`);
      } finally {
        document.body.removeChild(ta);
      }
    }
  };

  const unpublish = async (id: number) => {
    try {
      await unpublishReport(id);
      message.success("已取消发布");
      reload();
    } catch (err) {
      message.error((err as Error).message || "取消发布失败");
    }
  };

  return (
    <div className="report-tab">
      <div className="report-tab-header">
        <h1 className="report-tab-title">周报</h1>
        <div className="report-tab-actions">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setGenOpen(true)}
          >
            生成周报
          </Button>
        </div>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          style={{ margin: "16px 0" }}
        />
      )}

      {loading && reports.length === 0 ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : reports.length === 0 ? (
        <div className="report-tab-empty">
          暂无报告。点击右上「生成周报」开始。
        </div>
      ) : (
        <ul className="report-tab-list">
          {reports.map((r) => (
            <li key={r.id} className="report-row">
              <div className="report-row-main">
                <h2 className="report-row-title">{r.title}</h2>
                <div className="report-row-meta">
                  周期 {r.period_start} ~ {r.period_end}
                  <span className="report-row-meta-sep">·</span>
                  {r.is_published ? (
                    <Tag color="green">已发布</Tag>
                  ) : (
                    <Tag>未发布</Tag>
                  )}
                </div>
                <div className="report-row-time">
                  生成于 {dayjs(r.generated_at).format("YYYY-MM-DD HH:mm:ss")}
                </div>
              </div>
              <div className="report-row-actions">
                <Button onClick={() => openInAdmin(r.id)}>打开</Button>
                {r.is_published && (
                  <Button onClick={() => openPublicPreview(r.share_token)}>
                    公网预览
                  </Button>
                )}
                {r.is_published && (
                  <Button
                    icon={<CopyOutlined />}
                    onClick={() => copyShareLink(r.share_token)}
                  >
                    复制链接
                  </Button>
                )}
                {r.is_published && (
                  <Button onClick={() => unpublish(r.id)}>取消发布</Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <GenerateReportModal
        open={genOpen}
        onClose={() => setGenOpen(false)}
        onCreated={() => {
          setGenOpen(false);
          reload();
        }}
        projectId={projectId}
      />
    </div>
  );
}

// ----- Generate modal -----

interface GenModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  projectId: number;
}

interface GenFormShape {
  template_id: string;
  baseline_date: Dayjs | null;
  baseline_rate: number | null;
}

function GenerateReportModal({
  open,
  onClose,
  onCreated,
  projectId,
}: GenModalProps) {
  const toolbar = useToolbarFilter();
  // ``Form.useForm`` generic is intentionally loose (same as before).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [form] = Form.useForm() as any;
  const [submitting, setSubmitting] = useState(false);
  const [templateOptions, setTemplateOptions] = useState<
    { value: string; label: string }[]
  >([]);
  // Default baseline pre-fetched once per open. Backend persists the
  // last-generated baseline in ``report_settings.json`` so this is
  // the operator's previous choice — they can still edit before
  // submitting.
  const [baselineDefault, setBaselineDefault] = useState<{
    date: Dayjs | null;
    rate: number | null;
  }>({ date: null, rate: null });
  const [loadingDefault, setLoadingDefault] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    // Fetch templates + baseline in parallel — both are independent
    // reads with no relationship between the responses.
    setLoadingDefault(true);
    Promise.all([listTemplates(), getProjectBaseline(projectId)])
      .then(([tpls, base]) => {
        if (cancelled) return;
        setTemplateOptions(
          tpls.items.map((t: ReportTemplate) => ({
            value: t.id,
            label: t.description ? `${t.name} — ${t.description}` : t.name,
          })),
        );
        setBaselineDefault({
          date: base.baseline_date ? dayjs(base.baseline_date) : null,
          // Backend stores 0..1; the form value lives in 0..100 (matches
          // the visible field + "addonAfter='%'"). Convert here so the
          // default value the user sees on open matches what they
          // typed last time.
          rate: base.baseline_rate !== null ? base.baseline_rate * 100 : null,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setTemplateOptions([]);
          setBaselineDefault({ date: null, rate: null });
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDefault(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, projectId]);

  // Re-populate the form whenever the modal opens AND the defaults
  // are loaded. Without ``open`` in deps, the first open on a fresh
  // page would race: listTemplates() resolves *after* this effect
  // runs, so ``templateOptions[0]?.value`` would be undefined at
  // setFieldsValue time. Including the defaults as deps ensures the
  // second pass happens once they've actually arrived.
  useEffect(() => {
    if (!open) return;
    if (loadingDefault) return;
    form.setFieldsValue({
      template_id: templateOptions[0]?.value,
      baseline_date: baselineDefault.date,
      baseline_rate: baselineDefault.rate,
    });
  }, [open, loadingDefault, templateOptions, baselineDefault, form]);

  const submit = async () => {
    const v = (await form.validateFields()) as GenFormShape;
    setSubmitting(true);
    try {
      // Period / models / prompts are NOT in the modal — read them
      // from the GlobalToolbar's current state. The modal is now a
      // thin shell around "template + baseline", with the operator's
      // scoping decisions made once on the toolbar and applied here.
      const win = windowFromToolbar(toolbar.selectedDateRange);
      const platformCodes = platformCodesFromToolbar(toolbar.selectedModels);
      const newReport = await generateReport({
        project_id: projectId,
        template_id: v.template_id,
        period_start: win.start,
        period_end: win.end,
        platform_codes: platformCodes,
        prompts: toolbar.selectedPromptIds ?? undefined,
        baseline_date: v.baseline_date
          ? v.baseline_date.format("YYYY-MM-DD")
          : null,
        // ``v.baseline_rate`` is in 0..100 (the form value the user
        // sees, in percent). Convert to 0..1 for storage + API
        // contract. Round to 4 decimal places to avoid IEEE 754
        // tails like ``0.12119999999999999`` showing up in
        // ``report_settings.json``.
        baseline_rate:
          v.baseline_rate === null || v.baseline_rate === undefined
            ? null
            : roundTo4(Number(v.baseline_rate) / 100),
      });
      const url = publicReportUrl(newReport.share_token);
      try {
        await navigator.clipboard.writeText(url);
        message.success("周报已生成，公开链接已复制到剪贴板");
      } catch {
        message.info(`周报已生成，公开链接: ${url}`);
      }
      onCreated();
    } catch (err) {
      message.error((err as Error).message || "周报生成失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="生成周报"
      okText="生成"
      cancelText="取消"
      onCancel={onClose}
      onOk={submit}
      confirmLoading={submitting}
      destroyOnHidden
      width={520}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="template_id"
          label="报告模板"
          rules={[{ required: true, message: "请选择模板" }]}
        >
          <Select
            options={templateOptions}
            loading={templateOptions.length === 0 && open}
            placeholder="选择模板"
          />
        </Form.Item>
        <Form.Item
          name="baseline_date"
          label="基线日期"
          rules={[{ required: true, message: "请选择基线日期" }]}
        >
          <DatePicker style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="baseline_rate"
          label="基线提及率"
          rules={[
            { required: true, message: "请填写基线提及率" },
            {
              validator: async (_rule, value) => {
                if (value === null || value === undefined || value === "") {
                  throw new Error("请填写基线提及率");
                }
                const num = Number(value);
                if (Number.isNaN(num)) {
                  throw new Error("基线提及率必须是数字");
                }
                if (num < 0 || num > 100) {
                  throw new Error("基线提及率应在 0~100% 之间");
                }
              },
            },
          ]}
          extra={
            baselineDefault.rate !== null
              ? `默认 ${formatPercent(baselineDefault.rate)}%（来自上次生成）`
              : "尚未配置基线；填写后将作为下次默认值写入设置文件"
          }
        >
          <InputNumber
            min={0}
            max={100}
            step={0.01}
            placeholder="如 0.83"
            addonAfter="%"
            style={{ width: "100%" }}
            formatter={(v) => formatPercent(Number(v))}
            parser={parsePercentStringToPercentNumber}
          />
        </Form.Item>
        <div style={{ fontSize: 12, color: "#8c8c8c" }}>
          周期 / 模型 / 问题 沿用全局工具栏当前选择；本弹窗只填模板与基线。
        </div>
      </Form>
    </Modal>
  );
}

/** Round to 4 decimal places to avoid IEEE 754 tails like
 *  ``0.12119999999999999`` showing up in persisted JSON. 4 dp is
 *  enough for percent values (one part per ten thousand); for a
 *  0.83% baseline that's a precision of 0.0001% — well below what
 *  a human operator can read off a chart. */
function roundTo4(n: number): number {
  return Math.round(n * 1e4) / 1e4;
}

/** Format a 0..100 percent value for the InputNumber display.
 *  ``undefined`` / ``null`` / ``""`` renders as empty (so antd
 *  shows the placeholder). Always two decimal places, trailing
 *  zeros stripped when they're all zero (``12`` not ``12.00``,
 *  but ``12.10`` not ``12.1``). */
function formatPercent(n: number): string {
  if (!Number.isFinite(n)) return "";
  // Two decimals, strip trailing zeros after the dot. We re-parse
  // through Number because toFixed returns a string and we want
  // ``12.10`` to stay ``12.10``, not collapse to ``12.1``.
  return Number(n.toFixed(2)).toString();
}

/** antd ``InputNumber`` parser. Accepts a user-typed string and
 *  returns the canonical numeric form (0..100) — or ``""`` if the
 *  string is empty / unparseable.
 *
 *  The InputNumber is wrapped by ``addonAfter="%"`` so the visible
 *  field shows ``12.12 %``; the parser strips whitespace and an
 *  optional trailing ``%``, then returns the number. The
 *  InputNumber also handles locale separators (commas vs dots) via
 *  its own internal parser, but we redo it here so a paste of
 *  "12.12%" doesn't strip the digits.
 *
 *  This parser is intentionally lenient: anything that doesn't parse
 *  returns ``""`` so the field clears, instead of raising. Strict
 *  validation happens at form-submit time via the ``validator``
 *  rule on the Form.Item (range 0..100). */
function parsePercentStringToPercentNumber(value: string | undefined): number | "" {
  if (value === undefined || value === null || value === "") return "";
  const trimmed = String(value).replace(/\s+/g, "").replace(/%$/, "").replace(/,/g, "");
  if (trimmed === "") return "";
  const num = Number(trimmed);
  if (Number.isNaN(num)) return "";
  return num;
}
