"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Banner, Button, Card } from "@/components/ui";
import { SyncControls } from "@/components/sync-controls";
import { useSync } from "@/components/use-sync";
import { api, fmt, propertyLabel, type GscStatus, type Property, type SyncRun } from "@/lib/api";

// ---------- data status ----------

type StatusKey = "current" | "behind" | "none" | "failed" | "syncing";

const STATUS_STYLE: Record<StatusKey, { dot: string; text: string }> = {
  current: { dot: "bg-positive", text: "text-positive" },
  behind: { dot: "bg-warning", text: "text-warning" },
  none: { dot: "border border-muted", text: "text-muted" },
  failed: { dot: "bg-negative", text: "text-negative" },
  syncing: { dot: "bg-accent animate-pulse", text: "text-accent" },
};

const DATA_LAG_DAYS = 3; // Search Console finalises a day ~3 days later
const DAY_MS = 86_400_000;

/** Where a property's search data stands: syncing, failed, missing, current or N days behind. */
function dataStatus(p: Property, run: SyncRun | null = p.latest_run): { key: StatusKey; label: string } {
  if (run?.status === "running") return { key: "syncing", label: "Syncing…" };
  if (run?.status === "failed") return { key: "failed", label: "Sync failed" };
  if (!p.data_end) return { key: "none", label: "No data yet" };
  const newest = Date.now() - DATA_LAG_DAYS * DAY_MS;
  const behind = Math.floor((newest - new Date(p.data_end + "T00:00:00").getTime()) / DAY_MS);
  if (behind <= 1) return { key: "current", label: "Up to date" };
  return { key: "behind", label: `${behind} days behind` };
}

// ---------- brands ----------

type Brand = { key: string; properties: Property[]; main: Property };

/** "sc-domain:example.com", "https://www.example.com/" and "http://example.com/blog/" → "example.com". */
function brandKey(siteUrl: string) {
  return propertyLabel(siteUrl).name.split("/")[0].replace(/^www\./, "").toLowerCase();
}

/** One brand per site; its main property is the one with the newest data (a Domain property on ties). */
function groupBrands(properties: Property[]): Brand[] {
  const byKey = new Map<string, Property[]>();
  for (const p of properties) byKey.set(brandKey(p.site_url), [...(byKey.get(brandKey(p.site_url)) ?? []), p]);
  return [...byKey.entries()]
    .map(([key, props]) => {
      const ranked = [...props].sort(
        (a, b) =>
          (b.data_end ?? "").localeCompare(a.data_end ?? "") ||
          Number(b.site_url.startsWith("sc-domain:")) - Number(a.site_url.startsWith("sc-domain:")),
      );
      return { key, properties: ranked, main: ranked[0] };
    })
    .sort((a, b) => a.key.localeCompare(b.key));
}

const FILTERS: { key: StatusKey | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "current", label: "Up to date" },
  { key: "behind", label: "Behind" },
  { key: "none", label: "No data" },
  { key: "failed", label: "Sync failed" },
  { key: "syncing", label: "Syncing" },
];

// ---------- page ----------

export function IntegrationsView() {
  const params = useSearchParams();
  const [status, setStatus] = useState<GscStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [version, setVersion] = useState(0);
  const load = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;
    api
      .status()
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(`Can't reach the backend (${e.message}). Is Docker running?`);
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  const result = params.get("gsc");
  const properties = useMemo(() => status?.connections.flatMap((c) => c.properties) ?? [], [status]);

  return (
    <div className="space-y-6">
      {result === "connected" && (
        <Banner tone="success">
          Connected {params.get("email")} · found {params.get("properties")} Search Console properties. Sync a
          client to pull its data.
        </Banner>
      )}
      {result === "error" && <Banner tone="error">Couldn&apos;t connect Google: {params.get("reason")}</Banner>}
      {error && <Banner tone="error">{error}</Banner>}

      {status && <Clients properties={properties} onChange={load} />}
      {status && <Accounts status={status} onChange={load} onError={setError} />}
    </div>
  );
}

