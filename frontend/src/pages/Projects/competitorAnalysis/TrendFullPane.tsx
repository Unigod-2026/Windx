import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";

export default function TrendFullPane({ data }: { data: CompetitorAnalysisOut }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header">
        <div>
          <h3>完整提及趋势对比(自身 vs 竞品)</h3>
          <p>{data.start} ~ {data.end} · 共 {data.days} 天</p>
        </div>
      </div>
      <div className="panel-body">
        <Empty description="占位 — Task 13 填充" style={{ padding: 32 }} />
      </div>
    </div>
  );
}
