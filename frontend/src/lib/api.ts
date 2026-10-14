export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SyncRun = {
  id: number;
  status: "running" | "success" | "failed";
  start_date: string;
  end_date: string;
  rows_written: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type Property = {
  id: number;
  site_url: string;
  permission_level: string;
  last_synced_at: string | null;
  latest_run: SyncRun | null;
};

export type Connection = {
  id: number;
  email: string;
  created_at: string;
  properties: Property[];
};

export type GscStatus = {
  configured: boolean;
  connections: Connection[];
};

export type Totals = {
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

export type Summary = {
  site_url: string;
  start_date: string;
  end_date: string;
  totals: Totals;
  previous_totals: Totals | null;
  daily: (Totals & { date: string })[];
};

export type DimensionRow = Totals & { key: string };

export type InspectionRun = {
  id: number;
  status: "running" | "success" | "partial" | "failed";
  urls_known: number;
  urls_queued: number;
  urls_inspected: number;
  urls_failed: number;
  quota_exhausted: boolean;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type IndexingSummary = {
  latest_run: InspectionRun | null;
  known: number;
  inspected: number;
  indexed: number;
  not_indexed: number;
  daily_limit: number;
  used_last_24h: number;
  last_inspected_at: string | null;
  reasons: { reason: string; pages: number }[];
};

export type InspectedPage = {
  url: string;
  coverage_state: string | null;
  verdict: string | null;
  indexing_state: string | null;
  robots_txt_state: string | null;
  page_fetch_state: string | null;
  google_canonical: string | null;
  user_canonical: string | null;
  last_crawl_time: string | null;
  inspected_at: string | null;
  in_sitemap: boolean;
  in_search: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  status: () => request<GscStatus>("/api/gsc/status"),
  connectUrl: `${API_URL}/api/gsc/oauth/start`,
  disconnect: (connectionId: number) =>
    request<void>(`/api/gsc/connections/${connectionId}`, { method: "DELETE" }),
  refreshProperties: (connectionId: number) =>
    request<Property[]>(`/api/gsc/connections/${connectionId}/refresh-properties`, {
      method: "POST",
    }),
  property: (id: number) => request<Property>(`/api/gsc/properties/${id}`),
  sync: (id: number, days: number) =>
    request<SyncRun>(`/api/gsc/properties/${id}/sync`, {
      method: "POST",
      body: JSON.stringify({ days }),
    }),
  summary: (id: number, days: number) =>
    request<Summary>(`/api/gsc/properties/${id}/summary?days=${days}`),
  queries: (id: number, days: number, limit = 50) =>
    request<DimensionRow[]>(`/api/gsc/properties/${id}/queries?days=${days}&limit=${limit}`),
  pages: (id: number, days: number, limit = 50) =>
    request<DimensionRow[]>(`/api/gsc/properties/${id}/pages?days=${days}&limit=${limit}`),
  indexing: (id: number) => request<IndexingSummary>(`/api/gsc/properties/${id}/indexing`),
  startInspection: (id: number) =>
    request<InspectionRun>(`/api/gsc/properties/${id}/indexing`, { method: "POST" }),
  inspectedPages: (id: number, reason: string, limit = 100, offset = 0) =>
    request<{ total: number; items: InspectedPage[] }>(
      `/api/gsc/properties/${id}/indexing/pages?reason=${encodeURIComponent(reason)}&limit=${limit}&offset=${offset}`,
    ),
};

export const fmt = {
  int: (n: number) => n.toLocaleString("en-US"),
  pct: (n: number) => `${(n * 100).toFixed(2)}%`,
  pos: (n: number) => n.toFixed(1),
  date: (iso: string) =>
    new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
  dateTime: (iso: string) =>
    new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }),
};

/** Human-readable label for a GSC property: "sc-domain:x.com" -> "x.com (Domain)". */
export function propertyLabel(siteUrl: string) {
  if (siteUrl.startsWith("sc-domain:")) {
    return { name: siteUrl.slice("sc-domain:".length), kind: "Domain" };
  }
  return { name: siteUrl.replace(/^https?:\/\//, "").replace(/\/$/, ""), kind: "URL prefix" };
}