function Clients({ properties, onChange }: { properties: Property[]; onChange: () => void }) {
  const [filter, setFilter] = useState<StatusKey | "all">("all");
  const [search, setSearch] = useState("");
  const brands = useMemo(() => groupBrands(properties), [properties]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: brands.length };
    for (const b of brands) c[dataStatus(b.main).key] = (c[dataStatus(b.main).key] ?? 0) + 1;
    return c;
  }, [brands]);

  const shown = brands.filter(
    (b) =>
      (filter === "all" || dataStatus(b.main).key === filter) &&
      (!search || b.properties.some((p) => p.site_url.toLowerCase().includes(search.trim().toLowerCase()))),
  );

  if (brands.length === 0) {
    return (
      <Card className="p-6 text-sm text-muted">
        No clients yet. Connect a Google account below to list every site it can see in Search Console.
      </Card>
    );
  }

  return (
    <Card className="@container overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5 pb-4">
        <div>
          <h2 className="text-sm font-medium">Clients</h2>
          <p className="mt-0.5 text-xs text-muted">
            {brands.length} brands · {properties.length} Search Console properties
          </p>
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search clients"
          aria-label="Search clients"
          className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm sm:w-56"
        />
      </div>

      <div className="flex flex-wrap gap-2 px-5 pb-4" role="tablist" aria-label="Filter by data status">
        {FILTERS.filter((f) => f.key === "all" || counts[f.key]).map((f) => (
          <button
            key={f.key}
            role="tab"
            aria-selected={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
              filter === f.key ? "border-accent bg-accent-soft font-medium text-accent" : "border-border text-muted hover:text-foreground"
            }`}
          >
            {f.key !== "all" && <span className={`h-2 w-2 rounded-full ${STATUS_STYLE[f.key].dot}`} aria-hidden />}
            {f.label}
            <span className="tabular-nums">{counts[f.key] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="hidden grid-cols-[minmax(11rem,1fr)_11rem_10rem_17rem] gap-4 border-y border-border px-5 py-2 text-xs text-muted @4xl:grid">
        <span>Client</span>
        <span>Search data</span>
        <span>Indexing data</span>
        <span className="text-right">Sync</span>
      </div>
      {shown.length === 0 ? (
        <p className="border-t border-border px-5 py-6 text-sm text-muted @4xl:border-t-0">No clients match.</p>
      ) : (
        <ul className="divide-y divide-border border-t border-border @4xl:border-t-0">
          {shown.map((b) => (
            <BrandRow key={b.key} brand={b} onChange={onChange} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function BrandRow({ brand, onChange }: { brand: Brand; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const { main } = brand;
  const sync = useSync(main, onChange);
  const s = dataStatus(main, sync.run);
  const { kind } = propertyLabel(main.site_url);
  const more = brand.properties.length - 1;

  return (
    <li>
      <div className="grid gap-3 px-5 py-4 @4xl:grid-cols-[minmax(11rem,1fr)_11rem_10rem_17rem] @4xl:items-center @4xl:gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_STYLE[s.key].dot}`} aria-hidden />
            {main.data_end ? (
              <Link href={`/gsc/${main.id}`} className="truncate font-medium hover:text-accent hover:underline">
                {brand.key}
              </Link>
            ) : (
              <span className="truncate font-medium">{brand.key}</span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 pl-[18px] text-xs text-muted">
            <Badge>{kind}</Badge>
            {more > 0 && (
              <button
                onClick={() => setOpen(!open)}
                aria-expanded={open}
                className="hover:text-foreground"
              >
                {open ? "▾" : "▸"} {more} more {more === 1 ? "property" : "properties"}
              </button>
            )}
          </div>
        </div>

        <SearchData property={main} status={s} run={sync.run} />
        <IndexingData property={main} />

        <div className="flex flex-wrap items-center gap-2 @4xl:justify-end">
          <SyncControls property={main} running={sync.running} start={sync.start} />
          {main.data_end ? (
            <Link href={`/gsc/${main.id}`} className="px-1 text-sm text-accent hover:underline">
              Open
            </Link>
          ) : (
            <span className="invisible hidden px-1 text-sm @4xl:inline" aria-hidden>
              Open
            </span>
          )}
        </div>
        {sync.error && <p className="text-xs text-negative @4xl:col-span-4">{sync.error}</p>}
      </div>

      {open && (
        <ul className="divide-y divide-border border-t border-border bg-background/50">
          {brand.properties.map((p) => (
            <PropertyRow key={p.id} property={p} isMain={p.id === main.id} onChange={onChange} />
          ))}
        </ul>
      )}
    </li>
  );
}

function SearchData({ property, status, run }: { property: Property; status: ReturnType<typeof dataStatus>; run: SyncRun | null }) {
  let detail = "Run a sync to pull up to 16 months.";
  if (status.key === "syncing" && run && run.chunks_total > 1) {
    detail = `Month ${Math.min(run.chunks_done + 1, run.chunks_total)} of ${run.chunks_total} · newest first`;
  } else if (status.key === "syncing") {
    detail = "Newest data first — you can keep working.";
  } else if (status.key === "failed") {
    detail = run?.error ?? "Try syncing again.";
  } else if (property.data_start && property.data_end) {
    detail = `${fmt.date(property.data_start)} – ${fmt.date(property.data_end)}`;
  }
  return (
    <div className="min-w-0 pl-[18px] text-sm @4xl:pl-0">
      <span className="text-xs text-muted @4xl:hidden">Search data: </span>
      <span className={`font-medium ${STATUS_STYLE[status.key].text}`}>{status.label}</span>
      <p className="truncate text-xs text-muted" title={detail}>
        {detail}
      </p>
    </div>
  );
}

function IndexingData({ property }: { property: Property }) {
  const parts = [
    property.pages_inspected > 0 && `${fmt.int(property.pages_inspected)} pages inspected`,
    property.export_uploaded_at && `Export ${fmt.date(property.export_uploaded_at.slice(0, 10))}`,
  ].filter(Boolean);
  return (
    <div className="min-w-0 pl-[18px] text-sm @4xl:pl-0">
      <span className="text-xs text-muted @4xl:hidden">Indexing data: </span>
      {parts.length ? (
        <Link href={`/gsc/${property.id}/indexing`} className="hover:text-accent hover:underline">
          {parts.join(" · ")}
        </Link>
      ) : (
        <span className="text-muted">None yet</span>
      )}
    </div>
  );
}

function PropertyRow({ property, isMain, onChange }: { property: Property; isMain: boolean; onChange: () => void }) {
  const sync = useSync(property, onChange);
  const s = dataStatus(property, sync.run);
  const { name, kind } = propertyLabel(property.site_url);

  return (
    <li className="flex flex-col gap-2 py-3 pr-5 pl-[38px] sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          {/* full address: a brand can have both http:// and https:// properties */}
          <span className="truncate">{kind === "Domain" ? name : property.site_url}</span>
          <Badge>{kind}</Badge>
          {isMain && <span className="text-xs text-muted">shown above</span>}
        </div>
        <p className="mt-0.5 text-xs">
          <span className={STATUS_STYLE[s.key].text}>{s.label}</span>
          {property.data_start && property.data_end && (
            <span className="text-muted">
              {" "}
              · {fmt.date(property.data_start)} – {fmt.date(property.data_end)}
            </span>
          )}
        </p>
        {sync.error && <p className="mt-0.5 text-xs text-negative">{sync.error}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <SyncControls property={property} running={sync.running} start={sync.start} />
        <Link href={`/gsc/${property.id}`} className="px-1 text-sm text-accent hover:underline">
          Performance
        </Link>
        <Link href={`/gsc/${property.id}/indexing`} className="px-1 text-sm text-accent hover:underline">
          Indexing
        </Link>
      </div>
    </li>
  );
}

// ---------- connected accounts ----------

function Accounts({ status, onChange, onError }: { status: GscStatus; onChange: () => void; onError: (e: string) => void }) {
  return (
    <Card>
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <GscIcon />
          <div>
            <h2 className="text-sm font-medium">Google Search Console</h2>
            <p className="text-sm text-muted">Read-only access to clicks, impressions, rankings and indexing.</p>
          </div>
        </div>
        <a
          href={status.configured ? api.connectUrl : undefined}
          aria-disabled={!status.configured}
          className={`inline-flex shrink-0 items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium ${
            status.connections.length
              ? "border border-border bg-surface hover:bg-accent-soft"
              : "bg-accent text-white hover:opacity-90"
          } ${status.configured ? "" : "pointer-events-none opacity-50"}`}
        >
          {status.connections.length ? "Connect another account" : "Connect Google account"}
        </a>
      </div>

      {!status.configured && (
        <div className="border-t border-border px-5 py-4 text-sm text-muted">
          Google sign-in isn&apos;t set up yet. Add <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code>{" "}
          to <code>.env</code> (see <code>docs/gsc-setup.md</code>), then restart the backend.
        </div>
      )}

      {status.connections.map((conn) => (
        <div
          key={conn.id}
          className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3"
        >
          <div className="text-sm">
            <span className="font-medium">{conn.email}</span>
            <span className="text-muted"> · {conn.properties.length} properties</span>
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={async () => {
                await api.refreshProperties(conn.id).catch((e) => onError(e.message));
                onChange();
              }}
            >
              Refresh client list
            </Button>
            <Button
              variant="danger"
              onClick={async () => {
                if (!confirm(`Disconnect ${conn.email}? All data synced for its clients will be deleted.`)) return;
                await api.disconnect(conn.id).catch((e) => onError(e.message));
                onChange();
              }}
            >
              Disconnect
            </Button>
          </div>
        </div>
      ))}
    </Card>
  );
}

function GscIcon() {
  return (
    <svg viewBox="0 0 24 24" className="mt-0.5 h-8 w-8 shrink-0 text-accent" aria-hidden>
      <rect x="2" y="3" width="20" height="18" rx="3" fill="currentColor" opacity="0.15" />
      <path
        d="M6 16l4-4 3 3 5-6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
