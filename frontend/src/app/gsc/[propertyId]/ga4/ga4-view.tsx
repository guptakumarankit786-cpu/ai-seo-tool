"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ClientToolbar } from "@/components/client-toolbar";
import { change, MetricCard, SessionsChart } from "@/components/ga4-ui";
import { PropertyTabs } from "@/components/property-tabs";
import { COMPARE_LABEL, periodText, useDateRange } from "@/components/range-controls";
import { Badge, Banner, Card } from "@/components/ui";
import { api, fmt, propertyLabel, type Ga4Overview, type Ga4Totals, type Property } from "@/lib/api";

export function Ga4View({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [property, setProperty] = useState<Property | null>(null);
  const [range] = useDateRange();
  const [data, setData] = useState<Ga4Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const loading = doneKey !== JSON.stringify(range);

  useEffect(() => {
    api.property(id).then(setProperty).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    api
      .ga4Overview(id, range)
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
            {periodText({ ...data, compare_available: true })} · every channel, from GA4
            {loading && <span className="ml-2">Updating…</span>}
          </p>
        )}
      </header>

      <ClientToolbar propertyId={id} />
      <PropertyTabs propertyId={id} active="ga4" />

      {error && <Banner tone="error">{error}</Banner>}
      {loading && !data && <p className="text-sm text-muted">Reading GA4…</p>}
      {data && <Overview data={data} />}
    </div>
  );
}

const rate = (t: Ga4Totals) => (t.sessions ? t.engaged_sessions / t.sessions : 0);

function Overview({ data }: { data: Ga4Overview }) {
  if (data.error) return <Banner tone="error">{data.error}</Banner>;
  if (!data.linked)
    return (
      <Card className="p-6 text-sm text-muted">
        No GA4 property is linked to this client.{" "}
        <Link href="/integrations" className="text-accent hover:underline">
          Pick one on Integrations
        </Link>
        .
      </Card>
    );

  const { totals: t, previous: p, currency, compare } = data;
  const money = (n: number) => (data.revenue_tracked ? fmt.money(n, currency) : "—");
  const deviceTotal = data.devices.reduce((s, d) => s + d.sessions, 0);

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">GA4 · {data.ga4_name}</p>
      {data.unassigned_share >= 0.2 && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2 text-sm text-warning">
          {Math.round(data.unassigned_share * 100)}% of sessions are &quot;Unassigned&quot; — GA4 couldn&apos;t tell where they came
          from. This is a tracking setup problem (on Shopify often the custom pixel), so channel numbers below are incomplete.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="Sessions" value={fmt.int(t.sessions)} now={t.sessions} before={p?.sessions} compare={compare} />
        <MetricCard label="Users" value={fmt.int(t.users)} now={t.users} before={p?.users} compare={compare} />
        <MetricCard
          label="Engagement rate"
          value={`${(rate(t) * 100).toFixed(1)}%`}
          now={rate(t)}
          before={p ? rate(p) : null}
          compare={compare}
        />
        <MetricCard label="Key events" value={fmt.int(t.key_events)} now={t.key_events} before={p?.key_events} compare={compare} />
        <MetricCard label="Orders" value={fmt.int(t.orders)} now={t.orders} before={p?.orders} compare={compare} />
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
        <h2 className="mb-3 text-sm font-medium">Sessions per day</h2>
        {data.daily.length ? (
          <SessionsChart
            startDate={data.start_date}
            compareStart={data.compare_start}
            daily={data.daily}
            previousDaily={data.previous_daily}
            compareLabel={COMPARE_LABEL[compare]}
          />
        ) : (
          <p className="py-10 text-center text-sm text-muted">No sessions in this period.</p>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Card className="overflow-hidden">
          <h2 className="px-4 pt-4 pb-3 text-sm font-medium">Channels</h2>
          <table className="w-full table-fixed text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-y border-border">
                <th className="px-4 py-2 text-left font-normal">Channel</th>
                <th className="w-24 px-2 py-2 text-right font-normal">Sessions</th>
                <th className="hidden w-20 px-2 py-2 text-right font-normal sm:table-cell">Change</th>
                <th className="hidden w-24 px-2 py-2 text-right font-normal md:table-cell">Engaged</th>
                <th className="w-20 px-2 py-2 text-right font-normal">Orders</th>
                <th className="w-28 px-4 py-2 text-right font-normal">Revenue</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.channels.map((c) => {
                const delta = change(c.sessions, c.previous_sessions);
                return (
                  <tr key={c.channel} className="border-b border-border last:border-0">
                    <td className="truncate px-4 py-2">{c.channel}</td>
                    <td className="px-2 py-2 text-right">{fmt.int(c.sessions)}</td>
                    <td
                      className={`hidden px-2 py-2 text-right sm:table-cell ${
                        delta ? (delta.up ? "text-positive" : "text-negative") : "text-muted"
                      }`}
                    >
                      {delta ? delta.text : c.previous_sessions === 0 && c.sessions ? "new" : "—"}
                    </td>
                    <td className="hidden px-2 py-2 text-right md:table-cell">{(rate(c) * 100).toFixed(1)}%</td>
                    <td className="px-2 py-2 text-right">{fmt.int(c.orders)}</td>
                    <td className="px-4 py-2 text-right">{money(c.revenue)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <Card className="space-y-3 self-start p-4">
          <h2 className="text-sm font-medium">Devices</h2>
          {data.devices.map((d) => {
            const share = deviceTotal ? d.sessions / deviceTotal : 0;
            return (
              <div key={d.device} className="text-sm">
                <div className="flex justify-between gap-2">
                  <span className="capitalize">{d.device}</span>
                  <span className="tabular-nums text-muted">
                    {fmt.int(d.sessions)} · {(share * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-border">
                  <div className="h-1.5 rounded-full bg-accent" style={{ width: `${share * 100}%` }} />
                </div>
                <p className="mt-0.5 text-xs text-muted tabular-nums">
                  {fmt.int(d.orders)} orders · {money(d.revenue)}
                </p>
              </div>
            );
          })}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <h2 className="px-4 pt-4 pb-3 text-sm font-medium">Top landing pages · all channels</h2>
        <div className="max-h-[560px] overflow-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr className="border-y border-border">
                <th className="px-4 py-2 text-left font-normal">Landing page</th>
                <th className="w-24 px-2 py-2 text-right font-normal">Sessions</th>
                <th className="hidden w-24 px-2 py-2 text-right font-normal md:table-cell">Engaged</th>
                <th className="w-20 px-2 py-2 text-right font-normal">Orders</th>
                <th className="w-28 px-4 py-2 text-right font-normal">Revenue</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.pages.map((pg) => (
                <tr key={pg.url} className="border-b border-border last:border-0">
                  <td className="max-w-0 px-4 py-2">
                    {pg.url.startsWith("http") ? (
                      <a
                        href={pg.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate hover:text-accent hover:underline"
                        title={pg.url}
                      >
                        {pg.url.replace(/^https?:\/\/[^/]+/, "") || "/"} <span className="text-xs text-muted">↗</span>
                      </a>
                    ) : (
                      <span className="text-muted">{pg.url}</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">{fmt.int(pg.sessions)}</td>
                  <td className="hidden px-2 py-2 text-right md:table-cell">{(rate(pg) * 100).toFixed(1)}%</td>
                  <td className="px-2 py-2 text-right">{fmt.int(pg.orders)}</td>
                  <td className="px-4 py-2 text-right">{money(pg.revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
