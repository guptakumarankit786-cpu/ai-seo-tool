"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { use, useEffect, useMemo, useState } from "react";
import { COMPARE_LABEL, RangeControls } from "@/components/range-controls";
import { Badge, Banner, Button, Card } from "@/components/ui";
import { api, fmt, type Compare, type PageDetail, type PageKeyword } from "@/lib/api";
import { VerdictBadge } from "../../indexing/indexing-view";
import { Kpi } from "../../property-dashboard";
import { TrafficChart } from "../../traffic-chart";
import { FILTER_LABEL, FILTER_ORDER, TYPE_LABEL } from "../pages-view";

type KeywordSort = "clicks" | "impressions" | "ctr" | "position";

export function PageDetailView({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const search = useSearchParams();
  const url = search.get("url") ?? "";
  const [days, setDays] = useState(Number(search.get("days")) || 28);
  const [compare, setCompare] = useState<Compare>(search.get("compare") === "year" ? "year" : "previous");
  const [data, setData] = useState<PageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestKey = JSON.stringify([url, days, compare]);
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const loading = doneKey !== requestKey;

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    api
      .pageDetail(id, url, days, compare)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setDoneKey(JSON.stringify([url, days, compare])));
    return () => {
      cancelled = true;
    };
  }, [id, url, days, compare]);

  const path = url.replace(/^https?:\/\/[^/]+/, "") || "/";
  const backHref = `/gsc/${id}/pages`;

  if (!url) return <Banner tone="error">No page chosen. Open one from the Pages tab.</Banner>;

  return (
    <div className="space-y-6">
      <header className="min-w-0">
        <Link href={backHref} className="text-xs text-muted hover:text-foreground">
          ← Pages
        </Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight break-all">{path}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          {data && <Badge>{TYPE_LABEL[data.type]}</Badge>}
          {data &&
            FILTER_ORDER.filter((f) => data.flags.includes(f)).map((f) => (
              <span key={f} className="rounded bg-accent-soft px-1.5 py-0.5 text-xs text-accent">
                {FILTER_LABEL[f]}
              </span>
            ))}
          <a href={url} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">
            Open live page ↗
          </a>
        </div>
        {data && (
          <p className="mt-2 text-sm text-muted">
            {fmt.date(data.start_date)} – {fmt.date(data.end_date)}
            {loading && " · Updating…"}
          </p>
        )}
      </header>

      <RangeControls days={days} onDays={setDays} compare={compare} onCompare={setCompare} />

      {error && <Banner tone="error">{error}</Banner>}
      {!data && !error && (
        <p className="text-sm text-muted">
          Loading this page… the first time a date range is opened, its keywords are fetched from Google (up to ~30
          seconds on large sites).
        </p>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Clicks" metric="clicks" summary={data} />
            <Kpi label="Impressions" metric="impressions" summary={data} />
            <div className="relative">
              <Kpi label="CTR" metric="ctr" summary={data} />
              {data.expected_ctr != null && (
                <p
                  className="absolute top-4 right-4 text-xs text-muted"
                  title="This site's typical page CTR at this position"
                >
                  typical {fmt.pct(data.expected_ctr)}
                </p>
              )}
            </div>
            <Kpi label="Avg. position" metric="position" summary={data} lowerIsBetter />
          </div>

          <Card className="p-4">
            <h2 className="mb-3 text-sm font-medium">Clicks and impressions</h2>
            {data.daily.length ? (
              <TrafficChart summary={data} compareLabel={COMPARE_LABEL[compare]} />
            ) : (
              <p className="py-10 text-center text-sm text-muted">No impressions for this page in this range.</p>
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <KeywordsCard data={data} onPickDays={setDays} />
            <IndexingCard data={data} propertyId={id} />
          </div>
        </>
      )}
    </div>
  );
}

function KeywordsCard({ data, onPickDays }: { data: PageDetail; onPickDays: (days: number) => void }) {
  const [sort, setSort] = useState<KeywordSort>("clicks");
  const rows = useMemo(
    () =>
      [...data.keywords].sort((a, b) =>
        sort === "position" ? a.position - b.position : b[sort] - a[sort] || b.impressions - a.impressions,
      ),
    [data.keywords, sort],
  );
  const keywordClicks = data.keywords.reduce((n, k) => n + k.clicks, 0);
  const hidden = data.totals.clicks - keywordClicks;

  return (
    <Card className="overflow-hidden">
      <div className="px-4 pt-4 pb-3">
        <h2 className="text-sm font-medium">
          Keywords bringing this page traffic{data.keywords_available && ` (${fmt.int(data.keywords.length)})`}
        </h2>
        {data.keywords_available && hidden > 0 && (
          <p className="mt-1 text-xs text-muted">
            {fmt.int(hidden)} of {fmt.int(data.totals.clicks)} clicks came from searches Google doesn&apos;t show
            (anonymised).
          </p>
        )}
      </div>
      {!data.keywords_available ? (
        <div className="space-y-3 px-4 pb-5 text-sm text-muted">
          <p>Keywords per page are fetched live from Google for up to 3 months.</p>
          <div className="flex gap-2">
            {[28, 90].map((d) => (
              <Button key={d} variant="secondary" onClick={() => onPickDays(d)}>
                Show {d === 28 ? "28 days" : "3 months"}
              </Button>
            ))}
          </div>
        </div>
      ) : rows.length === 0 ? (
        <p className="px-4 pb-6 text-sm text-muted">Google reported no keywords for this page in this range.</p>
      ) : (
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 z-10 bg-surface text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-normal">Keyword</th>
                {(
                  [
                    ["clicks", "Clicks", "w-16"],
                    ["impressions", "Impr.", "w-20"],
                    ["ctr", "CTR", "hidden w-20 sm:table-cell"],
                    ["position", "Pos.", "w-16"],
                  ] as const
                ).map(([key, label, width]) => (
                  <th
                    key={key}
                    className={`px-2 py-2 text-right font-normal last:pr-4 ${width}`}
                    aria-sort={sort === key ? (key === "position" ? "ascending" : "descending") : "none"}
                  >
                    <button
                      onClick={() => setSort(key)}
                      className={`hover:text-foreground ${sort === key ? "font-medium text-foreground" : ""}`}
                    >
                      {label}
                      {sort === key && (key === "position" ? " ↑" : " ↓")}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((k) => (
                <KeywordRow key={k.query} k={k} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.keywords_fetched_at && (
        <p className="border-t border-border px-4 py-2 text-xs text-muted">
          Fetched from Google {fmt.dateTime(data.keywords_fetched_at)} · refreshed after the next sync or 24 hours
        </p>
      )}
    </Card>
  );
}

function KeywordRow({ k }: { k: PageKeyword }) {
  return (
    <tr className="border-b border-border align-top last:border-0">
      <td className="max-w-0 px-4 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${k.brand ? "bg-chart-brand" : "bg-chart-non-brand"}`}
            title={k.brand ? "Brand" : "Non-brand"}
            aria-label={k.brand ? "Brand" : "Non-brand"}
          />
          <span className="truncate" title={k.query}>
            {k.query}
          </span>
        </div>
        {k.other_pages > 0 && (
          <p className="mt-0.5 pl-4 text-[11px] text-muted" title="Other pages of this site Google showed for the same search">
            +{k.other_pages} other {k.other_pages === 1 ? "page" : "pages"} shown for this search
          </p>
        )}
      </td>
      <td className="px-2 py-2 text-right">{fmt.int(k.clicks)}</td>
      <td className="px-2 py-2 text-right">{fmt.int(k.impressions)}</td>
      <td className="hidden px-2 py-2 text-right sm:table-cell">{fmt.pct(k.ctr)}</td>
      <td className="px-2 py-2 pr-4 text-right">{fmt.pos(k.position)}</td>
    </tr>
  );
}

function IndexingCard({ data, propertyId }: { data: PageDetail; propertyId: number }) {
  const insp = data.inspection;
  const canonicalMismatch =
    insp?.google_canonical && insp.user_canonical && insp.google_canonical !== insp.user_canonical;
  return (
    <Card className="space-y-4 self-start p-4 text-sm">
      <h2 className="text-sm font-medium">Indexing</h2>
      {!insp ? (
        <p className="text-muted">
          Not inspected yet.{" "}
          <Link href={`/gsc/${propertyId}/indexing`} className="text-accent hover:underline">
            Inspect pages from the Indexing tab
          </Link>{" "}
          to see whether Google has indexed it.
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${insp.indexed ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative"}`}
            >
              {insp.indexed ? "Indexed" : "Not indexed"}
            </span>
            {insp.advice && <VerdictBadge verdict={insp.advice.verdict} />}
          </div>
          {insp.coverage_state && <p>{insp.coverage_state}</p>}
          {insp.advice && (
            <div className="space-y-1 text-xs">
              <p className="text-muted">{insp.advice.summary}</p>
              <p>
                <b className="font-medium">What to do:</b> {insp.advice.action}
              </p>
            </div>
          )}
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted">Last crawled</dt>
            <dd>{insp.last_crawl_time ? fmt.date(insp.last_crawl_time.slice(0, 10)) : "Never"}</dd>
            <dt className="text-muted">In sitemap</dt>
            <dd>{insp.in_sitemap ? "Yes" : "No"}</dd>
            <dt className="text-muted">Checked</dt>
            <dd>{insp.inspected_at ? fmt.date(insp.inspected_at.slice(0, 10)) : "—"}</dd>
          </dl>
          {canonicalMismatch && (
            <p className="text-xs text-warning">
              Google picked a different canonical: <span className="break-all">{insp.google_canonical}</span>
            </p>
          )}
        </div>
      )}

      {data.export_issues.length > 0 && (
        <div className="space-y-2 border-t border-border pt-3">
          <p className="text-xs text-muted">Listed in your Search Console export under:</p>
          {data.export_issues.map((e) => (
            <div key={e.issue} className="flex flex-wrap items-center gap-2 text-xs">
              <VerdictBadge verdict={e.advice.verdict} />
              <span>{e.issue}</span>
              <span className="text-muted">· uploaded {fmt.date(e.uploaded_at.slice(0, 10))}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
