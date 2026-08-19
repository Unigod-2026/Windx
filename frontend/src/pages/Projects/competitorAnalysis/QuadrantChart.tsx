import type { QuadrantPoint } from "../../../api/projects";

interface Props {
  points: QuadrantPoint[];
  selfAvg: number;
  competitorAvg: number;
}

export default function QuadrantChart({ points, selfAvg, competitorAvg }: Props) {
  const w = 760, h = 380, padL = 56, padR = 24, padT = 24, padB = 36;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const yMax = 1, xMax = 1;
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
      <text className="axis-label" x={w - padR} y={padT + innerH + 16} textAnchor="end">自身提及率</text>
      <text className="axis-label" x={padL - 8} y={padT - 8} textAnchor="end">竞品提及率</text>
      {/* quadrant quadrant labels */}
      <text className="quadrant-label" x={padL + innerW * 0.75} y={padT + 14} textAnchor="middle">优势区</text>
      <text className="quadrant-label" x={padL + innerW * 0.25} y={padT + innerH - 8} textAnchor="middle">劣势区</text>
      {/* points */}
      {points.map((p) => (
        <g key={p.platform}>
          <circle cx={x(p.self_mention_rate)} cy={y(p.competitor_avg_mention_rate)} r={6} fill="#1a55e8">
            <title>{`${p.platform}: 自身 ${(p.self_mention_rate * 100).toFixed(0)}% · 竞品均值 ${(p.competitor_avg_mention_rate * 100).toFixed(0)}%`}</title>
          </circle>
          <text className="point-label" x={x(p.self_mention_rate) + 9} y={y(p.competitor_avg_mention_rate) + 4}>
            {p.platform}
          </text>
        </g>
      ))}
    </svg>
  );
}
