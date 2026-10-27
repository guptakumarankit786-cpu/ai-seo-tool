"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
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
import { TermsEditor } from "@/components/terms-editor";
import { Card } from "@/components/ui";
import {
  api,
  fmt,
  type BrandTerms,
  type DateRange,
  type DimensionRow,
  type QuerySegment,
  type SegmentTotals,
  type Segments,
} from "@/lib/api";

/** Brand vs non-brand split: terms editor, two summary cards, hidden-data note and daily chart. */
export function BrandSection({
  propertyId,
  range,
  version,
  onTermsChange,
}: {
  propertyId: number;
  range: DateRange;
  version: number;
  onTermsChange: () => void;
}) {
  const [data, setData] = useState<Segments | null>(null);
  const [terms, setTerms] = useState<BrandTerms | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.segments(propertyId, range), api.brandTerms(propertyId)])
      .then(([s, t]) => {
        if (cancelled) return;
        setData(s);
        setTerms(t);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [propertyId, range, version]);

  if (error) return <Card className="p-4 text-sm text-negative">{error}</Card>;
  if (!data || !terms) return null;

  const total = data.brand.totals.clicks + data.non_brand.totals.clicks + data.hidden_clicks;
  const hiddenShare = total ? data.hidden_clicks / total : 0;

  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-medium">Brand vs non-brand</h2>
          <p className="mt-0.5 text-xs text-muted">Queries containing a brand term count as brand.</p>
        </div>
        <TermsEditor
          label="Brand terms"
          hint="Brand terms, separated by commas — include product / sub-brand names and common misspellings."
          placeholder="brand name, product name, misspelling"
          terms={terms.terms}
          isDefault={terms.is_default}
          suggested={terms.suggested}
          onSave={async (value) => {
            await api.setBrandTerms(propertyId, value);
            onTermsChange();
          }}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <SegmentCard label="Brand" color="bg-chart-brand" segment={data.brand} />
        <SegmentCard label="Non-brand" color="bg-chart-non-brand" segment={data.non_brand} />
      </div>

      {data.hidden_clicks > 0 && (
        <p className="text-xs text-muted">
          Google hides {fmt.int(data.hidden_clicks)} clicks ({(hiddenShare * 100).toFixed(0)}% of all clicks) from
          keyword data for privacy. They&apos;re in the totals above but can&apos;t be split into brand or non-brand.
        </p>
      )}

      {data.daily.length > 0 && (
        <div className="h-64 w-full">
          <ResponsiveContainer>
            <LineChart data={data.daily} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={data.daily.length > 120 ? fmt.month : fmt.date}
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
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="brand_clicks"
                name="Brand clicks"
                stroke="var(--chart-brand)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="non_brand_clicks"
                name="Non-brand clicks"
                stroke="var(--chart-non-brand)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

function change(cur: number, prev: number | undefined, lowerIsBetter = false) {
  if (!prev) return null;
  const pct = (cur - prev) / prev;
  const good = pct === 0 || (lowerIsBetter ? pct < 0 : pct > 0);
  return (
    <span className={good ? "text-positive" : "text-negative"}>
      {pct > 0 ? "+" : ""}
      {(pct * 100).toFixed(1)}%
    </span>
  );
}

function SegmentCard({ label, color, segment }: { label: string; color: string; segment: SegmentTotals }) {
  const { totals: t, previous: p } = segment;
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium">
          <span className={`h-2.5 w-2.5 rounded-full ${color}`} aria-hidden />
          {label}
        </span>
        <span className="text-xs text-muted tabular-nums">{(segment.click_share * 100).toFixed(1)}% of clicks</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border">
        <div className={`h-full ${color}`} style={{ width: `${segment.click_share * 100}%` }} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <Metric label="Clicks" value={fmt.int(t.clicks)} delta={change(t.clicks, p?.clicks)} />
        <Metric label="Impressions" value={fmt.int(t.impressions)} delta={change(t.impressions, p?.impressions)} />
        <Metric label="CTR" value={fmt.pct(t.ctr)} delta={change(t.ctr, p?.ctr)} />
        <Metric label="Avg. position" value={fmt.pos(t.position)} delta={change(t.position, p?.position, true)} />
      </dl>
    </div>
  );
}

function Metric({ label, value, delta }: { label: string; value: string; delta: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-semibold tabular-nums">{value}</dd>
      {delta && <dd className="text-xs tabular-nums">{delta}</dd>}
    </div>
  );
}

const SEGMENTS: { key: QuerySegment; label: string }[] = [
  { key: "all", label: "All" },
  { key: "brand", label: "Brand" },
  { key: "non_brand", label: "Non-brand" },
];

/** Top queries with an All / Brand / Non-brand filter. */
export function QueriesTable({ propertyId, range, version }: { propertyId: number; range: DateRange; version: number }) {
  const [segment, setSegment] = useState<QuerySegment>("all");
  const [rows, setRows] = useState<DimensionRow[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .queries(propertyId, range, 50, segment)
      .then((r) => {
        if (cancelled) return;
        setRows(r);
        setLoaded(true);
      })
      .catch(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [propertyId, range, segment, version]);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-sm font-medium">Top queries</h2>
          <Link href={`/gsc/${propertyId}/keywords`} className="text-xs text-accent hover:underline">
            View all keywords →
          </Link>
        </div>
        <div className="flex rounded-md border border-border p-0.5 text-xs" role="tablist">
          {SEGMENTS.map((s) => (
            <button
              key={s.key}
              role="tab"
              aria-selected={segment === s.key}
              onClick={() => setSegment(s.key)}
              className={`rounded px-2.5 py-1 ${segment === s.key ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      {loaded && rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">No queries in this range.</p>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-normal">Query</th>
                <th className="w-16 px-2 py-2 text-right font-normal">Clicks</th>
                <th className="w-20 px-2 py-2 text-right font-normal">Impr.</th>
                <th className="hidden w-16 px-2 py-2 text-right font-normal sm:table-cell">CTR</th>
                <th className="w-14 px-4 py-2 text-right font-normal">Pos.</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((r) => (
                <tr key={r.key} className="border-b border-border last:border-0">
                  <td className="max-w-0 px-4 py-2" title={r.key}>
                    <span className="flex items-center gap-2">
                      {segment === "all" && (
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${r.brand ? "bg-chart-brand" : "bg-chart-non-brand"}`}
                          title={r.brand ? "Brand" : "Non-brand"}
                          aria-label={r.brand ? "Brand" : "Non-brand"}
                        />
                      )}
                      <span className="truncate">{r.key}</span>
                    </span>
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
