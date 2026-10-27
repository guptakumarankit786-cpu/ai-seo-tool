"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { PropertyTabs } from "@/components/property-tabs";
import { COMPARE_LABEL, RangeControls } from "@/components/range-controls";
import { Badge, Banner, Button, Card } from "@/components/ui";
import {
  api,
  fmt,
  propertyLabel,
  type Compare,
  type PageFilter,
  type PageGroup,
  type PageQuery,
  type PageReport,
  type PageRow,
  type PageSort,
  type PageType,
  type Property,
} from "@/lib/api";

const PAGE_SIZE = 100;

const TYPE_LABEL: Record<PageType, string> = {
  home: "Home",
  collections: "Collections",
  products: "Products",
  blogs: "Blogs",
  pages: "Pages",
  other: "Other",
  shopping: "Shopping listings",
};
const TYPE_HINT: Partial<Record<PageType, string>> = {
  shopping: "Free product listing URLs (…?variant=…). Never counted as new, lost, low CTR or striking distance.",
  other: "Pages outside /products, /collections, /blogs and /pages (cart, search, policies…).",
};

const FILTER_LABEL: Record<PageFilter, string> = {
  high_performance: "High performance",
  low_ctr: "Low CTR",
  striking: "Striking distance",
  rising: "Rising",
  declining: "Declining",
  new: "New",
  lost: "Lost",
  zero_clicks: "Zero clicks",
};
const FILTER_ORDER = Object.keys(FILTER_LABEL) as PageFilter[];
const NEEDS_COMPARE: PageFilter[] = ["lost", "rising", "declining"];

function describe(f: PageFilter, d: PageReport["definitions"], compare: Compare): string {
  const vs = COMPARE_LABEL[compare];
  return {
    high_performance: `The pages that together bring ${d.high_performance_share * 100}% of clicks.`,
    low_ctr: `Top-${d.low_ctr_max_position} position with ${d.min_impressions}+ impressions, but CTR under half of this site's typical page CTR at that position — usually a title or description to rewrite.`,
    striking: `Average position ${d.striking_min_position}–${d.striking_max_position} with ${d.min_impressions}+ impressions — one push could reach the top 3 (home page left out: it ranks for too many searches).`,
    rising: `Clicks up by at least ${d.mover_min_clicks} and ${d.mover_min_share * 100}% ${vs}.`,
    declining: `Clicks down by at least ${d.mover_min_clicks} and ${d.mover_min_share * 100}% ${vs}.`,
    new: `${d.min_impressions}+ impressions now, none in the ${d.new_lookback_days} days before.`,
    lost: `Had clicks ${vs.replace("vs ", "in the ")} but none now.`,
    zero_clicks: `${d.min_impressions}+ impressions and no clicks.`,
  }[f];
}

