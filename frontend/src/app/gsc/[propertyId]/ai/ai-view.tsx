"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ClientToolbar } from "@/components/client-toolbar";
import { change, MetricCard, SessionsChart } from "@/components/ga4-ui";
import { PropertyTabs } from "@/components/property-tabs";
import { COMPARE_LABEL, periodText, useDateRange } from "@/components/range-controls";
import { Badge, Banner, Card } from "@/components/ui";
import { api, fmt, propertyLabel, type AiTraffic, type Property } from "@/lib/api";

export function AiView({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [property, setProperty] = useState<Property | null>(null);
  const [range] = useDateRange();
  const [data, setData] = useState<AiTraffic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const loading = doneKey !== JSON.stringify(range);

  useEffect(() => {
    api.property(id).then(setProperty).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    api
      .aiTraffic(id, range)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setDoneKey(JSON.stringify(range)));
    return () => {
      cancelled = true;
    };
  }, [id, range]);

  if (!property) return error ? <Banner tone="error">{error}</Banner> : <p className="text-sm text-muted">Loading…</p>;
  const { name, kind } = propertyLabel(property.site_url);

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
            {/* GA4 isn't limited to stored Search Console history, so the comparison is always available */}
            {periodText({ ...data, compare_available: true })} · visits from AI assistants, from GA4
            {loading && <span className="ml-2">Updating…</span>}
          </p>
        )}
      </header>

      <ClientToolbar propertyId={id} />
      <PropertyTabs propertyId={id} active="ai" />

      {error && <Banner tone="error">{error}</Banner>}
      {loading && !data && <p className="text-sm text-muted">Reading GA4…</p>}
      {data && <AiReport data={data} />}
    </div>
  );
}

