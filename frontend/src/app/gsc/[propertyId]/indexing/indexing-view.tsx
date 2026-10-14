"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { PropertyTabs } from "@/components/property-tabs";
import { Badge, Banner, Button, Card } from "@/components/ui";
import {
  api,
  fmt,
  propertyLabel,
  type IndexingSummary,
  type InspectedPage,
  type Property,
} from "@/lib/api";

const POLL_MS = 3000;
const PAGE_SIZE = 100;

export function IndexingView({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [property, setProperty] = useState<Property | null>(null);
  const [summary, setSummary] = useState<IndexingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.property(id), api.indexing(id)])
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
  }, [id, version]);

  const running = summary?.latest_run?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [running, reload]);

  if (error && !summary) return <Banner tone="error">{error}</Banner>;
  if (!property || !summary) return <p className="text-sm text-muted">Loading…</p>;

  const { name, kind } = propertyLabel(property.site_url);
  const quotaLeft = Math.max(0, summary.daily_limit - summary.used_last_24h);
  const pending = summary.known - summary.inspected;

  const start = async () => {
    setStarting(true);
    try {
      await api.startInspection(id);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    setStarting(false);
    reload();
  };

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
            {summary.last_inspected_at
              ? `Last inspected ${fmt.dateTime(summary.last_inspected_at)} · Google URL Inspection`
              : "Not inspected yet · Google URL Inspection"}
          </p>
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <Button onClick={start} disabled={running || starting || quotaLeft === 0}>
            {running ? "Inspecting…" : summary.inspected ? "Inspect more pages" : "Inspect pages"}
          </Button>
          <span className="text-xs text-muted">
            {fmt.int(quotaLeft)} of {fmt.int(summary.daily_limit)} inspections left today
          </span>
        </div>
      </header>

      <PropertyTabs propertyId={id} active="indexing" />

      {error && <Banner tone="error">{error}</Banner>}
      <RunStatus summary={summary} pending={pending} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Indexed" value={summary.indexed} tone="positive" />
        <Stat label="Not indexed" value={summary.not_indexed} tone="negative" />
        <Stat label="Waiting to be inspected" value={pending} />
        <Stat label="Pages found" value={summary.known} hint="From sitemaps + search results" />
      </div>

      <Card className="overflow-hidden">
        <div className="px-4 pt-4 pb-3">
          <h2 className="text-sm font-medium">Why pages aren&apos;t indexed</h2>
          <p className="mt-0.5 text-xs text-muted">
            Based on the {fmt.int(summary.inspected)} pages inspected so far. Search Console&apos;s own
            report can include URLs we haven&apos;t found yet.
          </p>
        </div>
        {summary.reasons.length === 0 ? (
          <p className="border-t border-border px-4 py-6 text-sm text-muted">
            {summary.inspected
              ? "Every inspected page is indexed. 🎉"
              : "Run an inspection to see why pages aren't indexed."}
          </p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {summary.reasons.map((r) => (
              <ReasonRow key={r.reason} propertyId={id} reason={r.reason} pages={r.pages} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function RunStatus({ summary, pending }: { summary: IndexingSummary; pending: number }) {
  const run = summary.latest_run;
  if (!run) return null;

  if (run.status === "running") {
    const done = run.urls_inspected + run.urls_failed;
    const pct = run.urls_queued ? Math.round((done / run.urls_queued) * 100) : 0;
    return (
      <Card className="p-4">
        <p className="text-sm">
          {run.urls_queued
            ? `Inspecting pages… ${fmt.int(done)} of ${fmt.int(run.urls_queued)}`
            : "Finding pages from sitemaps and search results…"}
        </p>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-accent-soft">
          <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
      </Card>
    );
  }
  if (run.status === "failed") {
    return <Banner tone="error">Last inspection failed: {run.error}</Banner>;
  }
  if (pending > 0) {
    return (
      <Card className="p-4 text-sm text-muted">
        {fmt.int(pending)} pages still waiting. Google allows {fmt.int(summary.daily_limit)}{" "}
        inspections per property per day — run again tomorrow to continue.
        {run.urls_failed > 0 && ` ${fmt.int(run.urls_failed)} pages couldn't be inspected last run.`}
      </Card>
    );
  }
  return null;
}

function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: number;
  tone?: "positive" | "negative";
  hint?: string;
}) {
  const color = tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : "";
  return (
    <Card className="p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{fmt.int(value)}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  );
}

function ReasonRow({ propertyId, reason, pages }: { propertyId: number; reason: string; pages: number }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<InspectedPage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMore = async (offset: number) => {
    setLoading(true);
    try {
      const res = await api.inspectedPages(propertyId, reason, PAGE_SIZE, offset);
      setItems((prev) => (offset === 0 ? res.items : [...prev, ...res.items]));
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    setLoading(false);
  };

  const toggle = () => {
    if (!open && items.length === 0) loadMore(0);
    setOpen(!open);
  };

  return (
    <li>
      <button
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left text-sm hover:bg-accent-soft"
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className={`text-muted transition-transform ${open ? "rotate-90" : ""}`}>›</span>
          <span className="truncate">{reason}</span>
        </span>
        <span className="shrink-0 tabular-nums font-medium">{fmt.int(pages)}</span>
      </button>

      {open && (
        <div className="border-t border-border bg-background/40">
          {error && <p className="px-4 py-3 text-xs text-negative">{error}</p>}
          <div className="max-h-[480px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface text-muted">
                <tr className="border-b border-border">
                  <th className="px-4 py-2 text-left font-normal">URL</th>
                  <th className="hidden px-2 py-2 text-left font-normal md:table-cell">Google canonical</th>
                  <th className="px-4 py-2 text-right font-normal">Last crawled</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.url} className="border-b border-border last:border-0">
                    <td className="max-w-0 px-4 py-2">
                      <div className="flex items-center gap-2">
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noreferrer"
                          title={p.url}
                          className="truncate hover:underline"
                        >
                          {p.url.replace(/^https?:\/\/[^/]+/, "") || "/"}
                        </a>
                        {p.in_sitemap && <Badge>sitemap</Badge>}
                      </div>
                    </td>
                    <td className="hidden max-w-0 truncate px-2 py-2 text-muted md:table-cell" title={p.google_canonical ?? ""}>
                      {p.google_canonical && p.google_canonical !== p.url
                        ? p.google_canonical.replace(/^https?:\/\/[^/]+/, "") || "/"
                        : "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-right text-muted tabular-nums">
                      {p.last_crawl_time ? fmt.date(p.last_crawl_time.slice(0, 10)) : "Never"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
            <span>
              Showing {fmt.int(items.length)} of {fmt.int(total)}
            </span>
            {items.length < total && (
              <Button variant="secondary" disabled={loading} onClick={() => loadMore(items.length)}>
                {loading ? "Loading…" : "Show more"}
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
