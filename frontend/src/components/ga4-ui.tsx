"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { COMPARE_LABEL } from "@/components/range-controls";
import { Card } from "@/components/ui";
import { fmt, type Compare } from "@/lib/api";

/** "+12.5%" against the comparison, or null when there's nothing to compare with. */
export function change(now: number, before: number | null | undefined): { text: string; up: boolean } | null {
  if (before == null || before === 0) return null;
  const c = (now - before) / before;
  return { text: `${c > 0 ? "+" : ""}${(c * 100).toFixed(1)}%`, up: c >= 0 };
}

/** KPI card for GA4 numbers: label, value, change vs the comparison period. */
export function MetricCard({
  label,
  value,
  now,
  before,
  compare,
  hint,
}: {
  label: string;
  value: string;
  now: number;
  before: number | null | undefined;
  compare: Compare;
  hint?: string;
}) {
  const delta = change(now, before);
  return (
    <Card className="p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {delta && (
        <p className={`mt-1 text-xs tabular-nums ${delta.up ? "text-positive" : "text-negative"}`}>
          {delta.text} <span className="text-muted">{COMPARE_LABEL[compare]}</span>
        </p>
      )}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  );
}

type Day = { date: string; sessions: number };

/** Sessions per day, with the comparison period drawn dashed on the same days. */
export function SessionsChart({
  startDate,
  compareStart,
  daily,
  previousDaily,
  compareLabel,
}: {
  startDate: string;
  compareStart: string | null;
  daily: Day[];
  previousDaily: Day[];
  compareLabel: string;
}) {
  const offset = compareStart ? Date.parse(startDate) - Date.parse(compareStart) : 0;
  const previous = new Map(
    previousDaily.map((d) => [new Date(Date.parse(d.date) + offset).toISOString().slice(0, 10), d.sessions]),
  );
  const data = daily.map((d) => ({ ...d, prev_sessions: previous.get(d.date) }));
  const longRange = daily.length > 120; // label months instead of days
  return (
    <div className="h-64 w-full">
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
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(v: number) => fmt.int(v)}
          />
          <Tooltip
            labelFormatter={(d) => fmt.date(String(d))}
            formatter={(v) => fmt.int(Number(v))}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="sessions"
            name="Sessions"
            stroke="var(--chart-clicks)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          {previous.size > 0 && (
            <Line
              type="monotone"
              dataKey="prev_sessions"
              name={`Sessions (${compareLabel})`}
              stroke="var(--chart-clicks)"
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
