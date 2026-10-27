"use client";

import { useEffect, useState } from "react";
import { Banner, Button, Card } from "@/components/ui";
import {
  api,
  fmt,
  OPPORTUNITY_MAX_DAYS,
  type CannibalResponse,
  type CannibalRow,
  type DateRange,
  type QuerySegment,
  type StrikingResponse,
  type StrikingRow,
  type StrikingSort,
} from "@/lib/api";

const PAGE_SIZE = 100;
const LOADING_TEXT =
  "Fetching keyword + page data live from Google… the first time for a date range takes ~5–30 seconds; after that it's instant for a day (or until the next sync).";

function stripHost(url: string) {
  return url.replace(/^https?:\/\/[^/]+/, "") || "/";
}

function PageLink({ url }: { url: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer" title={url} className="truncate text-accent hover:underline">
      {stripHost(url)}
    </a>
  );
}

export function BrandDot({ brand }: { brand: boolean }) {
  return (
    <span
      className={`h-2 w-2 shrink-0 rounded-full ${brand ? "bg-chart-brand" : "bg-chart-non-brand"}`}
      title={brand ? "Brand" : "Non-brand"}
      aria-label={brand ? "Brand" : "Non-brand"}
    />
  );
}

/** Notice shown when the chosen range is longer than page-level views support. */
export function RangeTooLong({ onPick }: { onPick: (days: number) => void }) {
  return (
    <Card className="flex flex-col gap-3 p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
      <p className="text-muted">
        This view pulls keyword + page data live from Google, so it covers up to 3 months — it&apos;s about where you
        rank now.
      </p>
      <div className="flex gap-2">
        <Button variant="secondary" onClick={() => onPick(28)}>
          Use 28 days
        </Button>
        <Button variant="secondary" onClick={() => onPick(OPPORTUNITY_MAX_DAYS)}>
          Use 3 months
        </Button>
      </div>
    </Card>
  );
}

/** Generic paged loader: first page on filter change, "Show more" appends. */
export function usePaged<T, R extends { total: number; items: T[] }>(
  fetchPage: (offset: number) => Promise<R>,
  deps: unknown[],
) {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<R | null>(null);
  const [rows, setRows] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify([...deps, offset]);
  const [doneKey, setDoneKey] = useState<string | null>(null);

  // Reset paging when filters change (adjusting state during render, not in an effect).
  const depsKey = JSON.stringify(deps);
  const [seenDeps, setSeenDeps] = useState(depsKey);
  if (seenDeps !== depsKey) {
    setSeenDeps(depsKey);
    setOffset(0);
  }

  useEffect(() => {
    let cancelled = false;
    fetchPage(offset)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setRows((prev) => (offset === 0 ? res.items : [...prev, ...res.items]));
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setDoneKey(key));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, rows, error, loading: doneKey !== key, more: () => setOffset(rows.length) };
}

export function Footer({ shown, total, loading, onMore }: { shown: number; total: number; loading: boolean; onMore: () => void }) {
  if (shown >= total) return null;
  return (
    <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
      <span>
        Showing {fmt.int(shown)} of {fmt.int(total)}
      </span>
      <Button variant="secondary" disabled={loading} onClick={onMore}>
        {loading ? "Loading…" : "Show more"}
      </Button>
    </div>
  );
}

function Fetched({ data }: { data: { start_date: string; end_date: string; fetched_at: string } }) {
  return (
    <span className="text-xs text-muted">
      {fmt.date(data.start_date)} – {fmt.date(data.end_date)} · fetched from Google {fmt.dateTime(data.fetched_at)}
    </span>
  );
}

// ---------- striking distance ----------

const STRIKING_SORTS: { key: StrikingSort; label: string }[] = [
  { key: "potential", label: "Potential" },
  { key: "impressions", label: "Impressions" },
  { key: "clicks", label: "Clicks" },
  { key: "position", label: "Position" },
];

