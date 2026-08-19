import { useEffect, useState } from "react";
import { Empty, Skeleton, Tabs, message } from "antd";
import {
  getCompetitorAnalysis,
  type CompetitorAnalysisOut,
  type CompetitorKpi,
} from "../../api/projects";
import OverviewTable from "./competitorAnalysis/OverviewTable";
import TrendFullPane from "./competitorAnalysis/TrendFullPane";
import DiffPane from "./competitorAnalysis/DiffPane";
import TrendChart from "./competitorAnalysis/TrendChart";

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
      <style>{`
        .cna-root {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .cna-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
          padding: 12px 0;
        }
        .diff-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
          padding: 12px 0;
        }
        .diff-grid > .panel-wide { grid-column: span 2; }
        .panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .panel-wide { grid-column: span 2; }
        .panel-header {
          padding: 14px 18px 10px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
        }
        .panel-header h3 {
          margin: 0;
          font-size: 15px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .panel-header p {
          margin: 4px 0 0;
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .panel-body { padding: 16px 18px; }
        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .data-table thead th {
          padding: 10px 12px;
          text-align: left;
          background: var(--bg-page, #fafafa);
          color: var(--text-secondary);
          font-weight: 500;
          font-size: 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .data-table .th-sub {
          font-weight: 400;
          color: var(--text-tertiary);
        }
        .data-table tbody td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .data-table-hover tbody tr:hover { background: var(--bg-hover, #fafafa); }
        .delta-up { color: var(--color-success, #16a34a); font-weight: 600; }
        .delta-down { color: var(--color-danger, #dc2626); font-weight: 600; }
        .delta-neutral { color: var(--text-tertiary); }

        .trend-legend {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          align-items: center;
        }
        .trend-legend .legend-item {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 12px;
          color: var(--text-secondary);
        }
        .trend-legend .legend-swatch {
          display: inline-block;
          width: 10px;
          height: 10px;
          border-radius: 2px;
        }

        .trend-chart, .bar-chart, .quadrant-chart {
          width: 100%;
          height: 260px;
          display: block;
        }
        .trend-chart .grid-line,
        .bar-chart .grid-line { stroke: var(--border-light, #f0f0f0); }
        .trend-chart .axis-label,
        .bar-chart .axis-label,
        .quadrant-chart .axis-label {
          fill: var(--text-quaternary);
          font-size: 10px;
        }
        .trend-chart .line { fill: none; stroke-width: 2; }
        .trend-chart .dot { stroke: #fff; stroke-width: 1; }
        .quadrant-chart .axis-line { stroke: var(--text-tertiary); stroke-width: 1; }
        .quadrant-chart .ref-line {
          stroke: var(--text-quaternary);
          stroke-dasharray: 4 4;
          stroke-width: 1;
        }
        .quadrant-chart .quadrant-label {
          fill: var(--text-tertiary);
          font-size: 11px;
        }
        .quadrant-chart .point-label {
          fill: var(--text-secondary);
          font-size: 11px;
        }
      `}</style>
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