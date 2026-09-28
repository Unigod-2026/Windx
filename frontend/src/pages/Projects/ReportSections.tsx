/**
 * 周报章节组件 + 共享 helpers。
 *
 * 6 个章节组件对齐 docs/参芪十一味颗粒-GEO周报-20260814.pdf 的章节结构,
 * 由统一入口 [PublicReportPreview](../PublicReportPreview.tsx) 渲染:
 * 未发布 → canEdit=true,内联编辑 + 发布按钮;已发布 → canEdit=false,只读。
 *
 * 历史:这些组件原本在 [ReportPreview.tsx](./ReportPreview.tsx) 里作为 admin 路由
 * 的页面组件使用,本期重构把 admin 路由删了,只保留公开 URL,组件全部迁到这里
 * 作为命名导出复用。
 */

import { useEffect, useRef, useState } from "react";
import { Button, Input } from "antd";
import * as echarts from "echarts";
import dayjs from "dayjs";
import type { ChangeRow, ReportSnapshotOut } from "../../api/reports";
import { WIZARD_MODELS } from "./wizardConfig";

// ----- Helpers -----

export function pct(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toFixed(2)}%`;
}

export function pp(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "—";
  const v = delta * 100;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

export function deltaClass(
  delta: number | null | undefined,
): "up" | "down" | "flat" {
  if (delta === null || delta === undefined) return "flat";
  if (delta > 0.0005) return "up";
  if (delta < -0.0005) return "down";
  return "flat";
}

/** 把 "31.67%" / "+0.8pp" / "7 篇" 拆成 {num, unit}。
 *  无法识别的 unit 直接整串放 num,unit 为空。 */
function splitValue(s: string): { num: string; unit: string } {
  if (!s || s === "—") return { num: s, unit: "" };
  for (const u of ["%", "篇", "pp"]) {
    if (s.endsWith(u)) return { num: s.slice(0, -u.length), unit: u };
  }
  return { num: s, unit: "" };
}

// ----- Shared primitives -----

export function EmptyBlock({ message }: { message: string }) {
  return <div className="report-preview-empty">{message}</div>;
}

export function ChapterHeading({ title }: { title: string }) {
  return <h2 className="report-preview-h2">{title}</h2>;
}

export function Sparkline({
  points,
  startDate,
  endDate,
}: {
  points: ReportSnapshotOut["snapshot"]["daily_mention_rate"];
  /** X 轴起点（一般是基线日期）。缺省则用第一个数据点的日期。 */
  startDate?: string;
  /** X 轴终点（一般是周期末日/当前日期）。缺省则用最后一个数据点的日期。 */
  endDate?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current || !points || points.length === 0) return;

    // X 轴 = 只有数据点的日期(去重排序),不再用 echarts time 轴自动均分日历
    const categories = Array.from(new Set(points.map((p) => p.date))).sort();
    const rawMax = Math.max(0.001, ...points.map((p) => p.rate));
    // y 轴上限向上取整到 5% 倍数,避免坐标轴跑到 73% 这种不规则刻度
    const yMaxPct = Math.max(0.05, Math.ceil((rawMax * 100) / 5) * 5) / 100;

    const fmtPct = (rate: number) => {
      const d = rate * 100 < 10 ? 1 : 0;
      return `${(rate * 100).toFixed(d)}%`;
    };

    const isBaseline = (idx: number) => {
      const p = points[idx];
      return !!p && "is_baseline" in p && Boolean(p.is_baseline);
    };

    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    chartRef.current = chart;
    chart.setOption({
      animation: false,
      grid: { left: 50, right: 16, top: 24, bottom: 28 },
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const arr = params as Array<{ axisValueLabel: string; data: [string, number] }>;
          const p = arr[0];
          return `${p.axisValueLabel}<br/>提及率: ${fmtPct(p.data[1])}`;
        },
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { formatter: (val: string) => dayjs(val).format("MM-DD") },
        splitLine: { show: false },
        axisLine: { lineStyle: { color: "#E8E8E8" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: yMaxPct,
        axisLabel: {
          formatter: (val: number) => `${(val * 100).toFixed(0)}%`,
          color: "#C7D2FE",
        },
        splitLine: { lineStyle: { color: "#EEF1F8" } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "snapshot",
          type: "line",
          data: points.map((p) => [p.date, p.rate]),
          symbol: "circle",
          // 基线点用更大圆点区分,但属于同一条线 — 让 baseline → 第一快照连起来
          symbolSize: (val: { dataIndex: number }) =>
            isBaseline(val.dataIndex) ? 12 : 8,
          itemStyle: {
            color: (val: { dataIndex: number }) =>
              isBaseline(val.dataIndex) ? "#E8A33D" : "#2E5BFF",
            borderColor: "#FFFFFF",
            borderWidth: 2,
          },
          lineStyle: { color: "#2E5BFF", width: 2 },
          // 折线下方淡蓝渐变:顶 ~12% 蓝 → 底 0%(纯白),参照 PDF 视觉
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(46, 91, 255, 0.12)" },
                { offset: 1, color: "rgba(46, 91, 255, 0)" },
              ],
            },
          },
          label: {
            show: true,
            position: "top",
            formatter: (params: { dataIndex: number; data: [string, number] }) => {
              const p = points[params.dataIndex];
              return p ? fmtPct(p.rate) : "";
            },
            fontSize: 11,
            color: "#1F3A8A",
            fontWeight: 600,
          },
          connectNulls: true,
        },
      ],
    });

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [points, startDate, endDate]);

  if (!points || points.length === 0) {
    return <div className="report-preview-spark">无数据</div>;
  }
  return <div ref={ref} className="report-preview-spark" />;
}

export function PlatformTable({
  rows,
  currentLabel,
  previousLabel,
}: {
  rows: ReportSnapshotOut["snapshot"]["platform_breakdown"];
  currentLabel: string;
  previousLabel: string;
}) {
  if (!rows || rows.length === 0) return <div>无数据</div>;

  // 每行一个 (platform × delivery × thinking_mode) 组合 — label 是 "文心-网页-快速" 这种
  const sorted = [...rows].sort((a, b) => b.current_rate - a.current_rate);
  const cellText = (rate: number, mentioned: number, total: number) =>
    total > 0 ? `${pct(rate)} (${mentioned}/${total})` : "—";
  // 周环比:上期或本期没数据 → 显示 "—",不假装算 0 - 0
  const deltaText = (
    delta: number,
    curTotal: number,
    prevTotal: number,
  ) =>
    curTotal === 0 || prevTotal === 0 ? "—" : pp(delta);

  const deliveryLabel = (d: string) => (d === "mobile" ? "移动" : "网页");
  const thinkingLabel = (t: string) => (t === "think" ? "思考" : "快速");
  const rowLabel = (r: ReportSnapshotOut["snapshot"]["platform_breakdown"][number]) =>
    `${r.platform_label}-${deliveryLabel(r.delivery_mode)}-${thinkingLabel(r.thinking_mode)}`;

  return (
    <table className="report-preview-table report-preview-table-31">
      <thead>
        <tr>
          <th>AI平台</th>
          <th>{currentLabel} 提及率</th>
          <th>{previousLabel} 提及率</th>
          <th>周环比</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={`${r.platform_code}-${r.delivery_mode}-${r.thinking_mode}`}>
            <td>{rowLabel(r)}</td>
            <td className="num">
              {cellText(r.current_rate, r.current_mentioned, r.current_total)}
            </td>
            <td className="num">
              {cellText(r.previous_rate, r.previous_mentioned, r.previous_total)}
            </td>
            <td className={`num ${deltaClass(r.delta_pp)}`}>
              {deltaText(r.delta_pp, r.current_total, r.previous_total)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MatrixTable({
  matrix,
}: {
  matrix: ReportSnapshotOut["snapshot"]["prompt_platform_matrix"];
}) {
  const rows = matrix ?? [];
  // 列顺序:从首行 per_platform 的 key 推导;key 形如 "doubao|web|think"
  const platforms: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    for (const pc of Object.keys(row.per_platform || {})) {
      if (!seen.has(pc)) {
        platforms.push(pc);
        seen.add(pc);
      }
    }
  }
  // 用 WIZARD_MODELS 做 platform_code → 显示名映射
  const modelLabel = (code: string): string =>
    WIZARD_MODELS.find((m) => m.value === code)?.name ?? code;

  // 把 key 拆成 3 行 header:模型名 / 网页|移动 / 快速|思考
  const splitKey = (k: string): [string, string, string] => {
    const [code, delivery, thinking] = k.split("|");
    const deliveryLabel = delivery === "mobile" ? "移动" : "网页";
    const thinkingLabel = thinking === "think" ? "思考" : "快速";
    return [modelLabel(code), deliveryLabel, thinkingLabel];
  };

  return (
    <table className="report-preview-table report-preview-matrix">
      <thead>
        <tr>
          <th className="matrix-num">#</th>
          <th className="matrix-question-head">问题</th>
          {platforms.map((pc) => {
            const [code, d, t] = splitKey(pc);
            return (
              <th key={pc} className="matrix-col-head">
                <div>{code}</div>
                <div>{d}</div>
                <div>{t}</div>
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, idx) => {
          const per = row.per_platform || {};
          return (
            <tr key={row.prompt_id} className={idx % 2 === 1 ? "matrix-row-alt" : ""}>
              <td className="matrix-num">{idx + 1}</td>
              <td title={row.prompt_text} className="matrix-question">
                {row.prompt_text}
              </td>
              {platforms.map((pc) => {
                const mentioned = per[pc];
                return (
                  <td
                    key={pc}
                    className={mentioned ? "mark-yes" : "mark-no"}
                  >
                    {mentioned ? "✓" : "—"}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** 5.2 单桶表格 —— # / 问题 / 覆盖变化,增量绿、回落红。 */
function ChangesTable({ rows }: { rows: ChangeRow[] }) {
  return (
    <table className="report-preview-table report-preview-table-52">
      <thead>
        <tr>
          <th className="chg-rank-head">#</th>
          <th className="chg-question-head">问题</th>
          <th className="chg-delta-head">覆盖变化</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, idx) => (
          <tr
            key={r.prompt_id ?? idx}
            className={idx % 2 === 1 ? "matrix-row-alt" : ""}
          >
            <td className="chg-rank">{idx + 1}</td>
            <td className="chg-question">{r.prompt_text}</td>
            <td className={`chg-delta ${r.to >= r.from ? "chg-up" : "chg-down"}`}>
              {r.from}→{r.to} 平台
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 编辑能力 + callout 底色:1.1 走势图 / 3.1 / 5.1 / 5.2 / 5.3 章节的说明文字。
 *  有值时显示文本 + 「编辑」链接(底色保留);无值时显示「点此编辑」占位。
 *  ``title`` 可选 —— 5.2 的 PDF 在框内多一行粗体小标题。
 *  ``tone`` 可选 —— 默认米黄(奶油色),5.3 核心归因用绿色底(对齐 PDF 色值)。 */
export function EditableCallout({
  value,
  canEdit,
  onSave,
  title,
  tone = "cream",
}: {
  value: string | null;
  canEdit: boolean;
  onSave: (next: string | null) => Promise<void>;
  title?: string;
  tone?: "cream" | "green";
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);

  const startEdit = () => {
    setDraft(value ?? "");
    setEditing(true);
  };
  const cancel = () => {
    setDraft(value ?? "");
    setEditing(false);
  };
  const save = async () => {
    setSaving(true);
    try {
      await onSave(draft.trim() || null);
      setEditing(false);
    } catch {
      // parent toasts; stay in editing mode so user can retry
    } finally {
      setSaving(false);
    }
  };

  const hasValue = value !== null && value !== "";
  return (
    <div
      className={`report-preview-callout${
        tone === "green" ? " report-preview-callout--green" : ""
      }`}
    >
      {title && <div className="report-preview-callout-title">{title}</div>}
      {editing ? (
        <div>
          <Input.TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 6 }}
            disabled={saving}
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <Button type="primary" size="small" loading={saving} onClick={save}>
              保存
            </Button>
            <Button size="small" onClick={cancel} disabled={saving}>
              取消
            </Button>
          </div>
        </div>
      ) : hasValue ? (
        <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{value}</p>
      ) : null}
      {canEdit && !editing && (
        <Button
          type="link"
          size="small"
          onClick={startEdit}
          style={{ padding: 0, marginTop: hasValue ? 4 : 0 }}
        >
          {hasValue ? "编辑" : "点此编辑"}
        </Button>
      )}
    </div>
  );
}

// ----- Chapter sections -----

export function SectionOneOverall({
  snapshot,
  canEdit,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  canEdit: boolean;
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  const daily = snapshot.daily_mention_rate;
  const ops = snapshot.content_ops as { weekly_post_count?: number } | null;
  const postCount = ops?.weekly_post_count ?? 0;
  const chartSummary = snapshot.weekly_chart_summary ?? null;

  if (!daily || daily.length === 0) {
    return (
      <section>
        <ChapterHeading title="一、整体提及率与各平台表现动态" />
        <EmptyBlock message="暂无数数据" />
      </section>
    );
  }
  // KPI 用 period_end 那天的数据 — 图表实时延伸,但 KPI 仍是「当前周期」语义
  const periodPoint =
    daily.find((d) => d.date === snapshot.period.end) ?? daily[daily.length - 1];
  // 周环比:「上周同日」= period.end - 7 天 — 09-22 → 09-15,09-28 → 09-21
  // 按日历天找(不是数组下标),找不到 = 0(那天无数据)
  const prevDate = dayjs(snapshot.period.end).subtract(7, "day").format("YYYY-MM-DD");
  const periodPrev = daily.find((d) => d.date === prevDate);
  const current = periodPoint?.rate ?? 0;
  const previous = periodPrev?.rate ?? 0;
  const wow = current - previous;
  const baseline = snapshot.baseline.rate;

  const lastDate = periodPoint?.date ?? snapshot.period.end;
  const mentioned = periodPoint?.mentioned;
  const total = periodPoint?.total;
  // 周环比对照日期标签:有数据显示日期 + 率;无数据显示「—」
  const prevShort = prevDate.length >= 10 ? prevDate.slice(5) : prevDate;
  const prevLabel =
    periodPrev !== undefined
      ? `${prevShort} ${pct(periodPrev.rate)}`
      : `${prevShort} —`;

  // 图表数据:基线作为「起点虚拟点」前置,后面的快照是真实 BrandMention 数据
  const baselinePoint =
    snapshot.baseline.date && snapshot.baseline.rate !== null
      ? {
          date: snapshot.baseline.date,
          total: 0,
          mentioned: 0,
          rate: snapshot.baseline.rate,
          is_baseline: true,
        }
      : null;
  const chartPoints = baselinePoint ? [baselinePoint, ...daily] : daily;

  // "2026-09-22" → "09-22",KPI 卡宽度有限,年用不到
  const shortDate = (s: string) => (s.length >= 10 ? s.slice(5) : s);

  return (
    <section>
      <ChapterHeading title="一、整体提及率与各平台表现动态" />
      <div className="report-preview-kpis">
        <div className="report-preview-kpi">
          <KpiValue value={pct(current)} />
          <div className="report-preview-kpi-label">
            {shortDate(lastDate)}整体提及率
            {mentioned !== undefined && total !== undefined && `(${mentioned}/${total})`}
          </div>
        </div>
        <div className="report-preview-kpi">
          <KpiValue value={pp(wow)} />
          <div className="report-preview-kpi-label">
            周环比(较 {prevLabel})
          </div>
        </div>
        <div className="report-preview-kpi">
          <KpiValue value={baseline !== null ? pp(current - baseline) : "—"} />
          <div className="report-preview-kpi-label">
            较基线({snapshot.baseline.date ? shortDate(snapshot.baseline.date) : "—"} {pct(baseline)})
          </div>
        </div>
        <div className="report-preview-kpi">
          <KpiValue value={`${postCount} 篇`} />
          <div className="report-preview-kpi-label">本周发布独立标题</div>
        </div>
      </div>
      <h3 className="report-preview-h3">
        1.1 整体提及率走势(基线 {snapshot.baseline.date ?? "—"} → {lastDate},
        {"  "}{daily.length} 个监测日)
      </h3>
      <Sparkline
        points={chartPoints}
        startDate={snapshot.baseline.date ?? undefined}
        endDate={snapshot.chart_end_date ?? snapshot.period.end}
      />
      <EditableCallout
        value={chartSummary}
        canEdit={canEdit}
        onSave={(v) => onSave({ weekly_chart_summary: v })}
      />
    </section>
  );
}

function KpiValue({ value, cls }: { value: string; cls?: string }) {
  const { num, unit } = splitValue(value);
  return (
    <div className={`report-preview-kpi-value ${cls ?? ""}`}>
      <span className="report-preview-kpi-num">{num}</span>
      {unit && <span className="report-preview-kpi-unit">{unit}</span>}
    </div>
  );
}

export function SectionTwoSummary({
  snapshot,
  canEdit,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  canEdit: boolean;
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  // 4 个区块按 PDF 排版:核心结论 = 全宽绿底,其余 3 个 = 3 列白底彩条
  const fields = [
    { key: "weekly_core_finding", label: "核心结论", hint: "1-2 句话总结本周监控结果", variant: "core" as const },
    { key: "weekly_platform_dynamic", label: "平台动态", hint: "本周 AI 平台层面的整体趋势", variant: "blue" as const },
    { key: "weekly_content_result", label: "内容成效", hint: "本周发布/分发对提及率的拉动效果", variant: "orange" as const },
    { key: "weekly_scene_coverage", label: "场景覆盖", hint: "本周各类问题的覆盖变化", variant: "green" as const },
  ];

  const block = snapshot.weekly_summary || {
    core_finding: null,
    platform_dynamic: null,
    content_result: null,
    scene_coverage: null,
  };

  const valueOf = (k: string): string | null => {
    if (k === "weekly_core_finding") return block.core_finding;
    if (k === "weekly_platform_dynamic") return block.platform_dynamic;
    if (k === "weekly_content_result") return block.content_result;
    if (k === "weekly_scene_coverage") return block.scene_coverage;
    return null;
  };

  const core = fields.find((f) => f.variant === "core")!;
  const thirds = fields.filter((f) => f.variant !== "core");

  return (
    <section>
      <ChapterHeading title="二、本周总结" />
      <SummaryBlock
        label={core.label}
        variant={core.variant}
        value={valueOf(core.key)}
        canEdit={canEdit}
        onSave={(v) => onSave({ [core.key]: v })}
      />
      <div className="summary-grid">
        {thirds.map((f) => (
          <SummaryBlock
            key={f.key}
            label={f.label}
            variant={f.variant}
            value={valueOf(f.key)}
            canEdit={canEdit}
            onSave={(v) => onSave({ [f.key]: v })}
          />
        ))}
      </div>
    </section>
  );
}

function SummaryBlock({
  label,
  value,
  variant,
  canEdit,
  onSave,
}: {
  label: string;
  value: string | null;
  variant: "core" | "blue" | "orange" | "green";
  canEdit: boolean;
  onSave: (next: string | null) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);

  const startEdit = () => {
    setDraft(value ?? "");
    setEditing(true);
  };

  const cancel = () => {
    setDraft(value ?? "");
    setEditing(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(draft.trim() || null);
      setEditing(false);
    } catch {
      // parent toasts; stay in editing mode so user can retry
    } finally {
      setSaving(false);
    }
  };

  const hasValue = value !== null && value !== "";

  return (
    <div className={`summary-block summary-block--${variant}`}>
      <div className="summary-block-head">
        <strong className="summary-block-title">{label}</strong>
      </div>
      {editing ? (
        <div>
          <Input.TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 12 }}
            disabled={saving}
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <Button type="primary" loading={saving} onClick={save}>
              保存
            </Button>
            <Button onClick={cancel} disabled={saving}>
              取消
            </Button>
          </div>
        </div>
      ) : hasValue ? (
        <p style={{ whiteSpace: "pre-wrap" }}>{value}</p>
      ) : null}
      {canEdit && !editing && (
        <Button type="link" size="small" onClick={startEdit} style={{ padding: 0 }}>
          {hasValue ? "编辑" : "点此编辑"}
        </Button>
      )}
    </div>
  );
}

export function SectionThreeBreakdown({
  snapshot,
  canEdit,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  canEdit: boolean;
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  const breakdown = snapshot.platform_breakdown || [];
  const matrix = snapshot.prompt_platform_matrix || [];
  const platformSummary = snapshot.weekly_platform_summary ?? null;

  // 3.1 表头日期:上一周期末日 → 当前周期末日
  const previousEnd = snapshot.previous_end_date ?? "上期";
  const currentEnd = snapshot.period.end;
  const prevShort = previousEnd.length >= 10 ? previousEnd.slice(5) : previousEnd;
  const currShort = currentEnd.length >= 10 ? currentEnd.slice(5) : currentEnd;

  return (
    <section>
      <ChapterHeading title="三、分平台周环比变化与问题级提及率明细" />

      <h3 className="report-preview-h3">
        3.1 各平台提及率周环比({prevShort} → {currShort})
      </h3>
      {breakdown.length === 0 ? (
        <EmptyBlock message="暂无数数据" />
      ) : (
        <PlatformTable
          rows={breakdown}
          currentLabel={currShort}
          previousLabel={prevShort}
        />
      )}
      <EditableCallout
        value={platformSummary}
        canEdit={canEdit}
        onSave={(v) => onSave({ weekly_platform_summary: v })}
      />

      {matrix.length > 0 && (
        <>
          <h3 className="report-preview-h3">
            3.2 每个问题的具体提及率({periodEndShort(snapshot.period.end)},
            {matrix.length}{" 题 × "}
            {Object.keys(matrix[0].per_platform).length}{" 平台"})
          </h3>
          <MatrixTable matrix={matrix} />
          <div className="report-preview-callout">
            提及率 = 提及该问题的平台数 ÷ {Object.keys(matrix[0].per_platform).length}
            {" × 100%。✓=已提及,—=未提及。"}
          </div>
        </>
      )}

      {(snapshot.stable_prompts?.length ?? 0) > 0 && (
        <>
          <h3 className="report-preview-h3">
            3.3 稳定提及的前{snapshot.stable_prompts!.length}个问题
            (基线至今 {snapshot.total_monitor_days ?? 0} 个监测日累计)
          </h3>
          <StablePromptsTable
            rows={snapshot.stable_prompts!}
            totalDays={snapshot.total_monitor_days ?? 0}
          />
        </>
      )}
    </section>
  );
}

/** 把 "2026-09-22" 截成 "09-22";缺省返回原值 */
function periodEndShort(s: string): string {
  return s.length >= 10 ? s.slice(5) : s;
}

interface ZeroMentionRow {
  prompt_id: number | null;
  prompt_text: string;
}

interface StablePromptRow {
  prompt_id: number | null;
  prompt_text: string;
  mention_days: number;
}

function ZeroMentionTable({ rows }: { rows: ZeroMentionRow[] }) {
  return (
    <table className="report-preview-table report-preview-table-51">
      <thead>
        <tr>
          <th className="zm-rank-head">#</th>
          <th className="zm-question-head">问题</th>
          <th className="zm-status-head">状态</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, idx) => (
          <tr
            key={r.prompt_id ?? idx}
            className={idx % 2 === 1 ? "matrix-row-alt" : ""}
          >
            <td className="zm-rank">{idx + 1}</td>
            <td className="zm-question">{r.prompt_text}</td>
            <td className="zm-status">
              <span className="zm-tag">0 提及</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StablePromptsTable({
  rows,
  totalDays,
}: {
  rows: StablePromptRow[];
  totalDays: number;
}) {
  return (
    <table className="report-preview-table report-preview-table-33">
      <thead>
        <tr>
          <th className="stable-rank-head">
            <div>排</div>
            <div>名</div>
          </th>
          <th className="stable-question-head">问题</th>
          <th className="stable-tag-head">标签</th>
          <th className="stable-coverage-head">覆盖监测日</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, idx) => (
          <tr key={r.prompt_id ?? idx} className={idx % 2 === 1 ? "matrix-row-alt" : ""}>
            <td className="stable-rank">{idx + 1}</td>
            <td className="stable-question">{r.prompt_text}</td>
            <td>
              <span className="stable-tag">稳定</span>
            </td>
            <td className="stable-coverage">
              {r.mention_days}/{totalDays} 天
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function SectionFourContentOps({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const ops = snapshot.content_ops;
  return (
    <section>
      <ChapterHeading title="四、本周内容运营" />
      {ops ? (
        <p>{typeof ops === "string" ? ops : JSON.stringify(ops)}</p>
      ) : (
        <EmptyBlock message="暂无数数据" />
      )}
    </section>
  );
}

export function SectionFiveWeeklyChanges({
  snapshot,
  canEdit,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  canEdit: boolean;
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  const changes = snapshot.weekly_changes;
  const zero = snapshot.zero_mention_prompts || [];
  const zeroSummary = snapshot.weekly_zero_mention_summary ?? null;
  const changeSummary = snapshot.weekly_change_summary ?? null;
  // 5.2 四张表按此顺序纵向渲染;空桶整表不显示(不是显示空表)
  const changeBuckets: Array<{
    key: string;
    title: (n: number) => string;
    rows: ChangeRow[];
  }> = [
    {
      key: "new_mentions",
      title: (n) => `新增突破(0 → 有提及,${n} 题)`,
      rows: changes?.new_mentions ?? [],
    },
    {
      key: "increased",
      title: (n) => `上升(覆盖平台数增加,${n} 题)`,
      rows: changes?.increased ?? [],
    },
    {
      key: "decreased",
      title: (n) => `回落/失守(覆盖平台数下降,${n} 题)`,
      rows: changes?.decreased ?? [],
    },
    {
      key: "lost_mentions",
      title: (n) => `完全失守(有提及 → 0,${n} 题)`,
      rows: changes?.lost_mentions ?? [],
    },
  ];
  // 5.1 标题里的「平台数」从 prompt_platform_matrix 第一行的列数取(平台×终端×模式组合数)
  const platformCount =
    snapshot.prompt_platform_matrix?.[0]
      ? Object.keys(snapshot.prompt_platform_matrix[0].per_platform).length
      : 0;
  const hasChanges =
    changes &&
    ((changes.new_mentions?.length ?? 0) > 0 ||
      (changes.increased?.length ?? 0) > 0 ||
      (changes.decreased?.length ?? 0) > 0 ||
      (changes.lost_mentions?.length ?? 0) > 0);
  const hasZero = zero.length > 0;
  if (!hasChanges && !hasZero) {
    return (
      <section>
        <ChapterHeading title="五、待突破问题与本周边际变化" />
        <EmptyBlock message="暂无数数据" />
      </section>
    );
  }

  return (
    <section>
      <ChapterHeading title="五、待突破问题与本周边际变化" />

      {hasZero && (
        <>
          <h3 className="report-preview-h3">
            5.1 持续未提及问题
            ({snapshot.total_monitor_days ?? 0} 个监测日
            {" × "}
            {platformCount}{" 平台全部 0 提及,共 "}{zero.length}{" 题"})
          </h3>
          <ZeroMentionTable rows={zero} />
          <EditableCallout
            value={zeroSummary}
            canEdit={canEdit}
            onSave={(v) => onSave({ weekly_zero_mention_summary: v })}
          />
        </>
      )}

      {hasChanges && (
        <>
          <h3 className="report-preview-h3">5.2 本周边际变化</h3>
          {changeBuckets.map(({ key, title, rows }) =>
            rows.length > 0 ? (
              <div key={key}>
                <h4 className="report-preview-h4">{title(rows.length)}</h4>
                <ChangesTable rows={rows} />
              </div>
            ) : null,
          )}
          <EditableCallout
            title="本周边际变化解读"
            value={changeSummary}
            canEdit={canEdit}
            onSave={(v) => onSave({ weekly_change_summary: v })}
          />
        </>
      )}
    </section>
  );
}

export function SectionAttribution({
  snapshot,
  canEdit,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  canEdit: boolean;
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  const text = snapshot.attribution ?? null;
  return (
    <section>
      <ChapterHeading title="5.3 核心归因" />
      {text || canEdit ? (
        <EditableCallout
          tone="green"
          value={text}
          canEdit={canEdit}
          onSave={(v) => onSave({ attribution: v })}
        />
      ) : (
        <EmptyBlock message="暂无数数据" />
      )}
    </section>
  );
}
