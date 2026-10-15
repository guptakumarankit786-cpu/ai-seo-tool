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
  type KeywordQuery,
  type KeywordRow,
  type KeywordSort,
  type KeywordType,
  type KeywordsResponse,
  type Property,
  type QuerySegment,
  OPPORTUNITY_MAX_DAYS,
} from "@/lib/api";
import { CannibalPanel, RangeTooLong, StrikingPanel } from "./opportunity-views";

const PAGE_SIZE = 100;

type View = "all" | "striking" | "cannibal";
const VIEWS: { key: View; label: string }[] = [
  { key: "all", label: "All keywords" },
  { key: "striking", label: "Striking distance" },
  { key: "cannibal", label: "Cannibalisation" },
];

const TYPE_LABEL: Record<KeywordType, string> = {
  high_performance: "High performance",
  question: "Questions",
  buying: "Buying intent",
  long_tail: "Long-tail",
  new: "New",
  lost: "Lost",
  rising: "Rising",
  declining: "Declining",
  low_ctr: "Low CTR",
  zero_clicks: "Zero clicks",
};
const TYPE_ORDER = Object.keys(TYPE_LABEL) as KeywordType[];
const NEEDS_COMPARE: KeywordType[] = ["lost", "rising", "declining"];

function describe(type: KeywordType, d: KeywordsResponse["definitions"], compare: Compare): string {
  const vs = COMPARE_LABEL[compare];
  return {
    high_performance: `The keywords that together bring ${d.high_performance_share * 100}% of clicks.`,
    question: "Question searches: how, what, why, when, where, which, who, can/should/is/do…, “?”, “ways to”, “tips for”.",
    buying: "Buying-intent searches: buy, price, cheap, discount, offer, best, top, review, vs, compare, online, near me, delivery…",
    long_tail: `Searches of ${d.long_tail_words} or more words.`,
    new: `Got impressions now but none in the ${d.new_lookback_days} days before.`,
    lost: `Had clicks ${vs.replace("vs ", "in the ")} but none now.`,
    rising: `Clicks up by at least ${d.mover_min_clicks} and ${d.mover_min_share * 100}% ${vs}.`,
    declining: `Clicks down by at least ${d.mover_min_clicks} and ${d.mover_min_share * 100}% ${vs}.`,
    low_ctr: `Top-${d.low_ctr_max_position} position with ${d.min_impressions}+ impressions, but CTR under half of this site's typical CTR at that position (brand and non-brand judged separately).`,
    zero_clicks: `${d.min_impressions}+ impressions and no clicks.`,
  }[type];
}

