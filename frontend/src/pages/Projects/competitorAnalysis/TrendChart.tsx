import type { CompetitorTrendSeries } from "../../../api/projects";

export default function TrendChart({ labels, series }: {
  labels: string[];
  series: CompetitorTrendSeries[];
}) {
  const w = 760, h = 240, padL = 40, padR = 12, padT = 12, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const max = Math.max(...allValues, 1);
  const yMax = Math.ceil(max / 5) * 5 || 5;
  const x = (i: number) => padL + (labels.length > 1 ? (i * innerW) / (labels.length - 1) : innerW / 2);
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => Math.round((yMax * i) / ticks));
  return (
    <svg className="trend-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yMax) * innerH;
        return (
          <g key={i}>
            <line className="grid-line" x1={padL} y1={yy} x2={w - padR} y2={yy} />
            <text className="axis-label" x={padL - 6} y={yy + 3} textAnchor="end">{t}</text>
          </g>
        );
      })}
      {labels.map((lab, i) => {
        if (labels.length > 7 && i % Math.ceil(labels.length / 6) !== 0) return null;
        return <text className="axis-label" key={i} x={x(i)} y={h - 8} textAnchor="middle">{lab.slice(5)}</text>;
      })}
      {series.map((s) => {
        const points = s.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        return (
          <g key={s.brand_canonical}>
            <polyline className="line" stroke={s.color} points={points} />
            {s.data.map((v, i) => v > 0 ? (
              <circle key={i} className="dot" cx={x(i)} cy={y(v)} r={2.5} fill={s.color} />
            ) : null)}
          </g>
        );
      })}
    </svg>
  );
}