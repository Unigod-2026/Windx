import type { QuadrantPoint } from "../../../api/projects";

interface Props {
  points: QuadrantPoint[];
  selfAvg: number;
  competitorAvg: number;
}

/**
 * 四象限散点图 — X = 自身提及率 · Y = 竞品均值 · 分割线 = 各自均值。
 * viewBox 设为 1400×520,横轴接近面板宽度(panel-wide 跨整行);
 * CSS 端给 .quadrant-chart 一个更高的 height,保留上下内边距让图更大。
 */
export default function QuadrantChart({ points, selfAvg, competitorAvg }: Props) {
  const w = 1400, h = 520;
  const padL = 80, padR = 48, padT = 36, padB = 60;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const xMax = 1, yMax = 1;
  const x = (v: number) => padL + (v / xMax) * innerW;
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  return (
    <svg className="quadrant-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {/* axes */}
      <line className="axis-line" x1={padL} y1={padT} x2={padL} y2={padT + innerH} />
      <line className="axis-line" x1={padL} y1={padT + innerH} x2={w - padR} y2={padT + innerH} />
      {/* quadrant split lines (avg) */}
      <line className="ref-line" x1={x(selfAvg)} y1={padT} x2={x(selfAvg)} y2={padT + innerH} />
      <line className="ref-line" x1={padL} y1={y(competitorAvg)} x2={w - padR} y2={y(competitorAvg)} />
      {/* axis labels */}
      <text className="axis-label" x={w - padR} y={padT + innerH + 28} textAnchor="end">自身提及率</text>
      <text className="axis-label" x={padL - 12} y={padT - 14} textAnchor="end">竞品提及率</text>
      {/* quadrant labels */}
      <text className="quadrant-label" x={padL + innerW * 0.75} y={padT + 18} textAnchor="middle">优势区</text>
      <text className="quadrant-label" x={padL + innerW * 0.25} y={padT + innerH - 14} textAnchor="middle">劣势区</text>
      {/* points */}
      {points.map((p) => (
        <g key={p.platform}>
          <circle cx={x(p.self_mention_rate)} cy={y(p.competitor_avg_mention_rate)} r={10} fill="#1a55e8">
            <title>{`${p.platform}: 自身 ${(p.self_mention_rate * 100).toFixed(0)}% · 竞品均值 ${(p.competitor_avg_mention_rate * 100).toFixed(0)}%`}</title>
          </circle>
          <text className="point-label" x={x(p.self_mention_rate) + 14} y={y(p.competitor_avg_mention_rate) + 5}>
            {p.platform}
          </text>
        </g>
      ))}
    </svg>
  );
}