import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";
import BarChart from "./BarChart";
import BarChartH from "./BarChartH";
import QuadrantChart from "./QuadrantChart";

export default function DiffPane({ data }: { data: CompetitorAnalysisOut }) {
  const { diff_core, diff_model, diff_quadrant } = data;

  // 自身均值 + 竞品均值(用于四象限的参考线)
  const selfAvg = diff_model.length
    ? diff_model.reduce((s, m) => s + m.self_mention_rate, 0) / diff_model.length
    : 0;
  const competitorAvg = diff_model.length
    ? diff_model.reduce((s, m) => s + m.competitor_mention_rate, 0) / diff_model.length
    : 0;

  return (
    <div className="diff-grid">
      {/* 1. 核心指标对比 */}
      <div className="panel">
        <div className="panel-header">
          <h3>核心指标对比</h3>
          <p>自身 vs 竞品均值(总提及率 / Top1 / Top3)</p>
        </div>
        <div className="panel-body">
          {diff_core.labels.length === 0
            ? <Empty description="窗口内尚无对比数据" style={{ padding: 32 }} />
            : (
              <BarChart
                labels={diff_core.labels}
                series={[
                  { name: "自身", color: "#1a55e8", data: diff_core.self },
                  { name: "竞品均值", color: "#ff6b1a", data: diff_core.competitor_avg },
                ]}
                unit="%"
              />
            )}
        </div>
      </div>

      {/* 2. 模型维度提及率 */}
      <div className="panel">
        <div className="panel-header">
          <h3>模型维度提及率</h3>
          <p>{diff_model.length} 个模型 · 自身 vs 竞品均值</p>
        </div>
        <div className="panel-body">
          {diff_model.length === 0
            ? <Empty description="窗口内尚无模型维度数据" style={{ padding: 32 }} />
            : (
              <BarChartH
                labels={diff_model.map((m) => m.platform)}
                series={[
                  { name: "自身", color: "#1a55e8", data: diff_model.map((m) => m.self_mention_rate * 100) },
                  { name: "竞品均值", color: "#ff6b1a", data: diff_model.map((m) => m.competitor_mention_rate * 100) },
                ]}
              />
            )}
        </div>
      </div>

      {/* 3. 模型竞争四象限 */}
      <div className="panel panel-wide">
        <div className="panel-header">
          <h3>模型竞争四象限</h3>
          <p>X = 自身提及率 · Y = 竞品提及率(均值)· 分割线 = 各自均值</p>
        </div>
        <div className="panel-body">
          {diff_quadrant.length === 0
            ? <Empty description="窗口内尚无四象限数据" style={{ padding: 32 }} />
            : <QuadrantChart points={diff_quadrant} selfAvg={selfAvg} competitorAvg={competitorAvg} />}
        </div>
      </div>
    </div>
  );
}
