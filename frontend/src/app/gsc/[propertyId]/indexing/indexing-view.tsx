"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { PropertyTabs } from "@/components/property-tabs";
import { Badge, Banner, Button, Card } from "@/components/ui";
import {
  api,
  fmt,
  propertyLabel,
  type Advice,
  type ExportReason,
  type IndexingExport,
  type IndexingSummary,
  type InspectedPage,
  type Property,
  type Verdict,
} from "@/lib/api";

const POLL_MS = 3000;
const PAGE_SIZE = 100;

type Source = "inspection" | "export";

export function IndexingView({ params }: { params: Promise<{ propertyId: string }> }) {
  const id = Number(use(params).propertyId);
  const [property, setProperty] = useState<Property | null>(null);
  const [summary, setSummary] = useState<IndexingSummary | null>(null);
  const [exported, setExported] = useState<IndexingExport | null>(null);
  const [source, setSource] = useState<Source>("inspection");
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.property(id), api.indexing(id), api.indexingExport(id)])
      .then(([p, s, e]) => {
        if (cancelled) return;
        setProperty(p);
        setSummary(s);
        setExported(e);
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
      </header>

      <PropertyTabs propertyId={id} active="indexing" />

      <div className="flex rounded-md border border-border bg-surface p-0.5 text-sm sm:w-fit" role="tablist">
        <SourceTab active={source === "inspection"} onClick={() => setSource("inspection")}>
          Inspected by app
        </SourceTab>
        <SourceTab active={source === "export"} onClick={() => setSource("export")}>
          Search Console export{exported ? "" : " (upload)"}
        </SourceTab>
      </div>

      {error && <Banner tone="error">{error}</Banner>}

      {source === "inspection" ? (
        <InspectionPanel propertyId={id} summary={summary} onChange={reload} onError={setError} />
      ) : (
        <ExportPanel propertyId={id} exported={exported} onChange={reload} />
      )}
    </div>
  );
}

function SourceTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex-1 rounded px-3 py-1.5 sm:flex-none ${active ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-foreground"}`}
    >
      {children}
    </button>
  );
}

// ---------- shared ----------

const VERDICT_LABEL: Record<Verdict, string> = {
  fix: "Worth fixing",
  review: "Check pages",
  ignore: "Safe to ignore",
};