export function KeywordsView({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [property, setProperty] = useState<Property | null>(null);
  const [q, setQ] = useState<KeywordQuery>({
    days: 28,
    compare: "previous",
    segment: "all",
    types: [],
    search: "",
    sort: "clicks",
    order: "desc",
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [view, setView] = useState<View>("all");
  const [searchInput, setSearchInput] = useState("");
  const [data, setData] = useState<KeywordsResponse | null>(null);
  const [rows, setRows] = useState<KeywordRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Loading = the filters on screen differ from the ones the last finished request used.
  const requestKey = JSON.stringify(q);
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const loading = doneKey !== requestKey;

  // Any filter change starts from the first page.
  const update = (patch: Partial<KeywordQuery>) => setQ((prev) => ({ ...prev, offset: 0, ...patch }));

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
      .keywords(id, q)
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
  const toggleType = (t: KeywordType) =>
    update({ types: q.types.includes(t) ? q.types.filter((x) => x !== t) : [...q.types, t] });
  const sortBy = (sort: KeywordSort) =>
    update({ sort, order: q.sort === sort && q.order === "desc" ? "asc" : sort === "position" || sort === "query" ? "asc" : "desc" });

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
            {fmt.date(data.start_date)} – {fmt.date(data.end_date)} · every keyword Google reported for this period
          </p>
        )}
      </header>

      <PropertyTabs propertyId={id} active="keywords" />

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Keyword view">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            role="tab"
            aria-selected={view === v.key}
            onClick={() => setView(v.key)}
            className={`rounded-md border px-3 py-1.5 text-sm ${
              view === v.key ? "border-accent bg-accent-soft font-medium text-accent" : "border-border hover:bg-accent-soft"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <RangeControls
          days={q.days}
          onDays={(days) => update({ days })}
          compare={q.compare}
          onCompare={(compare) => update({ compare })}
        />
        <div className="flex rounded-md border border-border bg-surface p-0.5 text-sm" role="tablist" aria-label="Brand filter">
          {(["all", "brand", "non_brand"] as QuerySegment[]).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={q.segment === s}
              onClick={() => update({ segment: s })}
              className={`rounded px-3 py-1 ${q.segment === s ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
            >
              {{ all: "All", brand: "Brand", non_brand: "Non-brand" }[s]}
            </button>
          ))}
        </div>
      </div>

      {view !== "all" &&
        (q.days > OPPORTUNITY_MAX_DAYS ? (
          <RangeTooLong onPick={(days) => update({ days })} />
        ) : view === "striking" ? (
          <StrikingPanel propertyId={id} days={q.days} segment={q.segment} />
        ) : (
          <CannibalPanel propertyId={id} days={q.days} segment={q.segment} />
        ))}

      {view === "all" && data && (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Keyword types">
            {TYPE_ORDER.map((t) => {
              const unavailable =
                (NEEDS_COMPARE.includes(t) && !data.compare_available) || (t === "new" && !data.new_available);
              const active = q.types.includes(t);
              return (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  disabled={unavailable && !active}
                  aria-pressed={active}
                  title={unavailable ? "Not enough history for this date range" : describe(t, data.definitions, q.compare)}
                  className={`rounded-full border px-3 py-1 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    active ? "border-accent bg-accent-soft text-accent" : "border-border hover:bg-accent-soft"
                  }`}
                >
                  {TYPE_LABEL[t]} <span className="tabular-nums text-muted">{unavailable ? "—" : fmt.int(data.counts[t])}</span>
                </button>
              );
            })}
            {q.types.length > 0 && (
              <button onClick={() => update({ types: [] })} className="px-2 text-sm text-muted hover:text-foreground">
                Clear
              </button>
            )}
          </div>
          {q.types.length > 0 && (
            <ul className="space-y-0.5 text-xs text-muted">
              {q.types.map((t) => (
                <li key={t}>
                  <b className="font-medium text-foreground">{TYPE_LABEL[t]}:</b> {describe(t, data.definitions, q.compare)}
                </li>
              ))}
              {q.types.length > 1 && <li>Keywords must match all selected types.</li>}
            </ul>
          )}
        </Card>
      )}

      {view === "all" && error && <Banner tone="error">{error}</Banner>}

      <Card className={`overflow-hidden ${view === "all" ? "" : "hidden"}`}>
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3">
          <h2 className="text-sm font-medium">
            {data ? `${fmt.int(data.total)} keywords` : "Keywords"}
            {loading && <span className="ml-2 font-normal text-muted">Updating…</span>}
          </h2>
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search keywords"
            aria-label="Search keywords"
            className="w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm sm:w-64"
          />
        </div>

        {loading && !data ? (
          <p className="px-4 pb-6 text-sm text-muted">
            Analysing keywords… the first time you open a date range this can take up to ~30 seconds on large sites; after
            that filters are instant.
          </p>
        ) : rows.length === 0 ? (
          <p className="px-4 pb-6 text-sm text-muted">No keywords match these filters.</p>
        ) : (
          <div className="max-h-[640px] overflow-auto">
            <table className="w-full table-fixed text-sm">
              <thead className="sticky top-0 z-10 bg-surface text-xs text-muted">
                <tr className="border-b border-border">
                  <SortHeader label="Keyword" sort="query" q={q} onSort={sortBy} className="px-4 text-left" />
                  <SortHeader label="Clicks" sort="clicks" q={q} onSort={sortBy} className="w-20 px-2 text-right" />
                  <SortHeader label="Change" sort="click_change" q={q} onSort={sortBy} className="hidden w-20 px-2 text-right md:table-cell" />
                  <SortHeader label="Impr." sort="impressions" q={q} onSort={sortBy} className="w-24 px-2 text-right" />
                  <SortHeader label="CTR" sort="ctr" q={q} onSort={sortBy} className="hidden w-20 px-2 text-right sm:table-cell" />
                  <SortHeader label="Pos." sort="position" q={q} onSort={sortBy} className="w-16 px-4 text-right" />
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {rows.map((r) => (
                  <KeywordTableRow key={r.query} row={r} compareAvailable={!!data?.compare_available} />
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

function SortHeader({
  label,
  sort,
  q,
  onSort,
  className,
}: {
  label: string;
  sort: KeywordSort;
  q: KeywordQuery;
  onSort: (sort: KeywordSort) => void;
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

function KeywordTableRow({ row, compareAvailable }: { row: KeywordRow; compareAvailable: boolean }) {
  const change = row.click_change;
  return (
    <tr className="border-b border-border align-top last:border-0">
      <td className="max-w-0 px-4 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${row.brand ? "bg-chart-brand" : "bg-chart-non-brand"}`}
            title={row.brand ? "Brand" : "Non-brand"}
            aria-label={row.brand ? "Brand" : "Non-brand"}
          />
          <span className="truncate" title={row.query}>
            {row.query}
          </span>
        </div>
        {row.types.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1 pl-4">
            {TYPE_ORDER.filter((t) => row.types.includes(t)).map((t) => (
              <span key={t} className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent">
                {TYPE_LABEL[t]}
              </span>
            ))}
          </div>
        )}
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
        {row.types.includes("low_ctr") && row.expected_ctr != null && (
          <div className="text-[11px] text-muted" title="This site's typical CTR at this position">
            typical {fmt.pct(row.expected_ctr)}
          </div>
        )}
      </td>
      <td className="px-4 py-2 text-right">{row.position == null ? "—" : fmt.pos(row.position)}</td>
    </tr>
  );
}
