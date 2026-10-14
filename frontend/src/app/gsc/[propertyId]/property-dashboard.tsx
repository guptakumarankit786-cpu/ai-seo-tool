"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { PropertyTabs } from "@/components/property-tabs";
import { Badge, Banner, Button, Card } from "@/components/ui";
import { useSync } from "@/components/use-sync";
import {
  api,
  fmt,
  propertyLabel,
  type DimensionRow,
  type Property,
  type Summary,
  type Totals,
} from "@/lib/api";
import { TrafficChart } from "./traffic-chart";

const RANGES = [7, 28, 90] as const;

export function PropertyDashboard({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [days, setDays] = useState<number>(28);
  const [property, setProperty] = useState<Property | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [queries, setQueries] = useState<DimensionRow[]>([]);
  const [pages, setPages] = useState<DimensionRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [version, setVersion] = useState(0);
  const load = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.property(id), api.summary(id, days), api.queries(id, days), api.pages(id, days)])
      .then(([p, s, q, pg]) => {
        if (cancelled) return;
        setProperty(p);
        setSummary(s);
        setQueries(q);
        setPages(pg);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id, days, version]);

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
            {fmt.date(summary.start_date)} – {fmt.date(summary.end_date)} · Google Search Console
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-border bg-surface p-0.5" role="group">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDays(r)}
                className={`rounded px-3 py-1 text-sm ${days === r ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
              >
                {r}d
              </button>
            ))}
          </div>
          <SyncControl property={property} onDone={load} />
        </div>
      </header>

      <PropertyTabs propertyId={id} active="performance" />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Clicks" metric="clicks" totals={summary.totals} prev={summary.previous_totals} />
        <Kpi
          label="Impressions"
          metric="impressions"
          totals={summary.totals}
          prev={summary.previous_totals}
        />
        <Kpi label="Avg. CTR" metric="ctr" totals={summary.totals} prev={summary.previous_totals} />
        <Kpi
          label="Avg. position"
          metric="position"
          totals={summary.totals}
          prev={summary.previous_totals}
          lowerIsBetter
        />
      </div>

      <Card className="p-4">
        <h2 className="mb-3 text-sm font-medium">Performance</h2>
        {summary.daily.length ? (
          <TrafficChart data={summary.daily} />
        ) : (
          <p className="py-10 text-center text-sm text-muted">
            No data in this range yet. Run a sync to pull it in.
          </p>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <DimensionTable title="Top queries" keyLabel="Query" rows={queries} />
        <DimensionTable title="Top pages" keyLabel="Page" rows={pages} isUrl />
      </div>
    </div>
  );
}

function SyncControl({ property, onDone }: { property: Property; onDone: () => void }) {
  const { running, error, start } = useSync(property, onDone);
  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-negative">{error}</span>}
      <Button variant="secondary" disabled={running} onClick={() => start(90)}>
        {running ? "Syncing…" : "Re-sync"}
      </Button>
    </div>
  );
}

function Kpi({
  label,
  metric,
  totals,
  prev,
  lowerIsBetter = false,
}: {
  label: string;
  metric: keyof Totals;
  totals: Totals;
  prev: Totals | null;
  lowerIsBetter?: boolean;
}) {
  const value = totals[metric];
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
          {delta.text} <span className="text-muted">vs previous period</span>
        </p>
      )}
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
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-normal">{keyLabel}</th>
                <th className="px-2 py-2 text-right font-normal">Clicks</th>
                <th className="px-2 py-2 text-right font-normal">Impr.</th>
                <th className="hidden px-2 py-2 text-right font-normal sm:table-cell">CTR</th>
                <th className="px-4 py-2 text-right font-normal">Pos.</th>
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
