/**
 * 「质量概览」sub-pane 占位。
 *
 * index.html 设计里有雷达图 / 维度评分 / 模型对比表 / 评分规则详情,
 * 全部依赖 quality scoring engine —— scoring_rules / quality_scores /
 * 关键词+正则+结构三类规则 + 权重 / CSV 导入,后端当前没有这套基础设施。
 *
 * 严格按 index.html 实现需要独立大工程,经与用户确认,本期先交付
 * raw + detail 两个 sub-tab,本 pane 显示「数据建设中」+ 简短说明,
 * 引导用户先用前两个 sub-tab。
 */

import { Empty } from "antd";
import { ExperimentOutlined } from "@ant-design/icons";

export default function QualityOverviewPane() {
  return (
    <div className="qo-root">
      <div className="qo-card">
        <Empty
          image={
            <ExperimentOutlined style={{ fontSize: 64, color: "var(--text-tertiary)" }} />
          }
          imageStyle={{ height: 80 }}
          description={
            <div className="qo-desc">
              <h4>质量评分引擎建设中</h4>
              <p>
                雷达图 / 维度评分 / 评分规则依赖 quality scoring 引擎(评分规则 CRUD +
                关键词 / 正则 / 结构三类规则 + 权重与分值),将在下个版本上线。
              </p>
              <p>
                本版本可先用「<strong>AI 回答原始内容</strong>」和「<strong>答案详情</strong>」两个 sub-tab
                查看 AI 原始回答、思考过程与品牌排名。
              </p>
            </div>
          }
        />
      </div>

      <style>{`
        .qo-root { padding: 12px 0; }
        .qo-card {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          padding: 80px 24px;
          text-align: center;
        }
        .qo-desc h4 { margin: 12px 0 8px; font-size: 16px; color: var(--text-primary); }
        .qo-desc p {
          margin: 4px auto;
          font-size: 13px;
          color: var(--text-secondary);
          max-width: 540px;
          line-height: 1.6;
        }
      `}</style>
    </div>
  );
}
