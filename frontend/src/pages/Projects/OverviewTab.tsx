import { useEffect, useMemo, useRef, useState } from "react";
import { DatePicker, Empty, Skeleton, message } from "antd";
import * as echarts from "echarts";
import dayjs, { type Dayjs } from "dayjs";
import {
  getProjectOverview,
  type OverviewKpi,
  type ProjectOverview,
} from "../../api/projects";
import { platformColor, platformLabel } from "./platforms";

interface Props {
  projectId: number;
}

type SubTab = "summary" | "trend" | "model" | "alert";
type RangeKey = "7" | "15" | "30" | "60" | "custom";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "summary", label: "总览数据" },
  { key: "trend", label: "趋势分析" },
  { key: "model", label: "模型维度" },
  { key: "alert", label: "告警中心" },
];

const TIME_RANGES: { key: RangeKey; label: string }[] = [
  { key: "7", label: "7 天" },
  { key: "15", label: "15 天" },
  { key: "30", label: "30 天" },
  { key: "60", label: "2 个月" },
  { key: "custom", label: "自定义" },
];

// Backend rejects anything wider; the picker enforces it up front so the
// user gets a disabled date rather than a 400.
const MAX_RANGE_DAYS = 62;

function fmtInt(v: number): string {
  return Math.round(v).toLocaleString("zh-CN");
}

function fmtRate(v: number): string {
  return (v * 100).toFixed(1);
}

/**
 * 首屏概览 —— 与 docs/ui-sample/index.html 的 ``#tab-overview`` 同构:
 *   顶部: 二级 Tab(总览数据 / 趋势分析 / 模型维度 / 告警中心) + 时间选择器
 *   中部: 5 张 KPI 卡片(总提及次数 / Top1 / Top3 / 提问总数 / 收到答案数)
 *   下部: 总提及趋势(echarts 折线) / Top1 率排行(echarts 横向条) / 告警概览
 *
 * 单一数据源 ``GET /projects/{id}/overview``。
 */
