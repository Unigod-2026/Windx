/**
 * 「全部信源」sub-tab —— 完成态。
 *
 * 数据由后端 ``GET /projects/{id}/source-preferences`` 一次性返回。
 * layout 严格按 docs/superpowers/specs/2026-08-19-source-preferences-tab-design.md
 * + docs/风球GEO监控平台UI/index.html:760-905 的 6-panel 版:
 *   - 顶部 4 张 KPI 卡
 *   - 行 1:信源引用分布(分类饼图)| 官方信源对比(分类柱状图)
 *   - 行 2 (wide):按模型细分的信源偏好(per-model 卡片,top 3 → 展开 top 10)
 *   - 行 3:信源变化趋势(模型筛选下拉)| 稳定信源(跨模型)
 *   - 行 4 (wide):优化建议(规则生成)
 *
 * 注:第 2 块「官方信源对比」原意是「自身品牌官方信源 vs 竞品」,
 * 当前缺竞品单独的引用数据,先退化为"各分类引用条数"的纵向柱状图,
 * 跟左侧饼图共用 type_counts。等品牌域名配置 + 竞品维度上线后再改回对比柱图。
 */

import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, message } from "antd";
import * as echarts from "echarts";
import EChart from "../../../components/EChart";
import {
  getProject,
  getSourcePreferences,
  type ProjectPlatform,
  type SourceByModelTop,
  type SourcePreferenceOut,
  type SourceStableItem,
  type SourceSuggestion,
  type SourceTrendDay,
} from "../../../api/projects";
import { platformLabel, platformColor as platformChartColor, rowKeyOfPlatform } from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";

interface Props {
  projectId: number;
}

const TYPE_COLOR: Record<string, string> = {
  垂类论坛: "#13c2c2",
  新闻网站: "#52c41a",
  官方网站: "#1a55e8",
  百科: "#722ed1",
  社交媒体: "#eb2f96",
  自媒体: "#fa8c16",
  海外网站: "#f5222d",
  其他: "#bfbfbf",
};

const SUGGESTION_ICON_BG: Record<string, string> = {
  focus: "rgba(26, 85, 232, 0.12)",
  "chart-line": "rgba(82, 196, 26, 0.16)",
  swap: "rgba(250, 140, 22, 0.16)",
  warning: "rgba(245, 34, 45, 0.12)",
};

const SUGGESTION_ICON_COLOR: Record<string, string> = {
  focus: "#1a55e8",
  "chart-line": "#52c41a",
  swap: "#fa8c16",
  warning: "#f5222d",
};

