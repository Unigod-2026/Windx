interface BarSeries {
  name: string;
  color: string;
  data: number[];
}

interface Props {
  labels: string[];
  series: BarSeries[];
  /** Optional y-axis unit suffix displayed in tooltips/labels. */
  unit?: string;
  /** Hard upper bound for y-axis. If omitted, computed from data. */
  yMax?: number;
}

export default function BarChart({ labels, series, unit, yMax }: Props) {
  const w = 520, h = 240, padL = 44, padR = 16, padT = 12, padB = 36;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const computedMax = Math.max(...allValues, 1);
  const yTop = yMax ?? (Math.ceil(computedMax / 5) * 5 || 5);
  const groupWidth = innerW / Math.max(labels.length, 1);
  const barWidth = Math.min(28, (groupWidth * 0.8) / Math.max(series.length, 1));

  const xCenter = (i: number) => padL + i * groupWidth + groupWidth / 2;
  const y = (v: number) => padT + innerH - (v / yTop) * innerH;

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) =>
    Math.round((yTop * i) / ticks),
  );

  return (
    <svg className="bar-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yTop) * innerH;
        return (
          <g key={i}>
            <line className="grid-line" x1={padL} y1={yy} x2={w - padR} y2={yy} />
            <text className="axis-label" x={padL - 6} y={yy + 3} textAnchor="end">{t}{unit ?? ""}</text>
          </g>
        );
      })}
      {labels.map((lab, i) => (
        <text key={i} className="axis-label" x={xCenter(i)} y={h - 12} textAnchor="middle">
          {lab.length > 8 ? lab.slice(0, 7) + "…" : lab}
        </text>
      ))}
      {labels.map((_, i) =>
        series.map((s, sIdx) => {
          const v = s.data[i] ?? 0;
          const xOff = xCenter(i) - (series.length * barWidth) / 2 + sIdx * barWidth;
          return (
            <rect
              key={`${i}-${sIdx}`}
              x={xOff}
              y={y(v)}
              width={barWidth - 2}
              height={padT + innerH - y(v)}
              fill={s.color}
              rx={2}
            >
              <title>{`${s.name} · ${labels[i]}: ${v}${unit ?? ""}`}</title>
            </rect>
          );
        }),
      )}
    </svg>
  );
}
