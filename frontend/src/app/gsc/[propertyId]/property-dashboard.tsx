"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { PropertyTabs } from "@/components/property-tabs";
import { SyncControls, SyncStatus } from "@/components/sync-controls";
import { Badge, Banner, Card } from "@/components/ui";
import { useSync } from "@/components/use-sync";
import {
  api,
  fmt,
  propertyLabel,
  type Compare,
  type DimensionRow,
  type Property,
  type Summary,
  type Totals,
} from "@/lib/api";
import { BrandSection, QueriesTable } from "./brand-section";
import { TrafficChart } from "./traffic-chart";

const RANGES = [
  { days: 7, label: "7d" },
  { days: 28, label: "28d" },
  { days: 90, label: "3m" },
  { days: 180, label: "6m" },
  { days: 365, label: "12m" },
  { days: 486, label: "16m" },
] as const;

const COMPARE_LABEL: Record<Compare, string> = { previous: "vs previous period", year: "vs last year" };

export function PropertyDashboard({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [days, setDays] = useState<number>(28);
  const [compare, setCompare] = useState<Compare>("previous");
  const [property, setProperty] = useState<Property | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [pages, setPages] = useState<DimensionRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [version, setVersion] = useState(0);
  const load = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.property(id), api.summary(id, days, compare), api.pages(id, days)])
      .then(([p, s, pg]) => {
        if (cancelled) return;
        setProperty(p);
        setSummary(s);
        setPages(pg);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id, days, compare, version]);

  if (error) return <Banner tone="error">{error}</Banner>;
  if (!property || !summary) return <p className="text-sm text-muted">Loading…</p>;

  const { name, kind } = propertyLabel(property.site_url);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <Link href="/integrations" className="text-xs text-muted hover:text-foreground">
            ← Integrations
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{name}</h1>
            <Badge>{kind}</Badge>
          </div>
          <p className="mt-1 text-sm text-muted">
            {fmt.date(summary.start_date)} – {fmt.date(summary.end_date)} · compared with{" "}
            {fmt.date(summary.compare_start)} – {fmt.date(summary.compare_end)}
          </p>
        </div>
        <SyncBar property={property} onDone={load} />
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-border bg-surface p-0.5" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r.days}
              onClick={() => setDays(r.days)}
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
          onChange={(e) => setCompare(e.target.value as Compare)}
          className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
        >
          <option value="previous">Compare: previous period</option>
          <option value="year">Compare: same period last year</option>
        </select>
      </div>

      <PropertyTabs propertyId={id} active="performance" />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Clicks" metric="clicks" summary={summary} />
        <Kpi label="Impressions" metric="impressions" summary={summary} />
        <Kpi label="Avg. CTR" metric="ctr" summary={summary} />
        <Kpi label="Avg. position" metric="position" summary={summary} lowerIsBetter />
      </div>

      <Card className="p-4">
        <h2 className="mb-3 text-sm font-medium">Performance</h2>
        {summary.daily.length ? (
          <TrafficChart summary={summary} compareLabel={COMPARE_LABEL[compare]} />
        ) : (
          <p className="py-10 text-center text-sm text-muted">
            No data in this range yet. Run a sync to pull it in.
          </p>
        )}
      </Card>

      <BrandSection propertyId={id} days={days} compare={compare} version={version} onTermsChange={load} />

      <div className="grid gap-6 lg:grid-cols-2">
        <QueriesTable propertyId={id} days={days} version={version} />
        <DimensionTable title="Top pages" keyLabel="Page" rows={pages} isUrl />
      </div>
    </div>
  );
}

function SyncBar({ property, onDone }: { property: Property; onDone: () => void }) {
  const { run, running, error, start } = useSync(property, onDone);
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <SyncControls property={property} running={running} start={start} />
      <p className="text-xs text-muted">
        <SyncStatus property={property} running={running} run={run} />
      </p>
      {error && <p className="text-xs text-negative">{error}</p>}
    </div>
  );
}

function Kpi({
  label,
  metric,
  summary,
  lowerIsBetter = false,
}: {
  label: string;
  metric: keyof Totals;
  summary: Summary;
  lowerIsBetter?: boolean;
}) {
  const value = summary.totals[metric];
  const prev = summary.previous_totals;
  const format = { clicks: fmt.int, impressions: fmt.int, ctr: fmt.pct, position: fmt.pos }[metric];

  let delta: { text: string; good: boolean } | null = null;
  if (prev && prev[metric]) {
    const change = (value - prev[metric]) / prev[metric];
    const improved = lowerIsBetter ? change < 0 : change > 0;
    delta = {
      text: `${change > 0 ? "+" : ""}${(change * 100).toFixed(1)}%`,
      good: change === 0 || improved,
    };
  }

  return (
    <Card className="p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{format(value)}</p>
      {delta && (
        <p className={`mt-1 text-xs tabular-nums ${delta.good ? "text-positive" : "text-negative"}`}>
          {delta.text} <span className="text-muted">{COMPARE_LABEL[summary.compare]}</span>
        </p>
      )}
      {!prev && <p className="mt-1 text-xs text-muted">Not enough history to compare</p>}
    </Card>
  );
}

function DimensionTable({
  title,
  keyLabel,
  rows,
  isUrl = false,
}: {
  title: string;
  keyLabel: string;
  rows: DimensionRow[];
  isUrl?: boolean;
}) {
  return (
    <Card className="overflow-hidden">
      <h2 className="px-4 pt-4 pb-3 text-sm font-medium">{title}</h2>
      {rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">No data in this range.</p>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-normal">{keyLabel}</th>
                <th className="w-16 px-2 py-2 text-right font-normal">Clicks</th>
                <th className="w-20 px-2 py-2 text-right font-normal">Impr.</th>
                <th className="hidden w-16 px-2 py-2 text-right font-normal sm:table-cell">CTR</th>
                <th className="w-14 px-4 py-2 text-right font-normal">Pos.</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-border last:border-0">
                  <td className="max-w-0 truncate px-4 py-2" title={r.key}>
                    {isUrl ? (
                      <a href={r.key} target="_blank" rel="noreferrer" className="hover:underline">
                        {r.key.replace(/^https?:\/\/[^/]+/, "") || "/"}
                      </a>
                    ) : (
                      r.key
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">{fmt.int(r.clicks)}</td>
                  <td className="px-2 py-2 text-right">{fmt.int(r.impressions)}</td>
                  <td className="hidden px-2 py-2 text-right sm:table-cell">{fmt.pct(r.ctr)}</td>
                  <td className="px-4 py-2 text-right">{fmt.pos(r.position)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
