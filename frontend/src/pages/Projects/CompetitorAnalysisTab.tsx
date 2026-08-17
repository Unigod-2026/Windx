/**
 * 竞品分析 tab —— data tab → 竞品分析。布局严格按 docs/ui-sample/index.html
 * #tab-competitor 的精简版:
 *   - 竞品概览(品牌 / 提及率 Top3 / 推荐度 / 情感 / 15 日趋势 sparkline)— 全宽
 *   - 提及趋势对比(自身 vs 竞品,折线,panel-wide)
 *   - 差异化标签云 + 竞争优势矩阵(关注点表待接入,目前占位)
 *
 * 数据由后端 ``GET /projects/{id}/competitor-analysis`` 一次性返回,
 * UI 只渲染,不再做 useMemo 聚合(后端 GROUP BY 已经在 SQL 层做完)。
 * 窗口固定近 15 天(从后端默认 days=15),不做时间段切换。
 */

import { useEffect, useState } from "react";
import { Empty, Skeleton, Tag, message } from "antd";
import { ThunderboltFilled } from "@ant-design/icons";
import {
  getCompetitorAnalysis,
  type CompetitorAnalysisOut,
  type CompetitorKpi,
  type ConcernTagCls,
} from "../../api/projects";

interface Props {
  projectId: number;
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function rateClass(v: number): string {
  if (v >= 0.7) return "rate-high";
  if (v >= 0.4) return "rate-mid";
  return "rate-low";
}

function sentimentClass(v: number | null): string {
  if (v === null) return "rate-low";
  if (v >= 0.7) return "rate-high";
  if (v >= 0.4) return "rate-mid";
  return "rate-low";
}

function tagFontSize(weight: number, max: number): number {
  if (max <= 0) return 13;
  const ratio = weight / max;
  return 12 + ratio * 8; // 12–20px
}

export default function CompetitorAnalysisTab({ projectId }: Props) {
  const [data, setData] = useState<CompetitorAnalysisOut | null>(null);
  const [loading, setLoading] = useState(true);

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
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (loading) {
    return <Skeleton active paragraph={{ rows: 12 }} />;
  }
  if (!data) {
    return <Empty description="暂无可展示的竞品分析数据" />;
  }

  const { self_brand, competitors, trend, concern_tags, total_subtasks } = data;
  const hasData = total_subtasks > 0;

  // Combine self + competitors into one ordered list for the 概览表.
  const overviewRows: CompetitorKpi[] = [];
  if (self_brand) overviewRows.push(self_brand);
  overviewRows.push(...competitors);

  return (
    <div className="cna-root">
      <div className="cna-grid">
        {/* 1. 竞品概览表 — 全宽 */}
        <div className="panel panel-wide">
          <div className="panel-header">
            <h3>竞品概览</h3>
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            {overviewRows.length === 0 ? (
              <Empty
                description={hasData ? "窗口内尚未识别到任何竞品" : "窗口内尚无回答记录"}
                style={{ padding: 32 }}
              />
            ) : (
              <table className="data-table data-table-hover">
                <thead>
                  <tr>
                    <th>品牌</th>
                    <th>提及率</th>
                    <th>Top3</th>
                    <th>推荐度</th>
                    <th>情感</th>
                    <th>15 日趋势</th>
                  </tr>
                </thead>
                <tbody>
                  {overviewRows.map((row) => (
                    <tr key={row.brand_canonical}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          {row.is_self && (
                            <Tag color="blue" style={{ margin: 0 }}>
                              自身
                            </Tag>
                          )}
                          <span style={{ fontWeight: row.is_self ? 600 : 500 }}>
                            {row.name}
                          </span>
                        </div>
                        {row.aliases && row.aliases.length > 0 && (
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--text-tertiary)",
                              marginTop: 2,
                            }}
                          >
                            别名:{row.aliases.slice(0, 3).join("、")}
                            {row.aliases.length > 3 && " …"}
                          </div>
                        )}
                      </td>
                      <td>
                        <span className={rateClass(row.mention_rate)}>
                          {pct(row.mention_rate)}
                        </span>
                      </td>
                      <td>
                        <span className={rateClass(row.top3_rate)}>
                          {pct(row.top3_rate)}
                        </span>
                      </td>
                      <td>
                        <span className={rateClass(row.recommend_rate)}>
                          {pct(row.recommend_rate)}
                        </span>
                      </td>
                      <td>
                        <span className={sentimentClass(row.avg_sentiment)}>
                          {row.avg_sentiment !== null
                            ? `${(row.avg_sentiment * 100).toFixed(0)}%`
                            : "—"}
                        </span>
                      </td>
                      <td>
                        <Sparkline values={row.spark} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 2. 趋势对比图(panel-wide,横跨两列) */}
        <div className="panel panel-wide">
          <div className="panel-header">
            <div>
              <h3>提及趋势对比(自身 vs 竞品)</h3>
              <p>近 {data.days} 天,每日被各模型提及次数对比</p>
            </div>
            <div className="trend-legend">
              {trend.series.map((s) => (
                <span key={s.brand_canonical} className="legend-item">
                  <span
                    className="legend-swatch"
                    style={{ background: s.color }}
                  />
                  {s.name}
                  {s.is_self && (
                    <Tag color="blue" style={{ marginLeft: 4, fontSize: 10 }}>
                      自身
                    </Tag>
                  )}
                </span>
              ))}
            </div>
          </div>
          <div className="panel-body">
            {trend.series.length === 0 ? (
              <Empty description="窗口内尚无每日提及数据" style={{ padding: 32 }} />
            ) : (
              <TrendChart labels={trend.labels} series={trend.series} />
            )}
          </div>
        </div>

        {/* 3. 差异化标签云 */}
        <div className="panel">
          <div className="panel-header">
            <h3>差异化标签云</h3>
            <p>基于 AI 回答中高频关联的项目核心词(由 LLM 抽取的 concern_hits)</p>
          </div>
          <div className="panel-body">
            {concern_tags.length === 0 ? (
              <Empty
                description="窗口内尚未抽取到差异化标签"
                style={{ padding: 32 }}
              />
            ) : (
              <div className="tag-cloud">
                {(() => {
                  const max = Math.max(...concern_tags.map((t) => t.weight));
                  return concern_tags.map((t) => (
                    <span
                      key={t.text}
                      className={`tag tag-${t.cls as ConcernTagCls}`}
                      style={{ ["--size" as never]: (tagFontSize(t.weight, max) / 14).toFixed(2) }}
                      title={`${t.text} · 出现 ${t.weight} 次`}
                    >
                      {t.text}
                    </span>
                  ));
                })()}
              </div>
            )}
          </div>
        </div>

        {/* 4. 竞争优势矩阵 — 关注点表未接入,占位 */}
        <div className="panel">
          <div className="panel-header">
            <h3>竞争优势矩阵</h3>
            <p>客户关注点 × 品牌 — 关注点表待接入</p>
          </div>
          <div className="panel-body">
            <div
              style={{
                padding: "32px 24px",
                textAlign: "center",
                color: "var(--text-tertiary)",
                fontSize: 13,
              }}
            >
              <ThunderboltFilled
                style={{ fontSize: 24, color: "var(--brand-blue)", marginBottom: 8 }}
              />
              <div style={{ marginBottom: 6 }}>竞争优势矩阵需要先配置「客户关注点」</div>
              <div style={{ fontSize: 12 }}>
                关注点表接入后,这里会按 关注点 × 品牌 展示每品牌的优势率(命中 AI 回答中该关注点的比例)
              </div>
            </div>
          </div>
        </div>
      </div>

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
        }
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
        .data-table tbody td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .data-table-hover tbody tr:hover { background: var(--bg-hover, #fafafa); }
        .rate-high { color: var(--color-success, #16a34a); font-weight: 600; }
        .rate-mid  { color: var(--color-warning, #d97706); font-weight: 500; }
        .rate-low  { color: var(--color-danger,  #dc2626); font-weight: 500; }

        .tag-cloud {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
          padding: 12px;
        }
        .tag-cloud .tag {
          display: inline-block;
          padding: 5px 12px;
          border-radius: 14px;
          background: var(--bg-page, #f5f6f8);
          color: var(--text-secondary);
          font-size: calc(14px * var(--size, 1));
          font-weight: 500;
          cursor: pointer;
        }
        .tag-cloud .tag:hover {
          background: var(--brand-blue, #1a55e8);
          color: white;
        }
        .tag-cloud .tag.tag-brand {
          background: var(--brand-blue, #1a55e8);
          color: white;
        }
        .tag-cloud .tag.tag-positive {
          background: var(--color-success-light, #dcfce7);
          color: var(--color-success, #16a34a);
        }
        .tag-cloud .tag.tag-negative {
          background: var(--color-danger-light, #fee2e2);
          color: var(--color-danger, #dc2626);
        }
        .tag-cloud .tag.tag-warn {
          background: var(--color-warning-light, #fef3c7);
          color: var(--color-warning, #d97706);
        }

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
        .trend-chart {
          width: 100%;
          height: 260px;
          display: block;
        }
        .trend-chart .grid-line { stroke: var(--border-light, #f0f0f0); }
        .trend-chart .axis-label { fill: var(--text-quaternary); font-size: 10px; }
        .trend-chart .line { fill: none; stroke-width: 2; }
        .trend-chart .dot { stroke: #fff; stroke-width: 1; }
      `}</style>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Inline SVGs — keeps the bundle thin and the chart looks identical across  */
/* platforms without pulling in a heavyweight chart lib just for a spark.    */
/* -------------------------------------------------------------------------- */

function Sparkline({ values }: { values: number[] }) {
  if (!values || values.length === 0) return <span>—</span>;
  const max = Math.max(...values, 1);
  // 15-day sparkline: wider than the previous 7-day version so the line
  // stays readable, but still fits inside a single table cell.
  const w = 120;
  const h = 22;
  const step = values.length > 1 ? w / (values.length - 1) : 0;
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline
        fill="none"
        stroke="var(--brand-blue, #1a55e8)"
        strokeWidth="1.5"
        points={points}
      />
    </svg>
  );
}

function TrendChart({
  labels,
  series,
}: {
  labels: string[];
  series: { brand_canonical: string; color: string; data: number[]; is_self: boolean }[];
}) {
  const w = 760;
  const h = 240;
  const padL = 40;
  const padR = 12;
  const padT = 12;
  const padB = 28;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  const allValues = series.flatMap((s) => s.data);
  const max = Math.max(...allValues, 1);
  // Round max up to a nice number so the y-axis doesn't get weird ticks.
  const yMax = Math.ceil(max / 5) * 5 || 5;

  const x = (i: number) =>
    padL + (labels.length > 1 ? (i * innerW) / (labels.length - 1) : innerW / 2);
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) =>
    Math.round((yMax * i) / ticks),
  );

  return (
    <svg
      className="trend-chart"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* y grid + labels */}
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yMax) * innerH;
        return (
          <g key={i}>
            <line
              className="grid-line"
              x1={padL}
              y1={yy}
              x2={w - padR}
              y2={yy}
            />
            <text
              className="axis-label"
              x={padL - 6}
              y={yy + 3}
              textAnchor="end"
            >
              {t}
            </text>
          </g>
        );
      })}
      {/* x labels — every ~3rd day to keep readable */}
      {labels.map((lab, i) => {
        if (labels.length > 7 && i % Math.ceil(labels.length / 6) !== 0) {
          return null;
        }
        return (
          <text
            className="axis-label"
            key={i}
            x={x(i)}
            y={h - 8}
            textAnchor="middle"
          >
            {lab.slice(5)}
          </text>
        );
      })}
      {/* lines */}
      {series.map((s) => {
        const points = s.data
          .map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)
          .join(" ");
        return (
          <g key={s.brand_canonical}>
            <polyline className="line" stroke={s.color} points={points} />
            {s.data.map((v, i) =>
              v > 0 ? (
                <circle
                  key={i}
                  className="dot"
                  cx={x(i)}
                  cy={y(v)}
                  r={2.5}
                  fill={s.color}
                />
              ) : null,
            )}
          </g>
        );
      })}
    </svg>
  );
}
