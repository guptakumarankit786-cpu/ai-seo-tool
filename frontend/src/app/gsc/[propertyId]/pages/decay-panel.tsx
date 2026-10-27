"use client";

import Link from "next/link";
import { useState } from "react";
import { SyncStatus } from "@/components/sync-controls";
import { Banner, Button, Card } from "@/components/ui";
import { useSync } from "@/components/use-sync";
import { api, fmt, type DecayCause, type DecayResponse, type DecayRow, type PageType, type Property } from "@/lib/api";
import { MonthBars } from "../keywords/monthly-views";
import { usePaged } from "../keywords/opportunity-views";
import { TYPE_LABEL } from "./pages-view";

const PAGE_SIZE = 50;

const CAUSE: Record<DecayCause, { label: string; style: string }> = {
  ranking: { label: "Ranking dropped", style: "bg-negative/15 text-negative" },
  demand: { label: "Fewer searches", style: "bg-accent-soft text-accent" },
  ctr: { label: "Lower CTR", style: "bg-warning/15 text-warning" },
  sudden: { label: "Sudden drop", style: "bg-negative/15 text-negative" },
  mixed: { label: "Mixed", style: "border border-border text-muted" },
};

const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
// "Jul 2026" — fmt.month's "Jul 26" reads like a date in running text.
const monthYear = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });

/** One line: what the numbers say and what to do about it. */
function explain(r: DecayRow, d: DecayResponse["definitions"]): string {
  const imprChange = r.before_impressions ? r.recent_impressions / r.before_impressions - 1 : 0;
  const ctrBefore = r.before_impressions ? r.before_clicks / r.before_impressions : 0;
  const ctrNow = r.recent_impressions ? r.recent_clicks / r.recent_impressions : 0;
  const pos = (p: number | null) => (p == null ? "—" : fmt.pos(p));
  return {
    ranking: `Average position slipped from ${pos(r.before_position)} to ${pos(r.recent_position)}. Refresh the content — update facts, cover what newer competing pages cover, add internal links.`,
    demand: `Impressions fell ${pct(-imprChange)} while position held (${pos(r.before_position)} → ${pos(r.recent_position)}) — fewer people search for this, or Google shows it for fewer searches. Check if the topic is seasonal or fading; widen the page to related searches.`,
    ctr: `Impressions and position held, but CTR fell from ${fmt.pct(ctrBefore)} to ${fmt.pct(ctrNow)}. Rewrite the title and description; check for new search features above it.`,
    sudden: `Clicks fell by ${pct(d.sudden_drop)}+ in a single month — that's a cliff, not slow decay. Check whether the page changed, redirected, was removed or de-indexed, or went out of stock.`,
    mixed: `Position, impressions and CTR each slipped a little (position ${pos(r.before_position)} → ${pos(r.recent_position)}, impressions ${imprChange > 0 ? "+" : ""}${pct(imprChange)}).`,
  }[r.cause];
}

