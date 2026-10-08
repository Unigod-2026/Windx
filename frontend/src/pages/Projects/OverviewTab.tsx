import { useEffect, useMemo, useState } from "react";
import { useToolbarFilter } from "../../components/ToolbarFilterContext";
import { Empty, Skeleton, message } from "antd";
import * as echarts from "echarts";
import EChart from "../../components/EChart";
import {
  getProjectOverview,
  type OverviewKpi,
  type OverviewModelDimension,
  type ProjectOverview,
} from "../../api/projects";
import { platformColor, platformInkColor, platformLabel } from "./platforms";

interface Props {
  projectId: number;
}

type SubTab = "summary" | "trend" | "model";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "summary", label: "总览数据" },
  { key: "trend", label: "趋势分析" },
  { key: "model", label: "模型维度" },
];

function fmtInt(v: number): string {
  return Math.round(v).toLocaleString("zh-CN");
}

function fmtRate(v: number): string {
  return (v * 100).toFixed(1);
}

// 把 hex 色和灰色(#a0a0a0)按 ``mix`` 比例混合,用来给 KPI 卡和条形图
// 降饱和度。``mix`` 越大越灰,默认 0.3 = "调低一点"。
function softenColor(hex: string, mix = 0.3): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const num = parseInt(m[1], 16);
  const r = (num >> 16) & 0xff;
  const g = (num >> 8) & 0xff;
  const b = num & 0xff;
  const blend = (c: number) => Math.round(c * (1 - mix) + 160 * mix);
  return (
    "#" +
    [blend(r), blend(g), blend(b)]
      .map((c) => c.toString(16).padStart(2, "0"))
      .join("")
  );
}

// 末端标签防重叠 —— v3.7(2026-10-05)docs/风球GEO监控平台UI-261005/overview.md §顺带修掉:
// 7+ 个模型末点挤在右侧 4 处重叠,最小间距 6.3px(12px 文字需 ≥14px)。
// 算法:取每条 series 最后一个非空点 → 按 y 升序 → 强制最小间距 14px → 超出 chart
// 下边界则整体上移 → 被挤开的点用 markLine 引回真实末点。
// 输出一份与 ``data.trend`` 等长的布局信息,喂给每条 series 的 markPoint.coord[1]
// (让标签画在避让后的 y 上)与可选 markLine(被挤开者补引导线)。
// 注意:doc 用的是手画 SVG(lineChart 返回 SVG string),我们这里走 echarts,
//  echarts 5 line 系列没有原生 endLabelData,所以用 markPoint.symbol='none' +
// label-only + coord 定位等价实现。
type EndLabelLayout = {
  /** 避让后的 y 轴值(标签落点)。 */
  displayY: number;
  /** 该 series 真实末点的 y 轴值(用于引导线起点)。 */
  realY: number;
  /** true = 真实末点与标签落点差距 ≥ MIN_GAP - 0.5,需要补 markLine 引导线。 */
  needsGuide: boolean;
};
const END_LABEL_MIN_GAP = 14; // 12px 文字 + 2px 缓冲
function computeEndLabelLayouts(
  series: { platform: string; data: number[] }[],
): EndLabelLayout[] {
  if (series.length === 0) return [];
  // 取每条线最后一个非空点(按 data 索引最大且非 null/undefined)。
  const lastReal = (arr: number[]) => {
    for (let i = arr.length - 1; i >= 0; i--) {
      const v = arr[i];
      if (v !== null && v !== undefined && Number.isFinite(v)) return v;
    }
    return 0;
  };
  const real = series.map((s) => lastReal(s.data));
  // 按真实 y 升序下推(echarts y 轴向上,y 越小越靠下)。
  const sorted = real
    .map((y, i) => ({ i, y }))
    .sort((a, b) => a.y - b.y);
  const display = new Array<number>(real.length);
  let cursor = -Infinity;
  sorted.forEach((p) => {
    const v = Math.max(p.y, cursor + END_LABEL_MIN_GAP);
    display[p.i] = v;
    cursor = v;
  });
  // 溢出下边界(< 0)整体上移,锚点是最低点不动。
  const minDisplay = Math.min(...display);
  if (minDisplay < 0) {
    const shift = -minDisplay;
    for (let k = 0; k < display.length; k++) display[k] += shift;
  }
  // 溢出上边界也保护一下(数值过大时不让标签飞出 chart 顶部)。
  // 这里不强求严格不溢出 —— echarts y 轴通常会自动按数据缩放,标签相对值
  // 偏移在视觉上仍可读。
  return real.map((ry, i) => ({
    displayY: display[i],
    realY: ry,
    needsGuide: Math.abs(display[i] - ry) >= END_LABEL_MIN_GAP - 0.5,
  }));
}

