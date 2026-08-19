import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";
import TrendChart from "./TrendChart";

export default function TrendFullPane({ data }: { data: CompetitorAnalysisOut }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header">
        <div>
          <h3>完整提及趋势(自身 vs 竞品)</h3>
          <p>点击下方品牌名称进行多选切换,未选中的品牌以灰色展示</p>
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