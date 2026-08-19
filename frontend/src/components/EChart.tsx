import { useEffect, useRef } from "react";
import * as echarts from "echarts";

interface Props {
  option: echarts.EChartsOption;
  height?: number;
  className?: string;
}

export default function EChart({ option, height, className }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current);
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return (
    <div
      ref={ref}
      className={className}
      style={{ width: "100%", ...(height !== undefined ? { height } : {}) }}
    />
  );
}