export default function OverviewTab({ projectId }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("summary");
  const [range, setRange] = useState<RangeKey>("15");
  const [custom, setCustom] = useState<[Dayjs, Dayjs]>(() => [
    dayjs().subtract(14, "day"),
    dayjs(),
  ]);
  // Half-picked range while the calendar is open — drives disabledDate so
  // the 2-month cap is enforced by greying out dates, not by an error.
  const [picking, setPicking] = useState<[Dayjs | null, Dayjs | null] | null>(
    null,
  );
  const [data, setData] = useState<ProjectOverview | null>(null);
  const [loading, setLoading] = useState(true);

  const query = useMemo(
    () =>
      range === "custom"
        ? {
            start: custom[0].format("YYYY-MM-DD"),
            end: custom[1].format("YYYY-MM-DD"),
          }
        : { days: Number(range) },
    [range, custom],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectOverview(projectId, query)
      .then((o) => {
        if (cancelled) return;
        setData(o);
      })
      .catch((err) => {
        if (cancelled) return;
        message.error((err as Error).message || "概览数据加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, query]);

  return (
    <div className="overview-tab">
      {/* 二级 Tab + 时间选择器 */}
      <div className="secondary-tabs">
        {SUB_TABS.map((t) => (
          <div
            key={t.key}
            className={`secondary-tab${subTab === t.key ? " active" : ""}`}
            onClick={() => setSubTab(t.key)}
          >
            {t.label}
          </div>
        ))}
        <div className="secondary-tabs-right">
          <div className="time-selector">
            {TIME_RANGES.map((r) => (
              <button
                key={r.key}
                type="button"
                className={`time-btn${range === r.key ? " active" : ""}`}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
          {range === "custom" && (
            <DatePicker.RangePicker
              size="small"
              value={custom}
              allowClear={false}
              disabledDate={(cur) => {
                if (cur > dayjs().endOf("day")) return true;
                if (!picking) return false;
                const [from, to] = picking;
                if (from && cur.diff(from, "day") >= MAX_RANGE_DAYS) return true;
                if (to && to.diff(cur, "day") >= MAX_RANGE_DAYS) return true;
                return false;
              }}
              onCalendarChange={(v) => setPicking(v)}
              onOpenChange={(open) => setPicking(open ? [null, null] : null)}
              onChange={(v) => {
                if (v && v[0] && v[1]) setCustom([v[0], v[1]]);
              }}
              style={{ marginLeft: 8, width: 240 }}
            />
          )}
        </div>
      </div>

      <div className="overview-content">
        {loading || !data ? (
          <Skeleton active paragraph={{ rows: 10 }} />
        ) : (
          <>
            {/* KPI 卡片组 */}
            <div className="kpi-grid">
              <KpiCard
                label="总提及次数"
                kpi={data.total_mentions}
                render={fmtInt}
                primary
                sparkColor="rgba(255,255,255,0.8)"
              />
              <KpiCard
                label="Top1 提及率"
                kpi={data.top1_rate}
                render={fmtRate}
                unit="%"
                sparkColor="#1a55e8"
              />
              <KpiCard
                label="Top3 提及率"
                kpi={data.top3_rate}
                render={fmtRate}
                unit="%"
                sparkColor="#52c41a"
              />
              <KpiCard
                label="提问总数"
                kpi={data.question_count}
                render={fmtInt}
                sparkColor="#722ed1"
              />
              <KpiCard
                label="收到答案数"
                kpi={data.answer_count}
                render={fmtInt}
                sparkColor="#ff6b1a"
              />
            </div>

            {/* 主图表区 */}
            <div className="overview-grid">
              <div className="panel panel-main">
                <div className="panel-header">
                  <div>
                    <h3>总提及趋势（近 {data.days} 天）</h3>
                    <p>按模型维度展示每日提及次数变化</p>
                  </div>
                  <div className="legend">
                    {data.trend.map((s, i) => (
                      <span className="legend-item" key={s.platform}>
                        <span
                          className="dot"
                          style={{ background: platformColor(s.platform, i) }}
                        />
                        {platformLabel(s.platform)}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="panel-body">
                  <TrendChart data={data} />
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h3>Top1 率排行</h3>
                    <p>各模型 Top1 提及率</p>
                  </div>
                </div>
                <div className="panel-body">
                  <RankingChart data={data} />
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      <style>{OVERVIEW_CSS}</style>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * KPI 卡片 —— 角落 sparkline 用 echarts 画,与原型 ``.kpi-chart`` 同位置
 * ---------------------------------------------------------------------- */

function KpiCard({
  label,
  kpi,
  render,
  unit,
  primary,
  sparkColor,
}: {
  label: string;
  kpi: OverviewKpi;
  render: (v: number) => string;
  unit?: string;
  primary?: boolean;
  sparkColor: string;
}) {
  const up = (kpi.delta_pct ?? 0) >= 0;
  return (
    <div className={`kpi-card${primary ? " kpi-primary" : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {render(kpi.value)}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
      <div className={`kpi-trend ${up ? "up" : "down"}`}>
        {kpi.delta_pct === null ? (
          <span>暂无对比数据</span>
        ) : (
          <>
            <span className="trend-icon">{up ? "↑" : "↓"}</span>
            <span>
              较上一周期 {up ? "+" : ""}
              {(kpi.delta_pct * 100).toFixed(1)}%
            </span>
          </>
        )}
      </div>
      <div className="kpi-chart">
        <Sparkline data={kpi.spark} color={sparkColor} />
      </div>
    </div>
  );
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  const option = useMemo<echarts.EChartsOption>(
    () => ({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "category", show: false, boundaryGap: false },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "line",
          data,
          smooth: true,
          symbol: "none",
          lineStyle: { color, width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color },
              { offset: 1, color: "transparent" },
            ]),
            opacity: 0.25,
          },
        },
      ],
    }),
    [data, color],
  );
  return <EChart option={option} height={50} />;
}

/* -------------------------------------------------------------------------
 * 总提及趋势 / Top1 率排行
 * ---------------------------------------------------------------------- */

function TrendChart({ data }: { data: ProjectOverview }) {
  const option = useMemo<echarts.EChartsOption>(
    () => ({
      grid: { left: 44, right: 20, top: 16, bottom: 30 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#d9d9d9" } },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data.labels,
        axisLine: { lineStyle: { color: "#f0f0f0" } },
        axisTick: { show: false },
        axisLabel: { color: "#8c8c8c", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "#f0f0f0" } },
        axisLabel: { color: "#8c8c8c", fontSize: 11 },
      },
      series: data.trend.map((s, i) => {
        const color = platformColor(s.platform, i);
        return {
          name: platformLabel(s.platform),
          type: "line" as const,
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: s.data,
          itemStyle: { color, borderColor: "#fff", borderWidth: 2 },
          lineStyle: { color, width: 2 },
          areaStyle: { color, opacity: 0.06 },
        };
      }),
    }),
    [data],
  );
  if (data.trend.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="该时间段没有提及数据"
        style={{ padding: 48 }}
      />
    );
  }
  return <EChart option={option} height={340} />;
}

function RankingChart({ data }: { data: ProjectOverview }) {
  const option = useMemo<echarts.EChartsOption>(() => {
    // echarts draws the first category at the bottom, so reverse to put the
    // highest Top1 rate on top like the prototype does.
    const items = [...data.ranking].reverse();
    return {
      grid: { left: 8, right: 48, top: 12, bottom: 12, containLabel: true },
      tooltip: {
        trigger: "item",
        formatter: (p) => {
          const one = Array.isArray(p) ? p[0] : p;
          const i = items[one.dataIndex as number];
          return `${platformLabel(i.platform)}<br/>Top1 率 ${(
            i.top1_rate * 100
          ).toFixed(1)}%<br/>样本 ${i.sample} 条`;
        },
      },
      xAxis: { type: "value", max: 100, show: false },
      yAxis: {
        type: "category",
        data: items.map((i) => platformLabel(i.platform)),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "#4f4f4f", fontSize: 12 },
      },
      series: [
        {
          type: "bar",
          barWidth: 14,
          showBackground: true,
          backgroundStyle: { color: "#f5f6f8", borderRadius: 4 },
          data: items.map((i, idx) => ({
            value: Number((i.top1_rate * 100).toFixed(1)),
            itemStyle: {
              color: platformColor(i.platform, data.ranking.length - 1 - idx),
              borderRadius: 4,
            },
          })),
          label: {
            show: true,
            position: "right",
            formatter: "{c}%",
            fontSize: 12,
            fontWeight: 600,
            color: "#4f4f4f",
          },
        },
      ],
    };
  }, [data]);
  if (data.ranking.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无排行数据"
        style={{ padding: 40 }}
      />
    );
  }
  return <EChart option={option} height={300} />;
}

/** Thin echarts wrapper: mounts once, re-applies options, resizes with the panel. */
function EChart({
  option,
  height,
}: {
  option: echarts.EChartsOption;
  height: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current);
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}

/* -------------------------------------------------------------------------
 * 样式 —— 逐条对齐 docs/ui-sample/css/layout.css 的 #tab-overview 区块
 * ---------------------------------------------------------------------- */

const OVERVIEW_CSS = `
.overview-tab {
  --brand-blue: #1a55e8;
  --brand-blue-light: #4d80f0;
  --text-primary: #181818;
  --text-secondary: #4f4f4f;
  --text-tertiary: #8c8c8c;
  --bg-page: #f5f6f8;
  --border-light: #f0f0f0;
  --color-success: #52c41a;
  --color-danger: #ff4d4f;
  --radius-lg: 8px;
  --shadow-card: 0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.04);
}

.overview-tab .secondary-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  border-bottom: 1px solid var(--border-light);
  padding: 0 4px;
}
.overview-tab .secondary-tab {
  padding: 10px 16px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.overview-tab .secondary-tab:hover { color: var(--brand-blue); }
.overview-tab .secondary-tab.active {
  color: var(--brand-blue);
  border-bottom-color: var(--brand-blue);
  font-weight: 500;
}
.overview-tab .secondary-tabs-right {
  margin-left: auto;
  display: flex;
  align-items: center;
}
.overview-tab .time-selector {
  display: inline-flex;
  background: var(--bg-page);
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}
.overview-tab .time-btn {
  background: transparent;
  border: 0;
  padding: 4px 12px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 4px;
}
.overview-tab .time-btn:hover { color: var(--brand-blue); }
.overview-tab .time-btn.active {
  background: #fff;
  color: var(--brand-blue);
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}

.overview-tab .overview-content { padding: 24px 0 0; }

.overview-tab .kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.overview-tab .kpi-card {
  background: #fff;
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: hidden;
}
.overview-tab .kpi-card.kpi-primary {
  background: linear-gradient(135deg, var(--brand-blue), var(--brand-blue-light));
  color: #fff;
}
.overview-tab .kpi-card.kpi-primary .kpi-label,
.overview-tab .kpi-card.kpi-primary .kpi-trend { color: rgba(255,255,255,0.85); }
.overview-tab .kpi-card.kpi-primary .kpi-value { color: #fff; }
.overview-tab .kpi-card.kpi-primary .kpi-chart { opacity: 0.4; }

.overview-tab .kpi-label {
  font-size: 14px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
  position: relative;
  z-index: 1;
}
.overview-tab .kpi-value {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 8px;
  position: relative;
  z-index: 1;
}
.overview-tab .kpi-unit { font-size: 20px; font-weight: 500; margin-left: 2px; }
.overview-tab .kpi-trend {
  font-size: 12px;
  color: var(--color-success);
  display: flex;
  align-items: center;
  gap: 4px;
  position: relative;
  z-index: 1;
}
.overview-tab .kpi-trend.up { color: var(--color-success); }
.overview-tab .kpi-trend.down { color: var(--color-danger); }
.overview-tab .kpi-chart {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 140px;
  height: 50px;
  opacity: 0.8;
}

.overview-tab .overview-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}
.overview-tab .panel {
  background: #fff;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.overview-tab .panel-header {
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.overview-tab .panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
.overview-tab .panel-header p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-tertiary);
}
.overview-tab .panel-body { padding: 16px 20px; flex: 1; min-width: 0; }

.overview-tab .legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: flex-end;
}
.overview-tab .legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.overview-tab .legend-item .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

@media (max-width: 1400px) {
  .overview-tab .kpi-grid { grid-template-columns: repeat(3, 1fr); }
  .overview-tab .overview-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) {
  .overview-tab .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .overview-tab .overview-grid { grid-template-columns: 1fr; }
}
`;