export function StrikingPanel({ propertyId, range, segment }: { propertyId: number; range: DateRange; segment: QuerySegment }) {
  const [sort, setSort] = useState<StrikingSort>("potential");
  const { data, rows, error, loading, more } = usePaged<StrikingRow, StrikingResponse>(
    (offset) => api.strikingDistance(propertyId, range, segment, sort, PAGE_SIZE, offset),
    [propertyId, range, segment, sort],
  );

  return (
    <Card className="overflow-hidden">
      <div className="space-y-2 px-4 pt-4 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium">
            {data ? `${fmt.int(data.total)} striking-distance keywords` : "Striking distance"}
            {loading && data && <span className="ml-2 font-normal text-muted">Updating…</span>}
          </h2>
          <label className="flex items-center gap-2 text-xs text-muted">
            Sort by
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as StrikingSort)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm text-foreground"
            >
              {STRIKING_SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {data && (
          <p className="text-xs text-muted">
            Keywords whose main page ranks {data.min_position}–{data.max_position} with {fmt.int(data.min_impressions)}+
            impressions — the quickest wins. <b className="font-medium text-foreground">Potential</b> = extra clicks if
            that page reached position {data.target_position}, using this site&apos;s own CTR there. <Fetched data={data} />
          </p>
        )}
      </div>
      {error && <div className="px-4 pb-3"><Banner tone="error">{error}</Banner></div>}
      {loading && !data ? (
        <p className="px-4 pb-6 text-sm text-muted">{LOADING_TEXT}</p>
      ) : rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">No striking-distance keywords for these filters.</p>
      ) : (
        <div className="max-h-[640px] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 z-10 bg-surface text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-normal">Keyword → ranking page</th>
                <th className="w-24 px-2 py-2 text-right font-normal">Impr.</th>
                <th className="hidden w-16 px-2 py-2 text-right font-normal sm:table-cell">Clicks</th>
                <th className="hidden w-20 px-2 py-2 text-right font-normal md:table-cell">CTR</th>
                <th className="w-16 px-2 py-2 text-right font-normal">Pos.</th>
                <th className="w-24 px-4 py-2 text-right font-normal">Potential</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((r) => (
                <tr key={r.query} className="border-b border-border align-top last:border-0">
                  <td className="max-w-0 px-4 py-2">
                    <div className="flex items-center gap-2">
                      <BrandDot brand={r.brand} />
                      <span className="truncate" title={r.query}>
                        {r.query}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 pl-4 text-xs">
                      <PageLink url={r.page} />
                      {r.other_pages > 0 && (
                        <span className="shrink-0 text-muted">+{r.other_pages} other page{r.other_pages > 1 ? "s" : ""}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right">{fmt.int(r.impressions)}</td>
                  <td className="hidden px-2 py-2 text-right sm:table-cell">{fmt.int(r.clicks)}</td>
                  <td className="hidden px-2 py-2 text-right md:table-cell">{fmt.pct(r.ctr)}</td>
                  <td className="px-2 py-2 text-right">{fmt.pos(r.position)}</td>
                  <td className="px-4 py-2 text-right font-medium text-positive">
                    {r.potential == null ? "—" : `+${fmt.int(r.potential)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Footer shown={rows.length} total={data.total} loading={loading} onMore={more} />}
    </Card>
  );
}

// ---------- cannibalisation ----------

export function CannibalPanel({ propertyId, range, segment }: { propertyId: number; range: DateRange; segment: QuerySegment }) {
  const { data, rows, error, loading, more } = usePaged<CannibalRow, CannibalResponse>(
    (offset) => api.cannibalisation(propertyId, range, segment, PAGE_SIZE, offset),
    [propertyId, range, segment],
  );

  return (
    <Card className="overflow-hidden">
      <div className="space-y-2 px-4 pt-4 pb-3">
        <h2 className="text-sm font-medium">
          {data ? `${fmt.int(data.total)} keywords with competing pages` : "Cannibalisation"}
          {loading && data && <span className="ml-2 font-normal text-muted">Updating…</span>}
        </h2>
        {data && (
          <p className="text-xs text-muted">
            Keywords with {fmt.int(data.min_impressions)}+ impressions where 2 or more of your pages each get at least{" "}
            {data.min_share * 100}% of them. Google splits attention between them — usually merge, redirect or
            differentiate the pages, and point internal links at the one you want to rank. Searches where 3+ pages all rank in
            the top 3 are Google sitelinks (usually brand searches) — listed last and marked as fine.{" "}
            <Fetched data={data} />
          </p>
        )}
      </div>
      {error && <div className="px-4 pb-3"><Banner tone="error">{error}</Banner></div>}
      {loading && !data ? (
        <p className="px-4 pb-6 text-sm text-muted">{LOADING_TEXT}</p>
      ) : rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">No competing pages for these filters. 🎉</p>
      ) : (
        <ul className="max-h-[640px] divide-y divide-border overflow-auto border-t border-border">
          {rows.map((r) => (
            <li key={r.query} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <BrandDot brand={r.brand} />
                  <span className="truncate font-medium" title={r.query}>
                    {r.query}
                  </span>
                  {r.sitelinks_likely && (
                    <span
                      className="shrink-0 rounded-full bg-positive/15 px-2 py-0.5 text-xs text-positive"
                      title="Several of your pages all rank in the top 3 for this search — Google is showing sitelinks. Usually fine."
                    >
                      Likely sitelinks — usually fine
                    </span>
                  )}
                </span>
                <span className="text-xs text-muted tabular-nums">
                  {fmt.int(r.impressions)} impr. · {fmt.int(r.clicks)} clicks · {r.competing_pages} pages
                </span>
              </div>
              <table className="mt-2 w-full table-fixed text-xs">
                <tbody className="tabular-nums">
                  {r.pages.map((p) => (
                    <tr key={p.page}>
                      <td className="max-w-0 py-1 pl-4">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-border" aria-hidden>
                            <div className="h-full bg-accent" style={{ width: `${p.share * 100}%` }} />
                          </div>
                          <PageLink url={p.page} />
                        </div>
                      </td>
                      <td className="w-14 py-1 text-right">{Math.round(p.share * 100)}%</td>
                      <td className="w-20 py-1 text-right">{fmt.int(p.impressions)}</td>
                      <td className="hidden w-14 py-1 text-right sm:table-cell">{fmt.int(p.clicks)}</td>
                      <td className="w-14 py-1 text-right">pos {fmt.pos(p.position)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </li>
          ))}
        </ul>
      )}
      {data && <Footer shown={rows.length} total={data.total} loading={loading} onMore={more} />}
    </Card>
  );
}