export function DecayPanel({ property, onSynced }: { property: Property; onSynced: () => void }) {
  const propertyId = property.id;
  const [types, setTypes] = useState<PageType[]>([]);
  const [version, setVersion] = useState(0);
  const { data, rows, error, loading, more } = usePaged<DecayRow, DecayResponse>(
    (offset) => api.pageDecay(propertyId, types, PAGE_SIZE, offset),
    [propertyId, types, version],
  );

  if (error) return <Banner tone="error">{error}</Banner>;
  if (!data) return <p className="text-sm text-muted">Looking for decaying pages…</p>;

  const d = data.definitions;
  if (!data.available) {
    return (
      <Card className="space-y-1 p-6 text-sm">
        <p className="font-medium">Not enough history yet</p>
        <p className="text-muted">
          Content decay compares the last {d.window_months} full months with the {d.window_months} before, so it needs{" "}
          {d.min_months} full months of data ({data.months.length} stored). Pull this client&apos;s full 16 months from
          Google — it runs in the background (a few minutes on large sites) and you can keep working.
        </p>
        <FullSync
          property={property}
          onDone={() => {
            setVersion((v) => v + 1);
            onSynced();
          }}
        />
      </Card>
    );
  }

  const recentFrom = data.months[data.months.length - d.window_months];
  const typeKeys = (Object.keys(TYPE_LABEL) as PageType[]).filter((t) => data.type_counts[t]);

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 px-4 pt-4 pb-3">
        <div>
          <h2 className="text-sm font-medium">
            {fmt.int(data.total)} decaying {data.total === 1 ? "page" : "pages"}
            {loading && <span className="ml-2 font-normal text-muted">Updating…</span>}
          </h2>
          <p className="mt-1 text-xs text-muted">
            Clicks in the last {d.window_months} full months ({monthYear(recentFrom)} – {monthYear(data.months[data.months.length - 1])})
            down at least {pct(d.min_drop)} on the {d.window_months} months before, falling in at least {d.min_falling_months} of the
            last {d.window_months} months, from {d.min_clicks}+ clicks. Biggest loss first. Seasonal pages can show up here
            too — with more than a year of stored history, compare the same months last year.
          </p>
        </div>
        {typeKeys.length > 1 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Page types">
            {typeKeys.map((t) => {
              const active = types.includes(t);
              return (
                <button
                  key={t}
                  onClick={() => setTypes(active ? types.filter((x) => x !== t) : [...types, t])}
                  aria-pressed={active}
                  className={`rounded-full border px-3 py-1 text-sm ${active ? "border-accent bg-accent-soft text-accent" : "border-border hover:bg-accent-soft"}`}
                >
                  {TYPE_LABEL[t]} <span className="tabular-nums text-muted">{data.type_counts[t]}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <p className="border-t border-border px-4 py-6 text-sm text-muted">
          No decaying pages{types.length ? " of this type" : ""} — nothing has lost clicks steadily over the last {d.window_months} months.
        </p>
      ) : (
        <ul className="divide-y divide-border border-t border-border">
          {rows.map((r) => (
            <DecayItem key={r.page} row={r} months={data.months} recentFrom={recentFrom} propertyId={propertyId} d={d} />
          ))}
        </ul>
      )}

      {rows.length < data.total && (
        <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted">
          <span>
            Showing {fmt.int(rows.length)} of {fmt.int(data.total)}
          </span>
          <Button variant="secondary" disabled={loading} onClick={more}>
            {loading ? "Loading…" : "Show more"}
          </Button>
        </div>
      )}
    </Card>
  );
}

function FullSync({ property, onDone }: { property: Property; onDone: () => void }) {
  const { run, running, error, start } = useSync(property, onDone);
  return (
    <div className="space-y-1 pt-2">
      <Button disabled={running} onClick={() => start({ mode: "range", days: 486 })}>
        {running ? "Syncing…" : "Sync full 16 months"}
      </Button>
      {(running || run?.status === "failed") && (
        <p className="text-xs text-muted">
          <SyncStatus property={property} running={running} run={run} />
        </p>
      )}
      {error && <p className="text-xs text-negative">{error}</p>}
    </div>
  );
}

function DecayItem({
  row,
  months,
  recentFrom,
  propertyId,
  d,
}: {
  row: DecayRow;
  months: string[];
  recentFrom: string;
  propertyId: number;
  d: DecayResponse["definitions"];
}) {
  const path = row.page.replace(/^https?:\/\/[^/]+/, "") || "/";
  const perMonth = Math.round(row.lost_clicks / d.window_months);
  return (
    <li className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto_11rem] md:items-center md:gap-6">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <Link
            href={`/gsc/${propertyId}/pages/detail?${new URLSearchParams({ url: row.page, days: "90" })}`}
            className="truncate text-sm hover:text-accent hover:underline"
            title={`${row.page} — open page details`}
          >
            {path}
          </Link>
          <a
            href={row.page}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 text-xs text-muted hover:text-foreground"
            aria-label="Open the live page in a new tab"
          >
            ↗
          </a>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted">{TYPE_LABEL[row.type]}</span>
          <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${CAUSE[row.cause].style}`}>{CAUSE[row.cause].label}</span>
        </div>
        <p className="mt-1.5 text-xs text-muted">{explain(row, d)}</p>
      </div>
      <MonthBars months={months} values={row.clicks} highlight={(m) => m >= recentFrom} unit="clicks" />
      <div className="text-sm tabular-nums md:text-right">
        <div>
          {fmt.int(row.before_clicks)} → {fmt.int(row.recent_clicks)}{" "}
          <span className="text-negative">−{pct(row.drop)}</span>
        </div>
        <div className="text-xs text-muted">
          clicks per {d.window_months} months · −{fmt.int(perMonth)}/month
        </div>
      </div>
    </li>
  );
}