export function PagesView({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [property, setProperty] = useState<Property | null>(null);
  const [q, setQ] = useState<PageQuery>({
    days: 28,
    compare: "previous",
    types: [],
    filters: [],
    search: "",
    sort: "clicks",
    order: "desc",
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [searchInput, setSearchInput] = useState("");
  const [data, setData] = useState<PageReport | null>(null);
  const [rows, setRows] = useState<PageRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Loading = the filters on screen differ from the ones the last finished request used.
  const requestKey = JSON.stringify(q);
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const loading = doneKey !== requestKey;

  // Any filter change starts from the first page.
  const update = (patch: Partial<PageQuery>) => setQ((prev) => ({ ...prev, offset: 0, ...patch }));

  useEffect(() => {
    api.property(id).then(setProperty).catch((e: Error) => setError(e.message));
  }, [id]);

  // Debounce the search box.
  useEffect(() => {
    const t = setTimeout(() => setQ((prev) => (prev.search === searchInput ? prev : { ...prev, search: searchInput, offset: 0 })), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    let cancelled = false;
    api
      .pageReport(id, q)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setRows((prev) => (q.offset === 0 ? res.items : [...prev, ...res.items]));
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setDoneKey(JSON.stringify(q)));
    return () => {
      cancelled = true;
    };
  }, [id, q]);

  if (!property) return error ? <Banner tone="error">{error}</Banner> : <p className="text-sm text-muted">Loading…</p>;

  const { name, kind } = propertyLabel(property.site_url);
  const toggleFilter = (f: PageFilter) =>
    update({ filters: q.filters.includes(f) ? q.filters.filter((x) => x !== f) : [...q.filters, f] });
  const sortBy = (sort: PageSort) =>
    update({ sort, order: q.sort === sort && q.order === "desc" ? "asc" : sort === "position" || sort === "page" ? "asc" : "desc" });
  const selectedType = q.types[0];

  return (
    <div className="space-y-6">
      <header className="min-w-0">
        <Link href="/integrations" className="text-xs text-muted hover:text-foreground">
          ← Integrations
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{name}</h1>
          <Badge>{kind}</Badge>
        </div>
        {data && (
          <p className="mt-1 text-sm text-muted">
            {fmt.date(data.start_date)} – {fmt.date(data.end_date)} · every page Google showed in search for this period
          </p>
        )}
      </header>

      <PropertyTabs propertyId={id} active="pages" />

      <RangeControls
        days={q.days}
        onDays={(days) => update({ days })}
        compare={q.compare}
        onCompare={(compare) => update({ compare })}
      />

      {data && data.groups.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" role="group" aria-label="Page types">
          {data.groups.map((g) => (
            <TypeCard
              key={g.type}
              group={g}
              compare={q.compare}
              selected={selectedType === g.type}
              onClick={() => update({ types: selectedType === g.type ? [] : [g.type] })}
            />
          ))}
        </div>
      )}

      {data && (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Page filters">
            {FILTER_ORDER.map((f) => {
              const unavailable = (NEEDS_COMPARE.includes(f) && !data.compare_available) || (f === "new" && !data.new_available);
              const active = q.filters.includes(f);
              return (
                <button
                  key={f}
                  onClick={() => toggleFilter(f)}
                  disabled={unavailable && !active}
                  aria-pressed={active}
                  title={unavailable ? "Not enough history for this date range" : describe(f, data.definitions, q.compare)}
                  className={`rounded-full border px-3 py-1 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    active ? "border-accent bg-accent-soft text-accent" : "border-border hover:bg-accent-soft"
                  }`}
                >
                  {FILTER_LABEL[f]} <span className="tabular-nums text-muted">{unavailable ? "—" : fmt.int(data.counts[f] ?? 0)}</span>
                </button>
              );
            })}
            {q.filters.length > 0 && (
              <button onClick={() => update({ filters: [] })} className="px-2 text-sm text-muted hover:text-foreground">
                Clear
              </button>
            )}
          </div>
          {(q.filters.length > 0 || selectedType) && (
            <ul className="space-y-0.5 text-xs text-muted">
              {selectedType && (
                <li>
                  <b className="font-medium text-foreground">{TYPE_LABEL[selectedType]}</b> pages only
                  {TYPE_HINT[selectedType] && ` — ${TYPE_HINT[selectedType]}`}.{" "}
                  <button onClick={() => update({ types: [] })} className="text-accent hover:underline">
                    Show all types
                  </button>
                </li>
              )}
              {q.filters.map((f) => (
                <li key={f}>
                  <b className="font-medium text-foreground">{FILTER_LABEL[f]}:</b> {describe(f, data.definitions, q.compare)}
                </li>
              ))}
              {q.filters.length > 1 && <li>Pages must match all selected filters.</li>}
            </ul>
          )}
        </Card>
      )}

      {error && <Banner tone="error">{error}</Banner>}

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3">
          <h2 className="text-sm font-medium">
            {data ? `${fmt.int(data.total)} pages` : "Pages"}
            {loading && <span className="ml-2 font-normal text-muted">Updating…</span>}
          </h2>
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search page URLs"
            aria-label="Search page URLs"
            className="w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm sm:w-64"
          />
        </div>

        {loading && !data ? (
          <p className="px-4 pb-6 text-sm text-muted">Analysing pages…</p>
        ) : rows.length === 0 ? (
          <p className="px-4 pb-6 text-sm text-muted">
            {data?.groups.length ? "No pages match these filters." : "No page data in this range yet. Run a sync from Integrations."}
          </p>
        ) : (
          <div className="max-h-[640px] overflow-auto">
            <table className="w-full table-fixed text-sm">
              <thead className="sticky top-0 z-10 bg-surface text-xs text-muted">
                <tr className="border-b border-border">
                  <SortHeader label="Page" sort="page" q={q} onSort={sortBy} className="px-4 text-left" />
                  <SortHeader label="Clicks" sort="clicks" q={q} onSort={sortBy} className="w-20 px-2 text-right" />
                  <SortHeader label="Change" sort="click_change" q={q} onSort={sortBy} className="hidden w-20 px-2 text-right md:table-cell" />
                  <SortHeader label="Impr." sort="impressions" q={q} onSort={sortBy} className="w-24 px-2 text-right" />
                  <SortHeader label="CTR" sort="ctr" q={q} onSort={sortBy} className="hidden w-20 px-2 text-right sm:table-cell" />
                  <SortHeader label="Pos." sort="position" q={q} onSort={sortBy} className="w-16 px-4 text-right" />
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {rows.map((r) => (
                  <PageTableRow key={r.page} row={r} compareAvailable={!!data?.compare_available} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && rows.length < data.total && (
          <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
            <span>
              Showing {fmt.int(rows.length)} of {fmt.int(data.total)}
            </span>
            <Button variant="secondary" disabled={loading} onClick={() => setQ((prev) => ({ ...prev, offset: rows.length }))}>
              {loading ? "Loading…" : "Show more"}
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

function TypeCard({
  group,
  compare,
  selected,
  onClick,
}: {
  group: PageGroup;
  compare: Compare;
  selected: boolean;
  onClick: () => void;
}) {
  const change = group.prev_clicks == null ? null : group.clicks - group.prev_clicks;
  const pct = change != null && group.prev_clicks ? change / group.prev_clicks : null;
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      title={TYPE_HINT[group.type]}
      className={`rounded-xl border p-4 text-left transition ${
        selected ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-accent/60"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className={`text-xs ${selected ? "font-medium text-accent" : "text-muted"}`}>{TYPE_LABEL[group.type]}</span>
        <span className="text-xs text-muted tabular-nums">{fmt.int(group.pages)} pages</span>
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{fmt.int(group.clicks)}</div>
      <div className="text-xs tabular-nums">
        {change == null ? (
          <span className="text-muted">clicks · no comparison</span>
        ) : (
          <span className={change > 0 ? "text-positive" : change < 0 ? "text-negative" : "text-muted"}>
            {change > 0 ? "+" : ""}
            {fmt.int(change)}
            {pct != null && ` (${pct > 0 ? "+" : ""}${(pct * 100).toFixed(0)}%)`}{" "}
            <span className="text-muted">{COMPARE_LABEL[compare]}</span>
          </span>
        )}
      </div>
      <div className="mt-2 text-xs text-muted tabular-nums">
        CTR {fmt.pct(group.ctr)} · pos {group.position == null ? "—" : fmt.pos(group.position)}
      </div>
    </button>
  );
}

function SortHeader({
  label,
  sort,
  q,
  onSort,
  className,
}: {
  label: string;
  sort: PageSort;
  q: PageQuery;
  onSort: (sort: PageSort) => void;
  className: string;
}) {
  const active = q.sort === sort;
  return (
    <th className={`py-2 font-normal ${className}`} aria-sort={active ? (q.order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => onSort(sort)} className={`hover:text-foreground ${active ? "font-medium text-foreground" : ""}`}>
        {label}
        {active && (q.order === "asc" ? " ↑" : " ↓")}
      </button>
    </th>
  );
}

function PageTableRow({ row, compareAvailable }: { row: PageRow; compareAvailable: boolean }) {
  const change = row.click_change;
  const path = row.page.replace(/^https?:\/\/[^/]+/, "") || "/";
  return (
    <tr className="border-b border-border align-top last:border-0">
      <td className="max-w-0 px-4 py-2">
        <a href={row.page} target="_blank" rel="noreferrer" className="block truncate hover:underline" title={row.page}>
          {path}
        </a>
        <div className="mt-1 flex flex-wrap gap-1">
          <span className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted">{TYPE_LABEL[row.type]}</span>
          {FILTER_ORDER.filter((f) => row.flags.includes(f)).map((f) => (
            <span key={f} className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent">
              {FILTER_LABEL[f]}
            </span>
          ))}
        </div>
      </td>
      <td className="px-2 py-2 text-right">{fmt.int(row.clicks)}</td>
      <td
        className={`hidden px-2 py-2 text-right md:table-cell ${!compareAvailable || change === 0 ? "text-muted" : change > 0 ? "text-positive" : "text-negative"}`}
      >
        {compareAvailable ? `${change > 0 ? "+" : ""}${fmt.int(change)}` : "—"}
      </td>
      <td className="px-2 py-2 text-right">{fmt.int(row.impressions)}</td>
      <td className="hidden px-2 py-2 text-right sm:table-cell">
        {fmt.pct(row.ctr)}
        {row.flags.includes("low_ctr") && row.expected_ctr != null && (
          <div className="text-[11px] text-muted" title="This site's typical page CTR at this position">
            typical {fmt.pct(row.expected_ctr)}
          </div>
        )}
      </td>
      <td className="px-4 py-2 text-right">{row.position == null ? "—" : fmt.pos(row.position)}</td>
    </tr>
  );
}