/**
 * 首屏概览 —— 复刻 docs/更新版UI/index.html #tab-overview:
 *   顶部: 二级 Tab(总览数据 / 趋势分析 / 模型维度) + 时间选择器
 *   总览数据 sub-pane:
 *     4 张 KPI 卡片(总提及率 / Top1 / Top3 / 正确率,各占一色),每张带
 *     trend + KPI-meta 分子分母 + sparkline
 *     主图表区: 总提及趋势(跨模型折线) + Top1 率排行
 *   趋势分析 sub-pane:
 *     放大版趋势图(420px)+ 可点击 chip 图例多选过滤(echarts legend)
 *   模型维度 sub-pane:
 *     2×2 子图:提及率 / Top1 / Top2 / Top3 跨模型对比
 *
 * 单一数据源 ``GET /projects/{id}/overview``,已扩展为同时返回
 * mention_rate / correct_rate / model_dimensions。
 */
export default function OverviewTab({ projectId }: Props) {
  const toolbar = useToolbarFilter();
  const [subTab, setSubTab] = useState<SubTab>("summary");
  const [data, setData] = useState<ProjectOverview | null>(null);
  const [loading, setLoading] = useState(true);

  // 日期范围 —— 走 GlobalToolbar(用户在工具栏日期下拉里改);null 时
  // fallback 到「近 15 天」作为安全默认。
  const query = useMemo(() => {
    const tdr = toolbar.selectedDateRange;
    if (tdr) {
      return "days" in tdr
        ? { days: tdr.days }
        : { start: tdr.start, end: tdr.end };
    }
    return { days: 15 };
  }, [toolbar.selectedDateRange]);

  // 把 toolbar 的「模型筛选版本号」拼进 useEffect 依赖,点「应用」就重拉。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectOverview(projectId, {
      ...query,
      platforms: toolbar.selectedModels ?? undefined,
      prompt_ids: toolbar.selectedPromptIds ?? undefined,
    })
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
  }, [
    projectId,
    query,
    toolbar.version,
    toolbar.selectedModels,
    toolbar.selectedPromptIds,
  ]);

  return (
    <div className="overview-tab">
      {/* 二级 Tab —— 时间选择统一走 GlobalToolbar,不在这里重复展示。 */}
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
      </div>

      <div className="overview-content">
        {loading || !data ? (
          <Skeleton active paragraph={{ rows: 10 }} />
        ) : (
          <>
            <div
              className={`sub-pane${subTab === "summary" ? " active" : ""}`}
              data-sub="summary"
            >
              <SummaryPane data={data} />
            </div>
            <div
              className={`sub-pane${subTab === "trend" ? " active" : ""}`}
              data-sub="trend"
            >
              <TrendPane data={data} />
            </div>
            <div
              className={`sub-pane${subTab === "model" ? " active" : ""}`}
              data-sub="model"
            >
              <ModelPane data={data} />
            </div>
          </>
        )}
      </div>

      <style>{OVERVIEW_CSS}</style>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * 总览数据 sub-pane — 4 张 KPI 卡片 + 总提及趋势 + Top1 率排行
 * ---------------------------------------------------------------------- */

function SummaryPane({ data }: { data: ProjectOverview }) {
  const totalAnswer = data.answer_count.value;
  const totalMentions = data.total_mentions.value;
  const totalQuestions = data.question_count.value;
  const top1Count = data.top1_rate.value * totalMentions;
  const top3Count = data.top3_rate.value * totalMentions;
  const correctCount = data.correct_rate.value * totalAnswer;
  return (
    <>
      {/* 4 张 KPI 卡(对齐更新版UI):总提及率 / Top1 / Top3 / 正确率 */}
      <div className="kpi-grid kpi-grid-4">
        <KpiCard
          variant="primary"
          label="总提及率"
          kpi={data.mention_rate}
          renderRate
          deltaSuffix=""
          meta={
            <>
              <span>
                总提问 <strong>{fmtInt(totalQuestions)}</strong> 次
              </span>
              <span>
                提及答案 <strong>{fmtInt(totalMentions)}</strong> / 总答案{" "}
                <strong>{fmtInt(totalAnswer)}</strong>
              </span>
            </>
          }
        />
        <KpiCard
          variant="green"
          label="Top1 提及率"
          kpi={data.top1_rate}
          renderRate
          deltaSuffix=""
          meta={
            <>
              <span>
                总提问 <strong>{fmtInt(totalQuestions)}</strong> 次
              </span>
              <span>
                Top1 答案 <strong>{fmtInt(top1Count)}</strong> / 提及答案{" "}
                <strong>{fmtInt(totalMentions)}</strong>
              </span>
            </>
          }
        />
        <KpiCard
          variant="cyan"
          label="Top3 提及率"
          kpi={data.top3_rate}
          renderRate
          deltaSuffix=""
          meta={
            <>
              <span>
                总提问 <strong>{fmtInt(totalQuestions)}</strong> 次
              </span>
              <span>
                Top3 答案 <strong>{fmtInt(top3Count)}</strong> / 提及答案{" "}
                <strong>{fmtInt(totalMentions)}</strong>
              </span>
            </>
          }
        />
        <KpiCard
          variant="purple"
          label="正确率"
          kpi={data.correct_rate}
          renderRate
          deltaSuffix=""
          meta={
            <>
              <span>
                错误率 <strong>{fmtRate(1 - data.correct_rate.value)}</strong>%
              </span>
              <span>
                正确 <strong>{fmtInt(correctCount)}</strong> / 总答案{" "}
                <strong>{fmtInt(totalAnswer)}</strong>
              </span>
            </>
          }
        />
      </div>

      {/* 主图表区 — 总提及趋势(跨模型) + Top1 率排行 */}
      <div className="overview-grid overview-grid-2col">
        <div className="panel panel-main">
          <div className="panel-header">
            <div>
              <h3>总提及趋势（近 {data.days} 天）</h3>
              <p>按模型维度展示每日提及次数变化</p>
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
  );
}

/* -------------------------------------------------------------------------
 * 趋势分析 sub-pane — 放大版折线图 + 可点击 chip 图例多选
 * ---------------------------------------------------------------------- */

function TrendPane({ data }: { data: ProjectOverview }) {
  // 平台选中状态。初始化全选,点 chip 切换单个平台的可见性。
  const allPlatforms = data.trend.map((s) => s.platform);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(allPlatforms),
  );

  const toggle = (p: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  };

  // echarts 用 selectedMap 控制每条线的可见性;未选中的线以灰色绘制,
  // 让"被过滤掉"和"被保留"的视觉对比明显。
  // v3.7:面积填充关闭(避免 7+ 层 6% 透明叠加的灰紫雾)、线宽 1.75、描点 5。
  // 末端标签按"所有线"的真实末点整体算布局(用户切 chip 选中不会跳),
  // 已关闭的 chip 标签也保留但染灰,用户取消勾选后还能在右侧看到位置提示。
  const endLayouts = computeEndLabelLayouts(data.trend);
  const series: echarts.EChartsOption["series"] = data.trend.map((s, i) => {
    const color = platformColor(s.platform, i);
    const ink = platformInkColor(s.platform, i);
    const isOn = selected.has(s.platform);
    const layout = endLayouts[i];
    const lastIdx = s.data.length - 1;
    return {
      name: platformLabel(s.platform),
      type: "line" as const,
      smooth: true,
      symbol: "circle",
      symbolSize: 5,
      data: s.data,
      itemStyle: isOn
        ? { color, borderColor: "#fff", borderWidth: 1.5 }
        : { color: "#cfd4dc", borderColor: "#fff", borderWidth: 1.5 },
      lineStyle: {
        color: isOn ? color : "#cfd4dc",
        width: 1.75,
        type: isOn ? "solid" : "dashed",
      },
      areaStyle: { color: "transparent" },
      showSymbol: false,
      // 末端标签:markPoint.symbol='none' + label-only(echarts 没有原生 line.endLabelData)。
      markPoint: {
        symbol: "none",
        animation: false,
        silent: true,
        label: {
          show: true,
          position: "right",
          distance: 6,
          color: isOn ? ink : "#c8ccd4",
          fontSize: 11,
          fontWeight: 500,
          formatter: () => platformLabel(s.platform),
        },
        data: [{ name: s.platform, coord: [lastIdx, layout.displayY] }],
      },
      // 被避让算法挤开者补细引导线。
      // echarts markLine 类型不收 {coord:[x,y]},改用 xAxis + yAxis 显式指定。
      ...(layout.needsGuide
        ? {
            markLine: {
              symbol: "none",
              silent: true,
              animation: false,
              lineStyle: {
                color: isOn ? color : "#cfd4dc",
                type: "dashed",
                width: 1,
                opacity: 0.55,
              },
              label: { show: false },
              data: [
                { xAxis: lastIdx, yAxis: layout.realY },
                { xAxis: lastIdx, yAxis: layout.displayY },
              ],
            },
          }
        : {}),
    };
  });

  const option = useMemo<echarts.EChartsOption>(
    () => ({
      grid: { left: 50, right: 96, top: 24, bottom: 36 },
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
      series,
    }),
    [data, series],
  );

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h3>总提及趋势（放大版）</h3>
          <p>点击下方模型名称进行多选切换,未选中的模型以灰色展示</p>
        </div>
      </div>
      <div className="chart-legend">
        {data.trend.map((s, i) => {
          const isOn = selected.has(s.platform);
          return (
            <button
              key={s.platform}
              type="button"
              className={`legend-chip${isOn ? "" : " off"}`}
              onClick={() => toggle(s.platform)}
            >
              <i style={{ background: platformColor(s.platform, i) }} />
              {platformLabel(s.platform)}
            </button>
          );
        })}
      </div>
      <div className="panel-body">
        {data.trend.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="该时间段没有提及数据"
            style={{ padding: 48 }}
          />
        ) : (
          <EChart option={option} className="chart-trend-tall" />
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * 模型维度 sub-pane — 2×2 子图:提及率 / Top1 / Top2 / Top3
 * ---------------------------------------------------------------------- */

function ModelPane({ data }: { data: ProjectOverview }) {
  if (data.model_dimensions.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="该时间段没有模型数据"
        style={{ padding: 48 }}
      />
    );
  }
  // echarts 横向条按 best→worst 排序(从下到 top),所以 reverse 让最好的
  // 显示在最上方,跟其他子图保持视觉一致。
  const reversed = [...data.model_dimensions].reverse();
  const labels = reversed.map((d) => platformLabel(d.platform));

  const makeOption = (
    key: keyof Pick<
      OverviewModelDimension,
      "mention_rate" | "top1_rate" | "top2_rate" | "top3_rate"
    >,
    suffix: string,
  ): echarts.EChartsOption => ({
    grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        const one = Array.isArray(p) ? p[0] : p;
        const i = reversed[one.dataIndex as number];
        return `${platformLabel(i.platform)}<br/>${(
          (i[key] as number) * 100
        ).toFixed(1)}%<br/>样本 ${i.sample} 条`;
      },
    },
    xAxis: { type: "value", max: 100, show: false },
    yAxis: {
      type: "category",
      data: labels,
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
        data: reversed.map((i, idx) => ({
          value: Number(((i[key] as number) * 100).toFixed(1)),
          itemStyle: {
            color: softenColor(platformColor(i.platform, data.model_dimensions.length - 1 - idx)),
            borderRadius: 4,
          },
        })),
        label: {
          show: true,
          position: "right",
          formatter: `{c}${suffix}`,
          fontSize: 12,
          fontWeight: 600,
          // v3.7:多色 graphic 背景下用单色深中性灰 #39424f,与 RankingChart 同款,
          // 避免 12px 文字落在 7+ 色 graphic 上对比度参差(<4.5)。
          color: "#39424f",
        },
      },
    ],
  });

  // 高度自适应:每行 22px(bar 14 + 间距 8)+ padding 32;最小 170 兜底。
  // project 52 全量 16 行 → 16*22 + 32 = 384px,避免 13+ 行时被裁。
  // 2x2 grid 每行 2 个 panel,clamp 上限到 420 避免单格过高挤另一行。
  const dimHeight = Math.min(420, Math.max(170, data.model_dimensions.length * 22 + 32));

  return (
    <div className="model-dim-grid">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>各模型提及率</h3>
            <p>当前时间范围:近 {data.days} 天</p>
          </div>
        </div>
        <div className="panel-body">
          <EChart option={makeOption("mention_rate", "%")} className="chart-dim" height={dimHeight} />
        </div>
      </div>
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Top1 提及排名</h3>
            <p>各模型答案排名第 1 占比</p>
          </div>
        </div>
        <div className="panel-body">
          <EChart option={makeOption("top1_rate", "%")} className="chart-dim" height={dimHeight} />
        </div>
      </div>
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Top2 提及排名</h3>
            <p>各模型答案排名前 2 占比</p>
          </div>
        </div>
        <div className="panel-body">
          <EChart option={makeOption("top2_rate", "%")} className="chart-dim" height={dimHeight} />
        </div>
      </div>
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Top3 提及排名</h3>
            <p>各模型答案排名前 3 占比</p>
          </div>
        </div>
        <div className="panel-body">
          <EChart option={makeOption("top3_rate", "%")} className="chart-dim" height={dimHeight} />
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * KPI 卡片 —— 4 种 variant(对应更新版UI 的 4 张色卡)
 * ---------------------------------------------------------------------- */

type KpiVariant = "primary" | "green" | "cyan" | "purple";

function KpiCard({
  variant,
  label,
  kpi,
  renderRate,
  deltaSuffix,
  meta,
}: {
  variant: KpiVariant;
  label: string;
  kpi: OverviewKpi;
  renderRate?: boolean;
  deltaSuffix?: string;
  meta: React.ReactNode;
}) {
  const up = (kpi.delta_pct ?? 0) >= 0;
  return (
    <div className={`kpi-card kpi-${variant}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {renderRate ? fmtRate(kpi.value) : fmtInt(kpi.value)}
        {renderRate && <span className="kpi-unit">%</span>}
      </div>
      <div className={`kpi-trend ${up ? "up" : "down"}`}>
        {kpi.delta_pct === null ? (
          <span>暂无对比数据</span>
        ) : (
          <>
            <span className="trend-icon">{up ? "↑" : "↓"}</span>
            <span>
              较上一周期 {up ? "+" : ""}
              {(kpi.delta_pct * 100).toFixed(1)}
              {deltaSuffix || "%"}
            </span>
          </>
        )}
      </div>
      <div className="kpi-meta">{meta}</div>
      <div className="kpi-chart">
        <Sparkline data={kpi.spark} />
      </div>
    </div>
  );
}

function Sparkline({ data }: { data: number[] }) {
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
          lineStyle: { color: "rgba(255,255,255,0.85)", width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(255,255,255,0.4)" },
              { offset: 1, color: "rgba(255,255,255,0.0)" },
            ]),
            opacity: 0.6,
          },
        },
      ],
    }),
    [data],
  );
  return <EChart option={option} height={50} />;
}

/* -------------------------------------------------------------------------
 * 总览数据 sub-pane 里的总提及趋势 + Top1 率排行
 * ---------------------------------------------------------------------- */

function TrendChart({ data }: { data: ProjectOverview }) {
  // v3.7:末端标签防重叠 —— 16 条线全选时,真实末点会挤成一团,这里
  // 给每条线算一个「避让后的 y」用于 markPoint 定位,被挤开者补 markLine 引导线。
  const endLayouts = computeEndLabelLayouts(data.trend);
  const option = useMemo<echarts.EChartsOption>(
    () => ({
      grid: { left: 44, right: 92, top: 16, bottom: 30 },
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
        const ink = platformInkColor(s.platform, i);
        const layout = endLayouts[i];
        const lastIdx = s.data.length - 1;
        return {
          name: platformLabel(s.platform),
          type: "line" as const,
          smooth: true,
          symbol: "circle",
          symbolSize: 5,
          data: s.data,
          itemStyle: { color, borderColor: "#fff", borderWidth: 1.5 },
          lineStyle: { color, width: 1.75 },
          // v3.7:关闭面积填充(7+ 层 6% 透明叠加产生灰紫雾);
          // 描点隐藏(全量 16 条时 r=5 圆点会盖住线);hover 时 echarts 自动恢复。
          areaStyle: { color: "transparent" },
          showSymbol: false,
          // 末端标签(模型名):用 markPoint.symbol='none' + label-only 替代
          //  echarts 不存在的 line.endLabelData,coord[1] 取「避让后的 y」做防重叠。
          markPoint: {
            symbol: "none",
            animation: false,
            silent: true,
            label: {
              show: true,
              position: "right",
              distance: 6,
              color: ink,
              fontSize: 11,
              fontWeight: 500,
              formatter: () => platformLabel(s.platform),
            },
            data: [{ name: s.platform, coord: [lastIdx, layout.displayY] }],
          },
          // 被避让算法挤开者补细引导线(真实末点 → 标签落点)。
          // echarts markLine 类型不收 {coord:[x,y]},改用 xAxis + yAxis 显式指定。
          ...(layout.needsGuide
            ? {
                markLine: {
                  symbol: "none",
                  silent: true,
                  animation: false,
                  lineStyle: { color, type: "dashed", width: 1, opacity: 0.55 },
                  label: { show: false },
                  data: [
                    { xAxis: lastIdx, yAxis: layout.realY },
                    { xAxis: lastIdx, yAxis: layout.displayY },
                  ],
                },
              }
            : {}),
        };
      }),
    }),
    [data, endLayouts],
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
  return <EChart option={option} height={300} />;
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
              color: softenColor(platformColor(i.platform, data.ranking.length - 1 - idx)),
              borderRadius: 4,
            },
          })),
          // v3.7:数值标签颜色 — 多色 graphic 背景下,用单色深中性灰 #39424f
          // (与 doc chart-top1-ranking 同款)更稳,任意色相对比度均 ≥4.5。
          // 若用 ink 色,得给每行挂 rich text,且 echarts rich.color 不接受 callback,
          // 故统一 #39424f,与 ModelPane 柱状图保持一致。
          label: {
            show: true,
            position: "right",
            formatter: (p) => {
              const one = Array.isArray(p) ? p[0] : p;
              const i = items[one.dataIndex as number];
              return `${(i.top1_rate * 100).toFixed(1)}%`;
            },
            fontSize: 12,
            fontWeight: 600,
            color: "#39424f",
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
  // 高度自适应:每行 22px(bar 14 + 间距 8)+ padding 32;最小 280 兜底。
  // project 52 全量 16 行 → 16*22 + 32 = 384px,避免 13+ 行时被裁。
  const height = Math.max(280, data.ranking.length * 22 + 32);
  return <EChart option={option} height={height} />;
}

/* -------------------------------------------------------------------------
 * 样式 —— 逐条对齐 docs/更新版UI/css/layout.css 的 #tab-overview 区块
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

/* sub-pane 切换:对齐更新版UI 的 #tab-overview .sub-pane 默认隐藏规则 */
.overview-tab .sub-pane { display: none; }
.overview-tab .sub-pane.active { display: block; }

/* 4 列 KPI grid */
.overview-tab .kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
@media (max-width: 1100px) {
  .overview-tab .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}

.overview-tab .kpi-card {
  border-radius: var(--radius-lg);
  padding: 18px 20px 14px;
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: hidden;
  min-height: 156px;
  color: #fff;
}
.overview-tab .kpi-card.kpi-primary {
  background: linear-gradient(135deg, #324e86, #3f63ab);
}
.overview-tab .kpi-card.kpi-green {
  background: linear-gradient(135deg, #2b6951, #358265);
}
.overview-tab .kpi-card.kpi-cyan {
  background: linear-gradient(135deg, #2e6776, #387e8f);
}
.overview-tab .kpi-card.kpi-purple {
  background: linear-gradient(135deg, #5c3984, #7749ab);
}
.overview-tab .kpi-card .kpi-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.95);
  margin-bottom: 6px;
  position: relative;
  z-index: 1;
}
.overview-tab .kpi-card .kpi-value {
  font-size: 30px;
  font-weight: 700;
  color: #fff;
  line-height: 1.2;
  margin-bottom: 6px;
  position: relative;
  z-index: 1;
}
.overview-tab .kpi-unit {
  font-size: 18px;
  font-weight: 500;
  margin-left: 2px;
}
.overview-tab .kpi-card .kpi-trend {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.95);
  display: flex;
  align-items: center;
  gap: 4px;
  position: relative;
  z-index: 1;
  margin-bottom: 10px;
}
.overview-tab .kpi-trend.up { color: #d9f7be; }
.overview-tab .kpi-trend.down { color: #ffd6d6; }
.overview-tab .kpi-trend .trend-icon { font-weight: 600; }

/* KPI-meta 双行(总提问 + 分子/分母);更新版UI 里 .kpi-meta 位于趋势行下方 */
.overview-tab .kpi-meta {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.88);
  display: flex;
  flex-direction: column;
  gap: 3px;
  position: relative;
  z-index: 1;
}
.overview-tab .kpi-meta strong {
  color: #fff;
  font-weight: 600;
}

.overview-tab .kpi-chart {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 140px;
  height: 50px;
  opacity: 0.4;
  pointer-events: none;
}

.overview-tab .overview-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}
@media (max-width: 1100px) {
  .overview-tab .overview-grid { grid-template-columns: 1fr; }
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

/* 趋势分析 chip 图例 */
.overview-tab .chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 20px 14px;
}
.overview-tab .legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--bg-page);
  border: 1px solid #e8e9ec;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  font-family: inherit;
}
.overview-tab .legend-chip:hover {
  border-color: var(--brand-blue);
  color: var(--brand-blue);
}
.overview-tab .legend-chip i {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
}
.overview-tab .legend-chip.off {
  background: #fafafa;
  border-color: #ececec;
  color: #bbb;
}

/* 趋势分析大图 / 模型维度 2×2 子图 */
.overview-tab .chart-trend-tall {
  height: min(420px, calc(100vh - 340px));
  min-height: 280px;
}
.overview-tab .model-dim-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  /* 留出底部 24px 缓冲,让面板不贴边 */
  padding-bottom: 4px;
}
@media (max-width: 1100px) {
  .overview-tab .model-dim-grid { grid-template-columns: 1fr; }
}
.overview-tab .chart-dim {
  /* 模型维度 2×2 子图高度由 JS 计算(max(170, N*22+32),上限 420),
     inline style 会覆盖此 CSS。仅作为 fallback。
     目标:project 52 全量 16 行(16*22+32=384)不被裁。 */
  min-height: 170px;
}
`;