function AiReport({ data }: { data: AiTraffic }) {
  if (data.error) return <Banner tone="error">{data.error}</Banner>;
  if (!data.linked)
    return (
      <Card className="p-6 text-sm text-muted">
        No GA4 property is linked to this client, so AI visits can&apos;t be read.{" "}
        <Link href="/integrations" className="text-accent hover:underline">
          Pick one on Integrations
        </Link>
        .
      </Card>
    );

  const { totals: t, previous: p, currency, compare } = data;
  const share = data.all_sessions ? t.sessions / data.all_sessions : 0;
  const prevShare = p && data.previous_all_sessions ? p.sessions / data.previous_all_sessions : null;
  const money = (n: number) => (data.revenue_tracked ? fmt.money(n, currency) : "—");
  const sources = [...data.assistants, ...(data.ads ? [data.ads] : [])];

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">
        GA4 · {data.ga4_name}. AI visits = GA4&apos;s &quot;AI Assistant&quot; channel plus visits from known assistants GA4
        files elsewhere (ChatGPT, Gemini, Perplexity, Claude, Copilot, DeepSeek…). ChatGPT ads are listed apart.
      </p>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <MetricCard label="AI sessions" value={fmt.int(t.sessions)} now={t.sessions} before={p?.sessions} compare={compare} />
        <MetricCard
          label="Share of all sessions"
          value={`${(share * 100).toFixed(2)}%`}
          now={share}
          before={prevShare}
          compare={compare}
          hint={`of ${fmt.int(data.all_sessions)} sessions`}
        />
        <MetricCard label="Orders" value={fmt.int(t.orders)} now={t.orders} before={p?.orders} compare={compare} />
        <MetricCard label="Key events" value={fmt.int(t.key_events)} now={t.key_events} before={p?.key_events} compare={compare} />
        <MetricCard
          label="Revenue"
          value={data.revenue_tracked ? fmt.money(t.revenue, currency) : "Not tracked"}
          now={t.revenue}
          before={data.revenue_tracked ? p?.revenue : null}
          compare={compare}
          hint={data.revenue_tracked ? undefined : "GA4 counts orders but no order value"}
        />
      </div>

      <Card className="p-4">
        <h2 className="mb-3 text-sm font-medium">AI sessions per day</h2>
        {data.daily.length ? (
          <SessionsChart
            startDate={data.start_date}
            compareStart={data.compare_start}
            daily={data.daily}
            previousDaily={data.previous_daily}
            compareLabel={COMPARE_LABEL[compare]}
          />
        ) : (
          <p className="py-10 text-center text-sm text-muted">No visits from AI assistants in this period.</p>
        )}
      </Card>

      <Card className="overflow-hidden">
        <h2 className="px-4 pt-4 pb-3 text-sm font-medium">By assistant</h2>
        <table className="w-full table-fixed text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-y border-border">
              <th className="px-4 py-2 text-left font-normal">Assistant</th>
              <th className="w-24 px-2 py-2 text-right font-normal">Sessions</th>
              <th className="hidden w-24 px-2 py-2 text-right font-normal sm:table-cell">Change</th>
              <th className="w-20 px-2 py-2 text-right font-normal">Orders</th>
              <th className="hidden w-24 px-2 py-2 text-right font-normal md:table-cell">Key events</th>
              <th className="w-28 px-4 py-2 text-right font-normal">Revenue</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {sources.map((a) => {
              const delta = change(a.sessions, a.previous?.sessions);
              const isAds = a === data.ads;
              return (
                <tr key={a.assistant} className={`border-b border-border last:border-0 ${isAds ? "text-muted" : ""}`}>
                  <td className="px-4 py-2">
                    {a.assistant}
                    {isAds && <span className="ml-2 text-xs">paid · not in the totals above</span>}
                  </td>
                  <td className="px-2 py-2 text-right">{fmt.int(a.sessions)}</td>
                  <td
                    className={`hidden px-2 py-2 text-right sm:table-cell ${
                      delta ? (delta.up ? "text-positive" : "text-negative") : "text-muted"
                    }`}
                  >
                    {delta ? delta.text : a.previous && a.sessions ? "new" : "—"}
                  </td>
                  <td className="px-2 py-2 text-right">{fmt.int(a.orders)}</td>
                  <td className="hidden px-2 py-2 text-right md:table-cell">{fmt.int(a.key_events)}</td>
                  <td className="px-4 py-2 text-right">{money(a.revenue)}</td>
                </tr>
              );
            })}
            {sources.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  No AI assistant visits in this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      <Card className="overflow-hidden">
        <h2 className="px-4 pt-4 pb-3 text-sm font-medium">Pages AI visitors land on</h2>
        {data.pages.length === 0 ? (
          <p className="px-4 pb-6 text-sm text-muted">No landing pages in this period.</p>
        ) : (
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full table-fixed text-sm">
              <thead className="sticky top-0 bg-surface text-xs text-muted">
                <tr className="border-y border-border">
                  <th className="px-4 py-2 text-left font-normal">Page</th>
                  <th className="hidden w-28 px-2 py-2 text-left font-normal sm:table-cell">Mostly from</th>
                  <th className="w-20 px-2 py-2 text-right font-normal">Sessions</th>
                  <th className="hidden w-20 px-2 py-2 text-right font-normal md:table-cell">Before</th>
                  <th className="w-20 px-2 py-2 text-right font-normal">Orders</th>
                  <th className="w-28 px-4 py-2 text-right font-normal">Revenue</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {data.pages.map((pg) => (
                  <tr key={pg.url} className="border-b border-border last:border-0">
                    <td className="max-w-0 px-4 py-2">
                      <a
                        href={pg.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate hover:text-accent hover:underline"
                        title={pg.url}
                      >
                        {pg.url.replace(/^https?:\/\/[^/]+/, "") || "/"} <span className="text-xs text-muted">↗</span>
                      </a>
                    </td>
                    <td className="hidden px-2 py-2 sm:table-cell">{pg.assistant}</td>
                    <td className="px-2 py-2 text-right">{fmt.int(pg.sessions)}</td>
                    <td className="hidden px-2 py-2 text-right text-muted md:table-cell">
                      {pg.previous_sessions == null ? "—" : fmt.int(pg.previous_sessions)}
                    </td>
                    <td className="px-2 py-2 text-right">{fmt.int(pg.orders)}</td>
                    <td className="px-4 py-2 text-right">{money(pg.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
