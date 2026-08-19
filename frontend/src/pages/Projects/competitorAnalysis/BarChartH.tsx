interface BarSeries {
  name: string;
  color: string;
  data: number[];
}

interface Props {
  labels: string[];
  series: BarSeries[];
  /** Optional suffix appended after numeric value labels (default "%"). */
  unit?: string;
}

/**
 * 横向分组条形图 — 对齐 docs/更新版UI/js/charts.js `groupedBarH`。
 *
 * 设计要点(对照 design):
 *   - 每行斑马纹背景(`#f5f6f8` / `#fafbfc` 交替)
 *   - 行标签(模型名)贴左
 *   - 每个 series 一根细条,在行内堆叠
 *   - 每根条末端贴数值标签 `xx%`
 *   - 顶部 legend:方块 + 文字,横向排列
 *   - 高度自适应 = 顶部 30 + labels.length * 44 + 底部 14
 */
export default function BarChartH({ labels, series, unit = "%" }: Props) {
  const w = 760;
  const h = 30 + labels.length * 44 + 14;
  const padL = 96, padR = 56, padT = 30, padB = 14;
  const innerW = w - padL - padR;
  const rowH = (h - padT - padB) / Math.max(labels.length, 1);
  const barH = Math.min(rowH * 0.38, 16);
  const maxVal = Math.max(...series.flatMap((s) => s.data), 1) * 1.15;

  return (
    <svg className="bar-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {series.map((s, i) => {
        const lx = padL + i * 120;
        return (
          <g key={`legend-${s.name}`}>
            <rect x={lx} y={9} width={12} height={10} rx={2} fill={s.color} />
            <text x={lx + 16} y={17} fontSize={11} fill="#4f4f4f">{s.name}</text>
          </g>
        );
      })}
      {labels.map((label, i) => {
        const rowY = padT + i * rowH;
        const stripe = i % 2 ? "#fafbfc" : "#f5f6f8";
        return (
          <g key={`row-${label}`}>
            <rect x={padL} y={rowY + 3} width={innerW} height={rowH - 6} rx={6} fill={stripe} />
            <text
              x={padL - 10}
              y={rowY + rowH / 2 + 4}
              textAnchor="end"
              fontSize={12}
              fill="#4f4f4f"
              fontWeight={500}
            >
              {label}
            </text>
            {series.map((s, sIdx) => {
              const v = s.data[i] ?? 0;
              const barW = (v / maxVal) * innerW;
              const by = rowY + rowH / 2 - barH - (sIdx === 0 ? 2 : -2);
              return (
                <g key={`${label}-${s.name}`}>
                  <rect
                    x={padL}
                    y={by}
                    width={Math.max(barW, 2)}
                    height={barH}
                    rx={3}
                    fill={s.color}
                  >
                    <title>{`${s.name} · ${label}: ${v.toFixed(1)}${unit}`}</title>
                  </rect>
                  <text
                    x={padL + Math.max(barW, 2) + 6}
                    y={by + barH - 3}
                    fontSize={11}
                    fontWeight={600}
                    fill={s.color}
                  >
                    {`${v.toFixed(1)}${unit}`}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}