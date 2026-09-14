import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";
import { platformLabel } from "../platforms";
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

  // 「模型维度提及率」条形图 label —— compound key → "千问-网页-快速" 等展示名,
  // 与 OverviewTab / 问题提及分析 tab 口径一致;每个 BarChartH 行用展示名渲染。
  // 排序已由后端按 (delivery web→mobile, thinking fast→think, code) 排好,
  // 前端直接用。
  const diffLabels = diff_model.map((m) => platformLabel(m.platform));

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

      {/* 2. 模型维度提及率 —— 每个 (网页/手机 × 快速/思考) 档位各一行 */}
      <div className="panel">
        <div className="panel-header">
          <h3>模型维度提及率</h3>
          <p>
            {diff_model.length} 个模型档位 · 自身 vs 竞品均值
            <span className="diff-legend-hint">网页 / 手机 × 快速 / 思考 各拆开</span>
          </p>
        </div>
        <div className="panel-body">
          {diff_model.length === 0
            ? <Empty description="窗口内尚无模型维度数据" style={{ padding: 32 }} />
            : (
              <BarChartH
                labels={diffLabels}
                // 竞品均值先画,自身后画(SVG 后绘制 = z 序在上),避免自身条较短时
                // 被竞品均值的橙色条压在底下看不到。
                series={[
                  { name: "竞品均值", color: "#ff6b1a", data: diff_model.map((m) => m.competitor_mention_rate * 100) },
                  { name: "自身", color: "#1a55e8", data: diff_model.map((m) => m.self_mention_rate * 100) },
                ]}
              />
            )}
        </div>
      </div>

      {/* 3. 模型竞争四象限 —— 每档位一个点 */}
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