export default function AllSources({ projectId }: Props) {
  const [out, setOut] = useState<SourcePreferenceOut | null>(null);
  const [loading, setLoading] = useState(true);
  // 项目当前配置的 platform rows。``null`` 表示还在加载,加载完后用来
  // 在「工具栏全选(= selectedModels 是 null)」时拼出完整 compound key
  // 传给后端,触发 by_model_top 空卡片补齐 —— 否则全选 8 个时只会显示
  // 窗口内有数据的 N 张卡,跟 dropdown 数量对不上。
  const [projectPlatforms, setProjectPlatforms] = useState<ProjectPlatform[] | null>(null);
  // 跟 GlobalToolbar dropdown 选中态同步:用户切换模型时 version+1,触发重 fetch,
  // 且把 selectedModels 传给后端补齐 by_model_top 空卡片,UI 数量对齐 dropdown。
  const toolbar = useToolbarFilter();

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then((d) => { if (!cancelled) setProjectPlatforms(d.platforms); })
      .catch(() => { if (!cancelled) setProjectPlatforms([]); });
    return () => { cancelled = true; };
  }, [projectId]);

  // ``toolbar.selectedModels === null``(全选 / 未筛)时,fallback 用项目
  // 全集 compound key,让后端按全集补齐 by_model_top 空卡片。
  // projectPlatforms 还在加载时返回 ``undefined`` —— 暂时不发请求,等
  // 项目配置加载完再发起,避免「先返回 7 卡 → 再变 8 卡」的闪烁。
  const effectiveModels = useMemo<string[] | null | undefined>(() => {
    if (toolbar.selectedModels !== null) return toolbar.selectedModels;
    if (projectPlatforms === null) return undefined;
    return projectPlatforms.map(rowKeyOfPlatform);
  }, [toolbar.selectedModels, projectPlatforms]);

  // 日期窗口 —— 跟 toolbar 「日期」下拉同步:preset 走 ``days``,自定义
  // 走 ``start``/``end``。null 时 fallback 近 15 天,与后端默认一致。
  const dateQuery = useMemo(
    () => toolbar.selectedDateRange ?? { days: 15 },
    [toolbar.selectedDateRange],
  );
  const dateKey = useMemo(() => JSON.stringify(dateQuery), [dateQuery]);

  // toolbar 「问题」筛选 —— ``null`` 表示「全部」,直接传给后端不传 prompts。
  // prompts 没有像 platforms 那样需要 fallback 到项目全集的需求(后端在空
  // 集合时会显式返回 0 行,这是 toolbar 应用后预期的语义)。
  const promptsKey = useMemo(
    () => (toolbar.selectedPromptIds ? [...toolbar.selectedPromptIds].sort().join("|") : "all"),
    [toolbar.selectedPromptIds],
  );

  useEffect(() => {
    // 项目 platform rows 还没加载完时,先不发起数据请求。
    if (effectiveModels === undefined) return;
    let cancelled = false;
    setLoading(true);
    getSourcePreferences(projectId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
      models: effectiveModels,
      prompts: toolbar.selectedPromptIds ?? undefined,
    })
      .then((d) => { if (!cancelled) setOut(d); })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "信源偏好数据加载失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, toolbar.version, effectiveModels, dateKey, promptsKey]);

  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (!out) return <Empty description="暂无可展示的信源数据" />;
  if (out.kpi.total_references === 0) {
    return <Empty description="窗口内尚无信源数据" style={{ padding: 32 }} />;
  }

  const k = out.kpi;

  return (
    <div className="sp-root">
      {/* KPI 行 */}
      <div className="sp-kpi-row">
        <KpiCard label="总引用条数" value={k.total_references.toLocaleString()} />
        <KpiCard label="唯一信源" value={k.unique_urls.toLocaleString()} />
        <KpiCard label="跨模型共享" value={k.cross_platform_urls.toLocaleString()} />
        <KpiCard label="平均每条引用" value={k.avg_refs_per_subtask.toFixed(1)} />
      </div>

      {/* 行 1:分类饼图 + 官方信源对比(占位) */}
      <div className="sp-row">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>信源引用分布</h3>
              <p>各分类信源被引用的绝对数量</p>
            </div>
          </div>
          <div className="panel-body">
            <TypePie typeCounts={out.type_counts} />
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>官方信源对比</h3>
              <p>各分类信源引用条数</p>
            </div>
          </div>
          <div className="panel-body">
            <TypeBar typeCounts={out.type_counts} />
          </div>
        </div>
      </div>

      {/* 行 2 (wide):按模型细分的信源偏好 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>按模型细分的信源偏好</h3>
            <p>每个大模型引用最多的信源 TOP 3(点击展开 TOP 10)</p>
          </div>
        </div>
        <div className="panel-body">
          <ByModelGrid byModel={out.by_model_top} />
        </div>
      </div>

      {/* 行 3:趋势(带模型筛选) + 稳定信源 */}
      <div className="sp-row">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>信源变化趋势</h3>
              <p>近 {out.days} 天新增 / 流失信源</p>
            </div>
          </div>
          <div className="panel-body">
            <TrendByPlatform trend={out.trend} start={out.start} end={out.end} />
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>稳定信源(跨模型)</h3>
              <p>被 ≥ 2 个模型持续引用的信源</p>
            </div>
          </div>
          <div className="panel-body">
            <StableSourceList items={out.stable_sources} />
          </div>
        </div>
      </div>

      {/* 行 4 (wide):优化建议 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>优化建议</h3>
            <p>基于信源引用结构的可操作建议(规则生成)</p>
          </div>
        </div>
        <div className="panel-body">
          <SuggestionList items={out.suggestions} />
        </div>
      </div>

      <style>{`
        .sp-root { display: flex; flex-direction: column; gap: 12px; padding: 12px 0; }
        .sp-kpi-row {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 12px;
        }
        .sp-kpi-card {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          padding: 14px 18px;
        }
        .sp-kpi-card-label { font-size: 12px; color: var(--text-tertiary); }
        .sp-kpi-card-value { font-size: 22px; font-weight: 600; color: var(--text-primary); margin-top: 6px; }
        /* minmax(0, 1fr) 而不是 1fr 1fr:默认 minmax(auto, 1fr) 会让某个
           panel 里的不可压缩内容(长 stable-title / chart graphic 等)撑爆 column,
           把另一列挤成只有 1 字宽度。强制 0 起点后两侧严格等宽。 */
        .sp-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
        .sp-chart { width: 100%; height: 280px; display: block; }
        .panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
        }
        .panel-header {
          padding: 14px 18px 10px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .panel-header h3 { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary); }
        .panel-header p { margin: 4px 0 0; font-size: 12px; color: var(--text-tertiary); }
        .panel-body { padding: 16px 18px; }
      `}</style>
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="sp-kpi-card">
      <div className="sp-kpi-card-label">{label}</div>
      <div className="sp-kpi-card-value">{value}</div>
    </div>
  );
}

function TypePie({ typeCounts }: { typeCounts: SourcePreferenceOut["type_counts"] }) {
  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (typeCounts.length === 0) return null;
    const total = typeCounts.reduce((s, x) => s + x.count, 0);
    return {
      tooltip: {
        trigger: "item",
        formatter: (p) => {
          const one = Array.isArray(p) ? p[0] : p;
          const value = Number(one.value ?? 0);
          const pct = Number(one.percent ?? 0);
          return `${one.name}<br/>${value.toLocaleString()} 条 · ${pct.toFixed(1)}%`;
        },
      },
      // 中心标题块:echarts 5 的 graphic 在 series 之下渲染,与 donut 中心对齐。
      graphic: [
        {
          type: "text",
          left: "center",
          top: "42%",
          style: {
            text: "总引用",
            fontSize: 12,
            fill: "#8c8c8c",
            fontFamily: "inherit",
          },
        },
        {
          type: "text",
          left: "center",
          top: "50%",
          style: {
            text: total.toLocaleString(),
            fontSize: 22,
            fontWeight: 700,
            fill: "#181818",
            fontFamily: "inherit",
          },
        },
      ],
      // 外侧标签 + 引导线:对齐 docs/风球GEO监控平台UI-261005/ js/charts.js donutChart;
      // 占比 ≥ 4% 的扇区才显示(与 doc 阈值一致),避免 8 个分类挤成乱麻。
      // 单行格式「分类 百分比」(例 「官方网站 11.1%」),不再带 \n 与绝对数值。
      series: [{
        type: "pie",
        radius: ["52%", "72%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: true,
        minShowLabelAngle: 4,
        label: {
          show: true,
          position: "outside",
          formatter: (p) => {
            const one = Array.isArray(p) ? p[0] : p;
            const pct = ((one.percent as number) ?? 0).toFixed(1);
            return `${one.name} ${pct}%`;
          },
          fontSize: 11,
          color: "#39424f",
        },
        labelLine: { show: true, length: 8, length2: 8 },
        itemStyle: { borderColor: "#fff", borderWidth: 2 },
        data: typeCounts.map((s) => ({
          name: s.type,
          value: s.count,
          itemStyle: { color: TYPE_COLOR[s.type] ?? "#bfbfbf" },
        })),
      }],
    };
  }, [typeCounts]);
  if (!option) return <Empty description="暂无分类数据" />;
  return <EChart option={option} className="sp-chart" />;
}

/**
 * 「官方信源对比」柱状图 —— 参考页本来要表达「自身品牌官方信源 vs 竞品」,
 * 但当前缺竞品单独的引用数据,先退化为"各分类引用条数"的纵向柱状图,
 * 跟左侧饼图共用 type_counts,只是视觉维度多一个(数量对比 vs 占比)。
 * 等品牌域名配置 + 竞品维度上线后,这里再改回真正的对比柱图。
 */
function TypeBar({ typeCounts }: { typeCounts: SourcePreferenceOut["type_counts"] }) {
  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (typeCounts.length === 0) return null;
    return {
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 60, right: 24, top: 24, bottom: 40 },
      xAxis: {
        type: "category",
        data: typeCounts.map((s) => s.type),
        axisLabel: { fontSize: 11, interval: 0, rotate: typeCounts.length > 5 ? 30 : 0 },
      },
      yAxis: { type: "value", minInterval: 1, axisLabel: { fontSize: 11 } },
      series: [{
        name: "引用条数",
        type: "bar",
        data: typeCounts.map((s) => ({
          value: s.count,
          itemStyle: { color: TYPE_COLOR[s.type] ?? "#bfbfbf" },
        })),
        barWidth: 28,
        label: {
          show: true,
          position: "top",
          fontSize: 11,
          color: "var(--text-secondary)",
          formatter: "{c}",
        },
      }],
    };
  }, [typeCounts]);
  if (!option) return <Empty description="暂无分类数据" />;
  return <EChart option={option} className="sp-chart" />;
}

/* ------------------------------------------------------------------
 * 按模型细分:每个模型一张卡,top 3 → 展开 top 10
 * ------------------------------------------------------------------ */

function ByModelGrid({ byModel }: { byModel: SourceByModelTop[] }) {
  if (byModel.length === 0) {
    return <Empty description="暂无模型信源数据" />;
  }
  return (
    <>
      <div className="sp-by-model-grid">
        {byModel.map((m) => (
          <ModelCard key={m.platform} model={m} />
        ))}
      </div>
      <style>{`
        .sp-by-model-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 12px;
        }
        .sp-model-card {
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          padding: 16px;
          background: var(--bg-page, #fafafa);
          transition: box-shadow 0.2s;
        }
        .sp-model-card:hover { box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.04); }
        .sp-model-card-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }
        .sp-model-card-title {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          font-weight: 500;
          color: var(--text-primary);
        }
        .sp-model-card-dot {
          width: 10px;
          height: 10px;
          border-radius: 999px;
          flex-shrink: 0;
        }
        .sp-model-card-meta {
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .sp-model-source-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .sp-model-source-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
          font-size: 12px;
        }
        .sp-model-source-name {
          color: var(--text-primary, #1f1f1f);
          font-weight: 500;
          flex: 1;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sp-model-source-count {
          color: var(--text-tertiary);
          background: #fff;
          padding: 2px 8px;
          border-radius: 9px;
          font-size: 11px;
          font-weight: 500;
          flex-shrink: 0;
        }
        .sp-source-expand-btn {
          display: block;
          width: 100%;
          text-align: center;
          margin-top: 8px;
          padding: 6px;
          font-size: 12px;
          color: var(--brand-blue, #1a55e8);
          background: transparent;
          border: 1px dashed var(--border-light, #e8e9ec);
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s;
        }
        .sp-source-expand-btn:hover {
          background: rgba(26, 85, 232, 0.04);
          border-color: var(--brand-blue, #1a55e8);
        }
        .sp-model-card-empty {
          font-size: 12px;
          color: var(--text-tertiary);
          padding: 18px 0;
          text-align: center;
        }
      `}</style>
    </>
  );
}

function ModelCard({ model }: { model: SourceByModelTop }) {
  const [expanded, setExpanded] = useState(false);
  const isEmpty = model.items.length === 0;
  // 后端返回 top 10,前端默认显示前 3,点击展开到 10
  const visible = expanded ? model.items.slice(0, 10) : model.items.slice(0, 3);
  const canExpand = model.items.length > 3;
  // platform 是 compound key(如 qianwen__web__fast),用 dropdown 的展示函数转中文名。
  const displayName = platformLabel(model.platform);
  // 头部圆点色:取该 platform 在 WIZARD_MODELS / PLATFORM_CATALOG 中的色,
  // 与 OverviewTab 的 trend / ranking 系列色对齐。
  const dotColor = platformChartColor(model.platform);

  return (
    <div className="sp-model-card">
      <div className="sp-model-card-head">
        <div className="sp-model-card-title">
          <span
            className="sp-model-card-dot"
            style={{ background: dotColor }}
          />
          {displayName}
        </div>
        <div className="sp-model-card-meta">
          {isEmpty ? "无数据" : `${model.items.length} 个信源`}
        </div>
      </div>
      {isEmpty ? (
        <div className="sp-model-card-empty">该模型窗口内暂无引用数据</div>
      ) : (
        <>
          <div className="sp-model-source-list">
            {visible.map((it) => (
              <div className="sp-model-source-item" key={it.sample_url}>
                <span
                  className="sp-model-source-name"
                  title={it.sample_title || it.media_name}
                >
                  {it.media_name}
                </span>
                <span className="sp-model-source-count">{it.count} 次</span>
              </div>
            ))}
          </div>
          {canExpand && (
            <button
              type="button"
              className="sp-source-expand-btn"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "收起 ↑" : "展开查看 TOP 10 ↓"}
            </button>
          )}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------
 * 信源变化趋势 —— 直接消费后端 ``out.trend``(全局 daily new_urls / lost_urls)。
 * 历史曾用 ``out.trend_by_platform`` 聚合,但 per-platform 维度在数据稀疏时
 * (project 52 等窗口内未跨日的 case)聚合后为空、趋势图空白;
 * 后端 ``compute_source_preferences`` 已经返回 ``trend`` 全局字段,
 * 与 toolbar 已筛选口径一致,直接拿来用即可。
 * ------------------------------------------------------------------ */

function TrendByPlatform({
  trend,
  start,
  end,
}: {
  trend: SourceTrendDay[];
  start: string;
  end: string;
}) {
  const option = useMemo<echarts.EChartsOption | null>(() => {
    // 后端 ``compute_source_preferences`` 只在「当天有数据」的日子才 append,
    // 见 backend/app/services/source_preferences.py:369 ``days_sorted = sorted(daily_urls.keys())``;
    // 这样 15 天窗口内只有 N 天有数据 → trend 只有 N 行 → chart 只画 N 个点。
    // 这里把 trend 展开成完整 ``[start, end]`` 日期范围,缺失日补 ``new=0, lost=0``,
    // 保证 xAxis 每天都有 tick,「新增 / 流失」线铺满整个窗口。
    const filled = fillTrendRange(trend, start, end);
    if (filled.length === 0) return null;
    return {
      tooltip: { trigger: "axis" },
      legend: { data: ["新增", "流失"], top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 44, right: 20, top: 36, bottom: 32 },
      xAxis: {
        type: "category",
        data: filled.map((d) => d.date),
        axisLine: { lineStyle: { color: "#f0f0f0" } },
        axisTick: { show: false },
        axisLabel: {
          color: "#8c8c8c",
          fontSize: 11,
          // 15+ 天的窗口不每 tick 都显示日期,避免挤成乱麻;短窗口(< 10 天)全显示。
          interval: filled.length > 10 ? "auto" : 0,
          formatter: (val: string) => {
            // 「YYYY-MM-DD」取 MM-DD;首尾两个 tick 强制显示,中间按 axisLabel interval 决定。
            return val.slice(5);
          },
        },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { fontSize: 11, color: "#8c8c8c" },
        splitLine: { lineStyle: { color: "#f0f0f0" } },
      },
      // 颜色对齐 docs/风球GEO监控平台UI-261005/ v3.7 降饱和:
      // 新增用模型色板里的降饱和绿 #3d9070(通义千问),流失用降饱和玫红 #b4487e(文心),
      // 替代原饱和 #52c41a / #f5222d,在深色背景或大面积并排时不再刺眼。
      series: [
        {
          name: "新增",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: filled.map((d) => d.new_urls),
          itemStyle: { color: "#3d9070", borderColor: "#fff", borderWidth: 1.5 },
          lineStyle: { color: "#3d9070", width: 1.75 },
          areaStyle: { color: "#3d9070", opacity: 0.1 },
        },
        {
          name: "流失",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: filled.map((d) => d.lost_urls),
          itemStyle: { color: "#b4487e", borderColor: "#fff", borderWidth: 1.5 },
          lineStyle: { color: "#b4487e", width: 1.75 },
          areaStyle: { color: "#b4487e", opacity: 0.1 },
        },
      ],
    };
  }, [trend, start, end]);

  if (!option) return <Empty description="窗口内尚无趋势数据" />;
  return <EChart option={option} className="sp-chart" height={280} />;
}

/** 把 ``trend`` 按 ``[start, end]`` 窗口补全成每日一行,缺失日 ``new_urls=0, lost_urls=0``。
 *  backend 只在当天有数据才写 trend 行,这样窗口内稀疏的天数不会被画出来 —— 前端补全。 */
function fillTrendRange(
  trend: SourceTrendDay[],
  start: string,
  end: string,
): SourceTrendDay[] {
  const byDate = new Map(trend.map((d) => [d.date, d]));
  const days: SourceTrendDay[] = [];
  const s = new Date(`${start}T00:00:00Z`);
  const e = new Date(`${end}T00:00:00Z`);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime()) || s > e) return trend;
  const cursor = new Date(s);
  while (cursor <= e) {
    const iso = cursor.toISOString().slice(0, 10);
    const existing = byDate.get(iso);
    days.push(
      existing ?? { date: iso, new_urls: 0, lost_urls: 0 },
    );
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

/* ------------------------------------------------------------------
 * 稳定信源(跨模型)ranked list
 * ------------------------------------------------------------------ */

function StableSourceList({ items }: { items: SourceStableItem[] }) {
  if (items.length === 0) {
    return <Empty description="暂无跨模型稳定信源(被 ≥ 2 个模型引用)" />;
  }
  return (
    <>
      <div className="sp-stable-list">
        {items.map((s, i) => (
          <div className="sp-stable-item" key={s.url}>
            <div className="sp-stable-rank">{i + 1}</div>
            <div className="sp-stable-info">
              <span
                className="sp-stable-title"
                title={s.url}
              >
                {s.title || s.site || s.url}
              </span>
              <div className="sp-stable-meta">
                被 {s.model_count} / {s.total_models} 个模型引用 · {s.count.toLocaleString()} 次
              </div>
            </div>
            <span
              className="sp-stable-tag"
              style={{ background: TYPE_COLOR[s.type] ?? "#bfbfbf" }}
            >
              {s.type}
            </span>
          </div>
        ))}
      </div>
      <style>{`
        .sp-stable-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
          max-height: 320px;
          overflow-y: auto;
        }
        .sp-stable-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px;
          border-radius: 6px;
          background: var(--bg-page, #fafafa);
          border: 1px solid var(--border-light, #f0f0f0);
        }
        .sp-stable-rank {
          width: 22px;
          height: 22px;
          border-radius: 999px;
          background: var(--brand-blue, #1a55e8);
          color: #fff;
          font-size: 11px;
          font-weight: 600;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .sp-stable-info {
          flex: 1;
          min-width: 0;
        }
        .sp-stable-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          display: block;
        }
        .sp-stable-meta {
          font-size: 11px;
          color: var(--text-tertiary);
          margin-top: 2px;
        }
        .sp-stable-tag {
          padding: 2px 10px;
          border-radius: 999px;
          color: #fff;
          font-size: 11px;
          font-weight: 500;
          flex-shrink: 0;
        }
      `}</style>
    </>
  );
}

/* ------------------------------------------------------------------
 * 优化建议
 * ------------------------------------------------------------------ */

function SuggestionList({ items }: { items: SourceSuggestion[] }) {
  if (items.length === 0) {
    return <Empty description="暂无优化建议" />;
  }
  return (
    <>
      <div className="sp-suggestion-list">
        {items.map((s, i) => (
          <div className="sp-suggestion-item" key={i}>
            <div
              className="sp-suggestion-icon"
              style={{
                background: SUGGESTION_ICON_BG[s.icon] ?? SUGGESTION_ICON_BG.focus,
                color: SUGGESTION_ICON_COLOR[s.icon] ?? SUGGESTION_ICON_COLOR.focus,
              }}
            >
              <SuggestionIcon kind={s.icon} />
            </div>
            <div>
              <div className="sp-suggestion-title">{s.title}</div>
              <div className="sp-suggestion-content">{s.content}</div>
            </div>
          </div>
        ))}
      </div>
      <style>{`
        .sp-suggestion-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .sp-suggestion-item {
          display: flex;
          gap: 12px;
          padding: 12px 14px;
          border-radius: 8px;
          background: var(--bg-page, #fafafa);
          border: 1px solid var(--border-light, #f0f0f0);
        }
        .sp-suggestion-icon {
          width: 32px;
          height: 32px;
          border-radius: 999px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .sp-suggestion-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .sp-suggestion-content {
          font-size: 12px;
          color: var(--text-secondary);
          margin-top: 4px;
          line-height: 1.5;
        }
      `}</style>
    </>
  );
}

function SuggestionIcon({ kind }: { kind: SourceSuggestion["icon"] }) {
  // 用 antd icon family 渲染 4 类图标(简单字符/SVG 占位,避免引入新依赖)
  const charMap: Record<SourceSuggestion["icon"], string> = {
    focus: "◎",
    "chart-line": "↗",
    swap: "⇄",
    warning: "!",
  };
  return (
    <span style={{ fontSize: 16, fontWeight: 700, lineHeight: 1 }}>
      {charMap[kind]}
    </span>
  );
}
