import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";
import TrendChart from "./TrendChart";

export default function TrendFullPane({ data }: { data: CompetitorAnalysisOut }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header">
        <div>
          <h3>完整提及趋势对比(自身 vs 竞品)</h3>
          <p>{data.start} ~ {data.end} · 共 {data.days} 天</p>
        </div>
        <div className="trend-legend">
          {data.trend.series.map((s) => (
            <span key={s.brand_canonical} className="legend-item">
              <span className="legend-swatch" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      </div>
      <div className="panel-body">
        {data.trend.series.length === 0
          ? <Empty description="窗口内尚无每日提及数据" style={{ padding: 32 }} />
          : <TrendChart labels={data.trend.labels} series={data.trend.series} />}
      </div>
    </div>
  );
}