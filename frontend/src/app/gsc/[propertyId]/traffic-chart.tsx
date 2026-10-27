"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmt, type Summary } from "@/lib/api";

/** Clicks + impressions per day, with the comparison period drawn dashed on the same days. */
export function TrafficChart({
  summary,
  compareLabel,
}: {
  summary: Pick<Summary, "start_date" | "compare_start" | "daily" | "previous_daily">;
  compareLabel: string;
}) {
  // Shift each comparison day onto the matching day of the current window.
  const offset = Date.parse(summary.start_date) - Date.parse(summary.compare_start);
  const previous = new Map(
    summary.previous_daily.map((d) => [
      new Date(Date.parse(d.date) + offset).toISOString().slice(0, 10),
      d,
    ]),
  );
  const data = summary.daily.map((d) => ({
    ...d,
    prev_clicks: previous.get(d.date)?.clicks,
    prev_impressions: previous.get(d.date)?.impressions,
  }));
  const hasPrevious = previous.size > 0;
  const longRange = summary.daily.length > 120; // label months instead of days

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={longRange ? fmt.month : fmt.date}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
            minTickGap={24}
          />
          <YAxis
            yAxisId="clicks"
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(v: number) => fmt.int(v)}
          />
          <YAxis
            yAxisId="impressions"
            orientation="right"
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(v: number) => fmt.int(v)}
          />
          <Tooltip
            labelFormatter={(d) => fmt.date(String(d))}
            formatter={(v) => fmt.int(Number(v))}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            yAxisId="clicks"
            type="monotone"
            dataKey="clicks"
            name="Clicks"
            stroke="var(--chart-clicks)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            yAxisId="impressions"
            type="monotone"
            dataKey="impressions"
            name="Impressions"
            stroke="var(--chart-impressions)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          {hasPrevious && (
            <Line
              yAxisId="clicks"
              type="monotone"
              dataKey="prev_clicks"
              name={`Clicks (${compareLabel})`}
              stroke="var(--chart-clicks)"
              strokeOpacity={0.5}
              strokeDasharray="4 4"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          )}
          {hasPrevious && (
            <Line
              yAxisId="impressions"
              type="monotone"
              dataKey="prev_impressions"
              name={`Impressions (${compareLabel})`}
              stroke="var(--chart-impressions)"
              strokeOpacity={0.5}
              strokeDasharray="4 4"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