const VERDICT_STYLE: Record<Verdict, string> = {
  fix: "bg-negative/15 text-negative",
  review: "bg-accent-soft text-accent",
  ignore: "bg-positive/15 text-positive",
};

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT_STYLE[verdict]}`}>
      {VERDICT_LABEL[verdict]}
    </span>
  );
}

function VerdictTotals({ rows }: { rows: { pages: number; advice: Advice }[] }) {
  const total = (v: Verdict) => rows.filter((r) => r.advice.verdict === v).reduce((n, r) => n + r.pages, 0);
  return (
    <div className="grid grid-cols-3 gap-3">
      {(["fix", "review", "ignore"] as const).map((v) => (
        <Card key={v} className="p-4">
          <VerdictBadge verdict={v} />
          <p className="mt-2 text-2xl font-semibold tabular-nums">{fmt.int(total(v))}</p>
          <p className="text-xs text-muted">pages</p>
        </Card>
      ))}
    </div>
  );
}

function AdviceBox({ advice, inSitemap }: { advice: Advice; inSitemap?: number }) {
  return (
    <div className="space-y-1 border-b border-border px-4 py-3 text-sm">
      <p className="text-muted">{advice.summary}</p>
      <p>
        <span className="font-medium">What to do: </span>
        {advice.action}
      </p>
      {advice.sitemap_cleanup && !!inSitemap && (
        <p className="text-negative">
          {fmt.int(inSitemap)} of these {inSitemap === 1 ? "is" : "are"} listed in the sitemap — remove{" "}
          {inSitemap === 1 ? "it" : "them"} so the sitemap only lists pages you want indexed.
        </p>
      )}
    </div>
  );
}

function Stat({ label, value, tone, hint }: { label: string; value: number | null; tone?: "positive" | "negative"; hint?: string }) {
  const color = tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : "";
  return (
    <Card className="p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value === null ? "—" : fmt.int(value)}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  );
}

function ExpandableRow({
  title,
  verdict,
  pages,
  meta,
  onOpen,
  children,
}: {
  title: string;
  verdict: Verdict;
  pages: number;
  meta?: string;
  onOpen?: () => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        onClick={() => {
          if (!open) onOpen?.();
          setOpen(!open);
        }}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm hover:bg-accent-soft"
      >
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className={`text-muted transition-transform ${open ? "rotate-90" : ""}`}>›</span>
          <span className="truncate">{title}</span>
          <VerdictBadge verdict={verdict} />
          {meta && <span className="text-xs text-muted">{meta}</span>}
        </span>
        <span className="shrink-0 font-medium tabular-nums">{fmt.int(pages)}</span>
      </button>
      {open && <div className="border-t border-border bg-background/40">{children}</div>}
    </li>
  );
}

function stripHost(url: string) {
  return url.replace(/^https?:\/\/[^/]+/, "") || "/";
}

// ---------- inspected by app ----------

function InspectionPanel({
  propertyId,
  summary,
  onChange,
  onError,
}: {
  propertyId: number;
  summary: IndexingSummary;
  onChange: () => void;
  onError: (msg: string | null) => void;
}) {
  const [starting, setStarting] = useState(false);
  const running = summary.latest_run?.status === "running";
  const quotaLeft = Math.max(0, summary.daily_limit - summary.used_last_24h);
  const pending = summary.known - summary.inspected;

  const start = async () => {
    setStarting(true);
    try {
      await api.startInspection(propertyId);
      onError(null);
    } catch (e) {
      onError((e as Error).message);
    }
    setStarting(false);
    onChange();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          {summary.last_inspected_at
            ? `Last inspected ${fmt.dateTime(summary.last_inspected_at)} via Google URL Inspection.`
            : "Checks each page from your sitemaps and search results with Google URL Inspection."}
        </p>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <Button onClick={start} disabled={running || starting || quotaLeft === 0}>
            {running ? "Inspecting…" : summary.inspected ? "Inspect more pages" : "Inspect pages"}
          </Button>
          <span className="text-xs text-muted">
            {fmt.int(quotaLeft)} of {fmt.int(summary.daily_limit)} inspections left today
          </span>
        </div>
      </div>

      <RunStatus summary={summary} pending={pending} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Indexed" value={summary.indexed} tone="positive" />
        <Stat label="Not indexed" value={summary.not_indexed} tone="negative" />
        <Stat label="Waiting to be inspected" value={pending} />
        <Stat label="Pages found" value={summary.known} hint="From sitemaps + search results" />
      </div>

      {summary.reasons.length > 0 && <VerdictTotals rows={summary.reasons} />}

      <Card className="overflow-hidden">
        <div className="px-4 pt-4 pb-3">
          <h2 className="text-sm font-medium">Why pages aren&apos;t indexed</h2>
          <p className="mt-0.5 text-xs text-muted">
            Based on the {fmt.int(summary.inspected)} pages inspected so far, worth-fixing first. Search Console&apos;s
            own report can include URLs we haven&apos;t found — upload its export for the full picture.
          </p>
        </div>
        {summary.reasons.length === 0 ? (
          <p className="border-t border-border px-4 py-6 text-sm text-muted">
            {summary.inspected ? "Every inspected page is indexed. 🎉" : "Run an inspection to see why pages aren't indexed."}
          </p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {summary.reasons.map((r) => (
              <InspectedReason key={r.reason} propertyId={propertyId} row={r} />
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
  if (run.status === "failed" && run.error !== "Interrupted by a server restart") {
    return <Banner tone="error">Last inspection failed: {run.error}</Banner>;
  }
  if (pending > 0) {
    return (
      <Card className="p-4 text-sm text-muted">
        {fmt.int(pending)} pages still waiting. Google allows {fmt.int(summary.daily_limit)} inspections per property per
        day — click Inspect more pages to continue (tomorrow if today&apos;s quota is used).
      </Card>
    );
  }
  return null;
}

function InspectedReason({ propertyId, row }: { propertyId: number; row: IndexingSummary["reasons"][number] }) {
  const [items, setItems] = useState<InspectedPage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMore = async (offset: number) => {
    setLoading(true);
    try {
      const res = await api.inspectedPages(propertyId, row.reason, PAGE_SIZE, offset);
      setItems((prev) => (offset === 0 ? res.items : [...prev, ...res.items]));
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    setLoading(false);
  };

  return (
    <ExpandableRow
      title={row.reason}
      verdict={row.advice.verdict}
      pages={row.pages}
      onOpen={() => items.length === 0 && loadMore(0)}
    >
      <AdviceBox advice={row.advice} inSitemap={row.in_sitemap} />
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
                    <a href={p.url} target="_blank" rel="noreferrer" title={p.url} className="truncate hover:underline">
                      {stripHost(p.url)}
                    </a>
                    {p.in_sitemap &&
                      (row.advice.sitemap_cleanup ? (
                        <span className="shrink-0 rounded-full bg-negative/15 px-2 py-0.5 text-negative">
                          remove from sitemap
                        </span>
                      ) : (
                        <Badge>sitemap</Badge>
                      ))}
                  </div>
                </td>
                <td
                  className="hidden max-w-0 truncate px-2 py-2 text-muted md:table-cell"
                  title={p.google_canonical ?? ""}
                >
                  {p.google_canonical && p.google_canonical !== p.url ? stripHost(p.google_canonical) : "—"}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right text-muted tabular-nums">
                  {p.last_crawl_time ? fmt.date(p.last_crawl_time.slice(0, 10)) : "Never"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ListFooter shown={items.length} total={total} loading={loading} onMore={() => loadMore(items.length)} />
    </ExpandableRow>
  );
}

function ListFooter({ shown, total, loading, onMore }: { shown: number; total: number; loading: boolean; onMore: () => void }) {
  return (
    <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
      <span>{loading && shown === 0 ? "Loading…" : `Showing ${fmt.int(shown)} of ${fmt.int(total)}`}</span>
      {shown < total && (
        <Button variant="secondary" disabled={loading} onClick={onMore}>
          {loading ? "Loading…" : "Show more"}
        </Button>
      )}
    </div>
  );
}

// ---------- Search Console export ----------

function ExportPanel({
  propertyId,
  exported,
  onChange,
}: {
  propertyId: number;
  exported: IndexingExport | null;
  onChange: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const res = await api.uploadIndexingExport(propertyId, file);
      setMessage({
        tone: "success",
        text:
          res.kind === "overview"
            ? `Imported ${res.reasons} reasons from ${res.filename}.`
            : `Imported ${fmt.int(res.urls)} example pages for “${res.issue}”.`,
      });
      onChange();
    } catch (e) {
      setMessage({ tone: "error", text: (e as Error).message });
    }
    setUploading(false);
    if (input.current) input.current.value = "";
  };

  return (
    <div className="space-y-6">
      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-sm">
          <p className="font-medium">Upload from Search Console</p>
          <p className="mt-0.5 text-muted">
            Indexing → Pages → <b>Export</b> → Download CSV, then upload the ZIP here. For a reason&apos;s page list,
            open that reason in Search Console and export it too.
          </p>
        </div>
        <div className="shrink-0">
          <input
            ref={input}
            type="file"
            accept=".zip,.csv"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          <Button onClick={() => input.current?.click()} disabled={uploading}>
            {uploading ? "Uploading…" : "Upload export"}
          </Button>
        </div>
      </Card>

      {message && <Banner tone={message.tone}>{message.text}</Banner>}

      {!exported ? (
        <p className="text-sm text-muted">No export uploaded yet for this client.</p>
      ) : (
        <>
          <p className="text-xs text-muted">
            Showing {exported.filename}, uploaded {fmt.dateTime(exported.uploaded_at)}
            {exported.chart_date && ` · data as of ${fmt.date(exported.chart_date)}`}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Indexed" value={exported.indexed} tone="positive" />
            <Stat label="Not indexed" value={exported.not_indexed} tone="negative" />
          </div>
          {exported.reasons.length > 0 && <VerdictTotals rows={exported.reasons} />}
          <Card className="overflow-hidden">
            <h2 className="px-4 pt-4 pb-3 text-sm font-medium">Why pages aren&apos;t indexed</h2>
            {exported.reasons.length === 0 ? (
              <p className="border-t border-border px-4 py-6 text-sm text-muted">No reasons in this export. 🎉</p>
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {exported.reasons.map((r) => (
                  <ExportedReason key={r.reason} propertyId={propertyId} row={r} />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function ExportedReason({ propertyId, row }: { propertyId: number; row: ExportReason }) {
  const [items, setItems] = useState<{ url: string; last_crawled: string | null }[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const loadMore = async (offset: number) => {
    setLoading(true);
    try {
      const res = await api.exportPages(propertyId, row.reason, PAGE_SIZE, offset);
      setItems((prev) => (offset === 0 ? res.items : [...prev, ...res.items]));
      setTotal(res.total);
    } catch {
      // the advice is still useful without the list
    }
    setLoading(false);
  };

  const meta = [row.source, row.validation && `Validation: ${row.validation}`].filter(Boolean).join(" · ");

  return (
    <ExpandableRow
      title={row.reason}
      verdict={row.advice.verdict}
      pages={row.pages}
      meta={meta}
      onOpen={() => row.urls_uploaded > 0 && items.length === 0 && loadMore(0)}
    >
      <AdviceBox advice={row.advice} />
      {row.urls_uploaded === 0 ? (
        <p className="px-4 py-3 text-xs text-muted">
          To see which pages: open “{row.reason}” in Search Console, click Export → Download CSV, and upload that ZIP.
        </p>
      ) : (
        <>
          <div className="max-h-[480px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface text-muted">
                <tr className="border-b border-border">
                  <th className="px-4 py-2 text-left font-normal">URL</th>
                  <th className="px-4 py-2 text-right font-normal">Last crawled</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.url} className="border-b border-border last:border-0">
                    <td className="max-w-0 truncate px-4 py-2">
                      <a href={p.url} target="_blank" rel="noreferrer" title={p.url} className="hover:underline">
                        {stripHost(p.url)}
                      </a>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-right text-muted tabular-nums">
                      {p.last_crawled ? fmt.date(p.last_crawled) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ListFooter shown={items.length} total={total} loading={loading} onMore={() => loadMore(items.length)} />
        </>
      )}
    </ExpandableRow>
  );
}
