"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { PropertyTabs } from "@/components/property-tabs";
import { ClientToolbar } from "@/components/client-toolbar";
import { COMPARE_LABEL, periodText, useDateRange } from "@/components/range-controls";
import { Badge, Banner, Card } from "@/components/ui";
import {
  api,
  fmt,
  propertyLabel,
  type DateRange,
  type DimensionRow,
  type TopPagesFilter,
  type Property,
  type Summary,
  type Totals,
} from "@/lib/api";
import { BrandSection, ChangeCell, ChangeHeader, QueriesTable, rowsHaveChange } from "./brand-section";
import { TrafficChart } from "./traffic-chart";


export function PropertyDashboard({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [range] = useDateRange();
  const [property, setProperty] = useState<Property | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [version, setVersion] = useState(0);
  const load = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.property(id), api.summary(id, range)])
      .then(([p, s]) => {
        if (cancelled) return;
        setProperty(p);
        setSummary(s);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id, range, version]);

  if (error) return <Banner tone="error">{error}</Banner>;
  if (!property || !summary) return <p className="text-sm text-muted">Loading…</p>;

  const { name, kind } = propertyLabel(property.site_url);

  return (
    <div className="space-y-6">
      <header className="min-w-0">
        <div>
          <Link href="/integrations" className="text-xs text-muted hover:text-foreground">
            ← Integrations
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{name}</h1>
            <Badge>{kind}</Badge>
          </div>
          <p className="mt-1 text-sm text-muted">{periodText(summary)}</p>
        </div>
      </header>

      <ClientToolbar propertyId={id} />

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
          <TrafficChart summary={summary} compareLabel={COMPARE_LABEL[summary.compare]} />
        ) : (
          <p className="py-10 text-center text-sm text-muted">
            No data in this range yet. Run a sync to pull it in.
          </p>
        )}
      </Card>

      <BrandSection propertyId={id} range={range} version={version} onTermsChange={load} />

      <div className="grid gap-6 lg:grid-cols-2">
        <QueriesTable propertyId={id} range={range} version={version} />
        <PagesTable propertyId={id} range={range} version={version} />
      </div>
    </div>
  );
}

export function Kpi({
  label,
  metric,
  summary,
  lowerIsBetter = false,
}: {
  label: string;
  metric: keyof Totals;
  summary: Pick<Summary, "totals" | "previous_totals" | "compare">;
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
      {!prev && summary.compare !== "none" && <p className="mt-1 text-xs text-muted">Not enough history to compare</p>}
    </Card>
  );
}

const PAGE_FILTERS: { key: TopPagesFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "low_ctr", label: "Low CTR" },
];

function PagesTable({ propertyId, range, version }: { propertyId: number; range: DateRange; version: number }) {
  const [filter, setFilter] = useState<TopPagesFilter>("all");
  const [rows, setRows] = useState<DimensionRow[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .pages(propertyId, range, 50, filter)
      .then((r) => {
        if (cancelled) return;
        setRows(r);
        setLoaded(true);
      })
      .catch(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [propertyId, range, filter, version]);
  const hasChange = rowsHaveChange(rows);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-sm font-medium">Top pages</h2>
          <Link href={`/gsc/${propertyId}/pages`} className="text-xs text-accent hover:underline">
            View all pages →
          </Link>
        </div>
        <div className="flex rounded-md border border-border p-0.5 text-xs" role="tablist">
          {PAGE_FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded px-2.5 py-1 ${filter === f.key ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {filter === "low_ctr" && (
        <p className="px-4 pb-3 text-xs text-muted">
          Top-10 pages with enough impressions whose CTR is under half of this site&apos;s typical page CTR at that
          position — biggest click shortfall first. Usually a title or description to rewrite.
        </p>
      )}
      {loaded && rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">
          {filter === "low_ctr" ? "No low-CTR pages in this range." : "No data in this range."}
        </p>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-normal">Page</th>
                <th className="w-16 px-2 py-2 text-right font-normal">Clicks</th>
                {hasChange && <ChangeHeader />}
                <th className="w-20 px-2 py-2 text-right font-normal">Impr.</th>
                <th className="hidden w-20 px-2 py-2 text-right font-normal sm:table-cell">CTR</th>
                <th className="w-14 px-4 py-2 text-right font-normal">Pos.</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-border last:border-0">
                  <td className="max-w-0 px-4 py-2" title={r.key}>
                    <span className="flex items-center gap-2">
                      <Link
                        href={`/gsc/${propertyId}/pages/detail?${new URLSearchParams({ url: r.key })}`}
                        className="truncate hover:text-accent hover:underline"
                      >
                        {r.key.replace(/^https?:\/\/[^/]+/, "") || "/"}
                      </Link>
                      <a
                        href={r.key}
                        target="_blank"
                        rel="noreferrer"
                        className="shrink-0 text-xs text-muted hover:text-foreground"
                        aria-label="Open the live page in a new tab"
                      >
                        ↗
                      </a>
                      {filter === "all" && r.low_ctr && (
                        <span className="shrink-0 rounded-full bg-negative/15 px-1.5 text-[11px] text-negative">
                          Low CTR
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-right">{fmt.int(r.clicks)}</td>
                  {hasChange && <ChangeCell row={r} />}
                  <td className="px-2 py-2 text-right">{fmt.int(r.impressions)}</td>
                  <td className="hidden px-2 py-2 text-right sm:table-cell">
                    {fmt.pct(r.ctr)}
                    {r.low_ctr && r.expected_ctr != null && (
                      <div className="text-[11px] text-muted" title="This site's typical page CTR at this position">
                        typical {fmt.pct(r.expected_ctr)}
                      </div>
                    )}
                  </td>
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
