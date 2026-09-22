"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { money, num, pct } from "@/lib/format";

export type ValueFormat = "money" | "number" | "percent";

const FORMATTERS: Record<ValueFormat, (v: number) => string> = {
  money: (v) => money(v, { compact: true }),
  number: (v) => num(v),
  percent: (v) => pct(v, 0),
};

export interface TrendPoint {
  label: string;
  value: number;
}

function ChartTooltip({
  active,
  payload,
  label,
  format,
  seriesLabel,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
  format: (v: number) => string;
  seriesLabel: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-panel px-2.5 py-1.5 text-xs shadow-sm">
      <div className="text-muted">{label}</div>
      <div className="tabular font-medium text-text">
        {seriesLabel}: {format(payload[0].value)}
      </div>
    </div>
  );
}

/** Single-series weekly bar chart. One axis, thin rounded bars, hover tooltip. */
export function BarTrend({
  data,
  valueFormat = "number",
  seriesLabel,
  height = 180,
  color = "var(--chart-1)",
}: {
  data: TrendPoint[];
  valueFormat?: ValueFormat;
  seriesLabel: string;
  height?: number;
  color?: string;
}) {
  const format = FORMATTERS[valueFormat];
  return (
    <div style={{ height }} role="img" aria-label={`${seriesLabel} by week`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }} barCategoryGap={3}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="0" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={48}
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            tickFormatter={(v: number) => format(v)}
          />
          <Tooltip
            cursor={{ fill: "var(--panel-2)" }}
            content={<ChartTooltip format={format} seriesLabel={seriesLabel} />}
          />
          <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
