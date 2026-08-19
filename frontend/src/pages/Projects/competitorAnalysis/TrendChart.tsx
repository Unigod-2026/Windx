import { useMemo, useState } from "react";
import * as echarts from "echarts";
import EChart from "../../../components/EChart";
import type { CompetitorTrendSeries } from "../../../api/projects";

interface Props {
  labels: string[];
  series: CompetitorTrendSeries[];
}

export default function TrendChart({ labels, series }: Props) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(series.map((s) => s.brand_canonical)),
  );

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // 与 OverviewTab 「趋势分析」tab 的视觉一致:选中保持品牌原色,未选中
  // 用灰色虚线绘制,让"被过滤掉"和"被保留"的视觉对比明显。
  const option = useMemo<echarts.EChartsOption>(() => {
    const eseries: echarts.EChartsOption["series"] = series.map((s) => {
      const isOn = selected.has(s.brand_canonical);
      return {
        name: s.name,
        type: "line" as const,
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        data: s.data,
        itemStyle: isOn
          ? { color: s.color, borderColor: "#fff", borderWidth: 2 }
          : { color: "#cfd4dc", borderColor: "#fff", borderWidth: 2 },
        lineStyle: {
          color: isOn ? s.color : "#cfd4dc",
          width: 2,
          type: isOn ? "solid" : "dashed",
        },
        areaStyle: isOn ? { color: s.color, opacity: 0.08 } : { color: "transparent" },
      };
    });
    return {
      grid: { left: 50, right: 28, top: 24, bottom: 36 },
      tooltip: { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: "#d9d9d9" } } },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: labels,
        axisLine: { lineStyle: { color: "#f0f0f0" } },
        axisTick: { show: false },
        axisLabel: { color: "#8c8c8c", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "#f0f0f0" } },
        axisLabel: { color: "#8c8c8c", fontSize: 11 },
      },
      series: eseries,
    };
  }, [labels, series, selected]);

  return (
    <>
      <div className="chart-legend">
        {series.map((s) => {
          const isOn = selected.has(s.brand_canonical);
          return (
            <button
              key={s.brand_canonical}
              type="button"
              className={`legend-chip${isOn ? "" : " off"}`}
              onClick={() => toggle(s.brand_canonical)}
            >
              <i style={{ background: s.color }} />
              {s.name}
              {s.is_self && <span className="legend-chip-self">自身</span>}
            </button>
          );
        })}
      </div>
      <EChart option={option} className="chart-trend-tall" />
    </>
  );
}