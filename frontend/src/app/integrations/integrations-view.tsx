"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Banner, Button, Card } from "@/components/ui";
import { useSync } from "@/components/use-sync";
import { api, fmt, propertyLabel, type GscStatus, type Property } from "@/lib/api";

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

  return (
    <div className="space-y-4">
      {result === "connected" && (
        <Banner tone="success">
          Connected {params.get("email")} · found {params.get("properties")} Search Console
          properties. Run a sync to pull data.
        </Banner>
      )}
      {result === "error" && (
        <Banner tone="error">Couldn&apos;t connect Google: {params.get("reason")}</Banner>
      )}
      {error && <Banner tone="error">{error}</Banner>}

      <Card>
        <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <GscIcon />
            <div>
              <h2 className="font-medium">Google Search Console</h2>
              <p className="text-sm text-muted">
                Clicks, impressions, CTR and rankings by query and page.
              </p>
            </div>
          </div>
          {status && (
            <a
              href={status.configured ? api.connectUrl : undefined}
              aria-disabled={!status.configured}
              className={`inline-flex shrink-0 items-center justify-center rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 ${status.configured ? "" : "pointer-events-none opacity-50"}`}
            >
              {status.connections.length ? "Connect another account" : "Connect"}
            </a>
          )}
        </div>

        {status && !status.configured && (
          <div className="border-t border-border px-5 py-4 text-sm text-muted">
            Google OAuth isn&apos;t configured yet. Add <code>GOOGLE_CLIENT_ID</code> and{" "}
            <code>GOOGLE_CLIENT_SECRET</code> to <code>.env</code> (see{" "}
            <code>docs/gsc-setup.md</code>), then restart the backend.
          </div>
        )}

        {status?.connections.map((conn) => (
          <div key={conn.id} className="border-t border-border">
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
              <div className="text-sm">
                <span className="font-medium">{conn.email}</span>
                <span className="text-muted"> · {conn.properties.length} properties</span>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  onClick={async () => {
                    await api.refreshProperties(conn.id).catch((e) => setError(e.message));
                    load();
                  }}
                >
                  Refresh list
                </Button>
                <Button
                  variant="danger"
                  onClick={async () => {
                    if (!confirm(`Disconnect ${conn.email}? Synced data will be deleted.`)) return;
                    await api.disconnect(conn.id).catch((e) => setError(e.message));
                    load();
                  }}
                >
                  Disconnect
                </Button>
              </div>
            </div>
            {conn.properties.length === 0 ? (
              <p className="px-5 pb-4 text-sm text-muted">
                No Search Console properties found for this account.
              </p>
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {conn.properties.map((p) => (
                  <PropertyRow key={p.id} property={p} onChange={load} />
                ))}
              </ul>
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}

function PropertyRow({ property, onChange }: { property: Property; onChange: () => void }) {
  const { run, running, error, start } = useSync(property, onChange);
  const { name, kind } = propertyLabel(property.site_url);

  return (
    <li className="flex flex-col gap-3 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {property.last_synced_at ? (
            <Link
              href={`/gsc/${property.id}`}
              className="truncate text-sm font-medium text-accent hover:underline"
            >
              {name}
            </Link>
          ) : (
            <span className="truncate text-sm font-medium">{name}</span>
          )}
          <Badge>{kind}</Badge>
        </div>
        <p className="mt-0.5 text-xs text-muted">
          {running
            ? "Syncing… this can take a minute for large sites."
            : run?.status === "failed"
              ? `Last sync failed: ${run.error}`
              : property.last_synced_at
                ? `Synced ${fmt.dateTime(property.last_synced_at)} · ${fmt.int(run?.rows_written ?? 0)} rows`
                : "Not synced yet"}
        </p>
        {error && <p className="mt-0.5 text-xs text-negative">{error}</p>}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button variant="secondary" disabled={running} onClick={() => start(90)}>
          {running ? "Syncing…" : property.last_synced_at ? "Re-sync 90 days" : "Sync 90 days"}
        </Button>
        {property.last_synced_at && (
          <Link
            href={`/gsc/${property.id}`}
            className="inline-flex items-center rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            Open
          </Link>
        )}
      </div>
    </li>
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
