"use client";

import { useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui";
import type { Compare, DateRange } from "@/lib/api";

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
  custom: "vs comparison period",
  none: "",
};

// ---------- one date range for every client and tab; each new visit starts at 28 days vs previous period ----------

const STORAGE_KEY = "seo-tool:date-range";
const DEFAULT_RANGE: DateRange = { days: 28, start: null, end: null, compare: "previous", compareStart: null, compareEnd: null };

let current: DateRange | null = null;
const listeners = new Set<() => void>();

function read(): DateRange {
  if (current) return current;
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "null");
    current = saved ? { ...DEFAULT_RANGE, ...saved } : DEFAULT_RANGE;
  } catch {
    current = DEFAULT_RANGE; // private window / blocked storage: just don't remember
  }
  return current as DateRange;
}

export function setDateRange(next: DateRange) {
  current = next;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // not kept across reloads, but still shared by every screen in this tab
  }
  listeners.forEach((l) => l());
}

/** Re-run every report with the same range, e.g. after a sync brought in new data. */
export const refreshReports = () => setDateRange({ ...read() });

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The shared date range: changing it anywhere updates every screen. */
export function useDateRange(): [DateRange, (next: DateRange) => void] {
  const range = useSyncExternalStore(subscribe, read, () => DEFAULT_RANGE);
  return [range, setDateRange];
}

/** Length of the chosen range in days (custom dates included). */
export function rangeDays(r: DateRange): number {
  if (r.start && r.end) return Math.round((Date.parse(r.end) - Date.parse(r.start)) / 86_400_000) + 1;
  return r.days;
}

type PeriodDates = { start_date: string; end_date: string; compare_start: string | null; compare_end: string | null };

/** "Sep 15 – Oct 12 · compared with Aug 18 – Sep 14", "· no comparison", or a note when the comparison isn't stored. */
export function periodText(d: PeriodDates & ({ previous_totals: unknown } | { compare_available: boolean })) {
  const fmtDate = (iso: string) => {
    const date = new Date(iso + "T00:00:00");
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      ...(date.getFullYear() !== new Date().getFullYear() && { year: "numeric" }),
    });
  };
  const range = `${fmtDate(d.start_date)} – ${fmtDate(d.end_date)}`;
  if (!d.compare_start || !d.compare_end) return `${range} · no comparison`;
  const compared = `${fmtDate(d.compare_start)} – ${fmtDate(d.compare_end)}`;
  const stored = "compare_available" in d ? d.compare_available : d.previous_totals != null;
  return stored ? `${range} · compared with ${compared}` : `${range} · no comparison: ${compared} isn't stored yet`;
}

/** A preset range, keeping the comparison choice. */
export const withPreset = (r: DateRange, days: number): DateRange => ({ ...r, days, start: null, end: null });

// ---------- the bar ----------

const inputClass = "rounded-md border border-border bg-surface px-2 py-1 text-sm";

/** Date range + comparison for every report on a client page; one choice applies to all tabs and clients. */
export function DateBar() {
  const [range, setRange] = useDateRange();
  const custom = !!(range.start && range.end);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ start: range.start ?? "", end: range.end ?? "" });
  const [cDraft, setCDraft] = useState({ start: range.compareStart ?? "", end: range.compareEnd ?? "" });
  const today = new Date().toISOString().slice(0, 10);
  const draftValid = draft.start && draft.end && draft.start <= draft.end;
  const cDraftValid = cDraft.start && cDraft.end && cDraft.start <= cDraft.end;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-border bg-surface p-0.5" role="group" aria-label="Date range">
          {RANGES.map((r) => {
            const active = !custom && range.days === r.days;
            return (
              <button
                key={r.days}
                onClick={() => {
                  setEditing(false);
                  setRange(withPreset(range, r.days));
                }}
                aria-pressed={active}
                className={`rounded px-3 py-1 text-sm ${active ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
              >
                {r.label}
              </button>
            );
          })}
          <button
            onClick={() => setEditing(!editing)}
            aria-pressed={custom}
            aria-expanded={editing}
            className={`rounded px-3 py-1 text-sm ${custom ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
          >
            Custom
          </button>
        </div>
        <select
          aria-label="Compare with"
          value={range.compare}
          onChange={(e) => {
            const compare = e.target.value as Compare;
            // Custom comparison waits for its dates (below) before it applies.
            if (compare !== "custom") setRange({ ...range, compare, compareStart: null, compareEnd: null });
            else setRange({ ...range, compare, compareStart: cDraft.start || null, compareEnd: cDraft.end || null });
          }}
          className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
        >
          <option value="previous">Compare: previous period</option>
          <option value="year">Compare: same period last year</option>
          <option value="custom">Compare: custom dates</option>
          <option value="none">No comparison</option>
        </select>
      </div>

      {editing && (
        <form
          className="flex flex-wrap items-center gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            if (!draftValid) return;
            setRange({ ...range, start: draft.start, end: draft.end });
            setEditing(false);
          }}
        >
          <span className="text-muted">From</span>
          <input type="date" aria-label="Start date" value={draft.start} max={today} onChange={(e) => setDraft({ ...draft, start: e.target.value })} className={inputClass} />
          <span className="text-muted">to</span>
          <input type="date" aria-label="End date" value={draft.end} max={today} onChange={(e) => setDraft({ ...draft, end: e.target.value })} className={inputClass} />
          <Button type="submit" variant="secondary" disabled={!draftValid}>
            Apply
          </Button>
          {draft.start && draft.end && draft.start > draft.end && <span className="text-xs text-negative">The start must be before the end.</span>}
        </form>
      )}

      {range.compare === "custom" && (
        <form
          className="flex flex-wrap items-center gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            if (cDraftValid) setRange({ ...range, compareStart: cDraft.start, compareEnd: cDraft.end });
          }}
        >
          <span className="text-muted">Compare with</span>
          <input type="date" aria-label="Comparison start date" value={cDraft.start} max={today} onChange={(e) => setCDraft({ ...cDraft, start: e.target.value })} className={inputClass} />
          <span className="text-muted">to</span>
          <input type="date" aria-label="Comparison end date" value={cDraft.end} max={today} onChange={(e) => setCDraft({ ...cDraft, end: e.target.value })} className={inputClass} />
          <Button type="submit" variant="secondary" disabled={!cDraftValid}>
            Apply
          </Button>
          {!(range.compareStart && range.compareEnd) && <span className="text-xs text-muted">Pick the dates to compare with.</span>}
        </form>
      )}
    </div>
  );
}
