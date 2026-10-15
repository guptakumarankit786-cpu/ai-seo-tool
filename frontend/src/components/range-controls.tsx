"use client";

import type { Compare } from "@/lib/api";

export const RANGES = [
  { days: 7, label: "7d" },
  { days: 28, label: "28d" },
  { days: 90, label: "3m" },
  { days: 180, label: "6m" },
  { days: 365, label: "12m" },
  { days: 486, label: "16m" },
] as const;

export const COMPARE_LABEL: Record<Compare, string> = {
  previous: "vs previous period",
  year: "vs last year",
};

/** Date-range buttons + comparison select, shared by Performance and Keywords. */
export function RangeControls({
  days,
  onDays,
  compare,
  onCompare,
}: {
  days: number;
  onDays: (days: number) => void;
  compare: Compare;
  onCompare: (compare: Compare) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-md border border-border bg-surface p-0.5" role="group" aria-label="Date range">
        {RANGES.map((r) => (
          <button
            key={r.days}
            onClick={() => onDays(r.days)}
            aria-pressed={days === r.days}
            className={`rounded px-3 py-1 text-sm ${days === r.days ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
          >
            {r.label}
          </button>
        ))}
      </div>
      <select
        aria-label="Compare with"
        value={compare}
        onChange={(e) => onCompare(e.target.value as Compare)}
        className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
      >
        <option value="previous">Compare: previous period</option>
        <option value="year">Compare: same period last year</option>
      </select>
    </div>
  );
}
