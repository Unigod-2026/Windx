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

