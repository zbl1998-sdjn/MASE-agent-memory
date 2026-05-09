import type { ChartPoint } from "../types";
import type { CSSProperties } from "react";

type BarChartProps = {
  data: ChartPoint[];
  labelKey?: "name" | "date";
  emptyLabel?: string;
};

export function BarChart({ data, labelKey = "name", emptyLabel = "暂无可视化数据" }: BarChartProps) {
  const max = Math.max(1, ...data.map((item) => item.value));
  if (!data.length) {
    return <div className="empty chart-empty">{emptyLabel}</div>;
  }
  return (
    <div className="bar-chart">
      {data.map((item) => {
        const label = String(item[labelKey] ?? item.name ?? item.date ?? "unknown");
        return (
          <div className="bar-row" key={label}>
            <span>{label}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${Math.max(6, (item.value / max) * 100)}%` }} />
            </div>
            <strong>{item.value}</strong>
          </div>
        );
      })}
    </div>
  );
}

export function Sparkline({ data }: { data: ChartPoint[] }) {
  const max = Math.max(1, ...data.map((item) => item.value));
  return (
    <div className="sparkline">
      {data.slice(-18).map((item, index) => {
        const label = String(item.date ?? item.name ?? index);
        return (
          <div className="spark-column" key={`${label}-${index}`} title={`${label}: ${item.value}`}>
            <span style={{ height: `${Math.max(10, (item.value / max) * 100)}%` }} />
          </div>
        );
      })}
    </div>
  );
}

export function DonutStat({ value, total, label }: { value: number; total: number; label: string }) {
  const percent = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="donut-stat" style={{ "--percent": `${percent}%` } as CSSProperties}>
      <div>
        <strong>{percent}%</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}
