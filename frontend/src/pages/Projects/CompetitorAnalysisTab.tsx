import { useEffect, useState } from "react";
import { Empty, Skeleton, Tabs, message } from "antd";
import {
  getCompetitorAnalysis,
  type CompetitorAnalysisOut,
  type CompetitorKpi,
  type CompetitorTrendSeries,
} from "../../api/projects";
import OverviewTable from "./competitorAnalysis/OverviewTable";
import TrendFullPane from "./competitorAnalysis/TrendFullPane";
import DiffPane from "./competitorAnalysis/DiffPane";

interface Props {
  projectId: number;
}

type SubTab = "all" | "trend" | "diff";

export default function CompetitorAnalysisTab({ projectId }: Props) {
  const [data, setData] = useState<CompetitorAnalysisOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [sub, setSub] = useState<SubTab>("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getCompetitorAnalysis(projectId)
      .then((analysis) => {
        if (cancelled) return;
        setData(analysis);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        message.error(err.message || "竞品分析数据加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <Skeleton active paragraph={{ rows: 12 }} />;
  if (!data) return <Empty description="暂无可展示的竞品分析数据" />;

  const overviewRows: CompetitorKpi[] = [];
  if (data.self_brand) overviewRows.push(data.self_brand);
  overviewRows.push(...data.competitors);

  return (
    <div className="cna-root">
      <Tabs
        activeKey={sub}
        onChange={(k) => setSub(k as SubTab)}
        items={[
          { key: "all", label: "全部竞品", children: <AllPane data={data} rows={overviewRows} /> },
          { key: "trend", label: "趋势对比", children: <TrendFullPane data={data} /> },
          { key: "diff", label: "差异化分析", children: <DiffPane data={data} /> },
        ]}
      />
    </div>
  );
}

function AllPane({ data, rows }: { data: CompetitorAnalysisOut; rows: CompetitorKpi[] }) {
  return (
    <div className="cna-grid">
      <OverviewTable rows={rows} />
      <div className="panel panel-wide">
        <div className="panel-header"><h3>提及趋势对比(自身 vs 竞品)</h3></div>
        <div className="panel-body">
          {data.trend.series.length === 0
            ? <Empty description="窗口内尚无每日提及数据" style={{ padding: 32 }} />
            : <TrendChart labels={data.trend.labels} series={data.trend.series} />}
        </div>
      </div>
    </div>
  );
}

// 复用 TrendChart(从原文件搬过来)
function TrendChart({ labels, series }: {
  labels: string[];
  series: CompetitorTrendSeries[];
}) {
  const w = 760, h = 240, padL = 40, padR = 12, padT = 12, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const max = Math.max(...allValues, 1);
  const yMax = Math.ceil(max / 5) * 5 || 5;
  const x = (i: number) => padL + (labels.length > 1 ? (i * innerW) / (labels.length - 1) : innerW / 2);
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => Math.round((yMax * i) / ticks));
  return (
    <svg className="trend-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yMax) * innerH;
        return (
          <g key={i}>
            <line className="grid-line" x1={padL} y1={yy} x2={w - padR} y2={yy} />
            <text className="axis-label" x={padL - 6} y={yy + 3} textAnchor="end">{t}</text>
          </g>
        );
      })}
      {labels.map((lab, i) => {
        if (labels.length > 7 && i % Math.ceil(labels.length / 6) !== 0) return null;
        return <text className="axis-label" key={i} x={x(i)} y={h - 8} textAnchor="middle">{lab.slice(5)}</text>;
      })}
      {series.map((s) => {
        const points = s.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        return (
          <g key={s.brand_canonical}>
            <polyline className="line" stroke={s.color} points={points} />
            {s.data.map((v, i) => v > 0 ? (
              <circle key={i} className="dot" cx={x(i)} cy={y(v)} r={2.5} fill={s.color} />
            ) : null)}
          </g>
        );
      })}
    </svg>
  );
}
