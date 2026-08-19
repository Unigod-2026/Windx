import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, message } from "antd";
import * as echarts from "echarts";
import EChart from "../../components/EChart";
import {
  getSourcePreferences,
  type SourcePreferenceItem,
  type SourcePreferenceOut,
  type SourceTrendDay,
} from "../../api/projects";

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

export default function SourcePreferencesTab({ projectId }: Props) {
  const [out, setOut] = useState<SourcePreferenceOut | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSourcePreferences(projectId)
      .then((d) => { if (!cancelled) setOut(d); })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "信源偏好数据加载失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  const typeOption = useMemo<echarts.EChartsOption | null>(() => {
    if (!out || out.type_counts.length === 0) return null;
    return {
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { orient: "horizontal", bottom: 0, textStyle: { fontSize: 11 } },
      series: [{
        type: "pie",
        radius: ["45%", "70%"],
        avoidLabelOverlap: true,
        label: { show: false },
        data: out.type_counts.map((s) => ({
          name: s.type,
          value: s.count,
          itemStyle: { color: TYPE_COLOR[s.type] ?? "#bfbfbf" },
        })),
      }],
    };
  }, [out]);

  const platformOption = useMemo<echarts.EChartsOption | null>(() => {
    if (!out || out.platform_slices.length === 0) return null;
    return {
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: ["引用条数", "唯一 URL"], top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: { type: "category", data: out.platform_slices.map((p) => p.platform) },
      yAxis: [
        { type: "value", name: "引用条数", axisLabel: { fontSize: 11 } },
        { type: "value", name: "唯一 URL", axisLabel: { fontSize: 11 } },
      ],
      series: [
        {
          name: "引用条数",
          type: "bar",
          data: out.platform_slices.map((p) => p.total_refs),
          itemStyle: { color: "#1a55e8" },
          barWidth: 24,
        },
        {
          name: "唯一 URL",
          type: "bar",
          yAxisIndex: 1,
          data: out.platform_slices.map((p) => p.unique_urls),
          itemStyle: { color: "#ff6b1a" },
          barWidth: 24,
        },
      ],
    };
  }, [out]);

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

      {/* 行 1:分类饼图 + 按模型柱状图 */}
      <div className="sp-row">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>信源分类分布</h3>
              <p>按 host 子串分类的引用条数占比</p>
            </div>
          </div>
          <div className="panel-body">
            {typeOption
              ? <EChart option={typeOption} className="sp-chart" />
              : <Empty description="暂无分类数据" />}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>按模型引用分布</h3>
              <p>每个大模型引用了多少信源 / 其中多少唯一</p>
            </div>
          </div>
          <div className="panel-body">
            {platformOption
              ? <EChart option={platformOption} className="sp-chart" />
              : <Empty description="暂无模型数据" />}
          </div>
        </div>
      </div>

      {/* 行 2:Top 50 信源 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>信源引用 Top 50</h3>
            <p>按引用次数倒序 · 共 {out.top_sources.length} 条</p>
          </div>
        </div>
        <div className="panel-body">
          <TopSourcesTable items={out.top_sources} />
        </div>
      </div>

      {/* 行 3:变化趋势双折线 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>信源变化趋势</h3>
            <p>每日新增 / 流失 URL 数(按 created_at 所在本地日期 set diff)</p>
          </div>
        </div>
        <div className="panel-body">
          <TrendChart data={out.trend} />
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
        .sp-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
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

function TopSourcesTable({ items }: { items: SourcePreferenceItem[] }) {
  if (items.length === 0) return <Empty description="暂无信源明细" />;
  return (
    <table className="data-table data-table-hover" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr>
          <th style={{ width: 48, textAlign: "left" }}>#</th>
          <th style={{ textAlign: "left" }}>信源</th>
          <th style={{ width: 110 }}>类型</th>
          <th style={{ width: 90, textAlign: "right" }}>引用次数</th>
          <th style={{ width: 220 }}>平台</th>
          <th style={{ width: 110 }}>最近引用</th>
        </tr>
      </thead>
      <tbody>
        {items.map((it, i) => (
          <tr key={it.url}>
            <td>{i + 1}</td>
            <td>
              <a href={it.url} target="_blank" rel="noopener noreferrer" style={{ color: "#1a55e8" }}>
                {it.title || it.site || it.url}
              </a>
              {it.title && (
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
                  {it.site || it.url}
                </div>
              )}
            </td>
            <td>
              <span
                style={{
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: TYPE_COLOR[it.type] ?? "#bfbfbf",
                  color: "#fff",
                  fontSize: 11,
                }}
              >
                {it.type}
              </span>
            </td>
            <td style={{ textAlign: "right", fontWeight: 600 }}>{it.count}</td>
            <td>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {it.platforms.map((p) => (
                  <span
                    key={p}
                    style={{
                      padding: "1px 8px",
                      borderRadius: 999,
                      background: "var(--bg-page, #fafafa)",
                      border: "1px solid #e8e9ec",
                      fontSize: 11,
                      color: "var(--text-secondary)",
                    }}
                  >
                    {p}
                  </span>
                ))}
              </div>
            </td>
            <td style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
              {it.last_seen.slice(0, 10)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TrendChart({ data }: { data: SourceTrendDay[] }) {
  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (data.length === 0) return null;
    return {
      tooltip: { trigger: "axis" },
      legend: { data: ["新增", "流失"], top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: { type: "category", data: data.map((d) => d.date) },
      yAxis: { type: "value", minInterval: 1, axisLabel: { fontSize: 11 } },
      series: [
        {
          name: "新增",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: data.map((d) => d.new_urls),
          itemStyle: { color: "#52c41a" },
          lineStyle: { color: "#52c41a", width: 2 },
          areaStyle: { color: "#52c41a", opacity: 0.08 },
        },
        {
          name: "流失",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: data.map((d) => d.lost_urls),
          itemStyle: { color: "#f5222d" },
          lineStyle: { color: "#f5222d", width: 2 },
          areaStyle: { color: "#f5222d", opacity: 0.08 },
        },
      ],
    };
  }, [data]);
  if (!option) return <Empty description="窗口内尚无趋势数据" />;
  return <EChart option={option} className="sp-chart" height={280} />;
}
