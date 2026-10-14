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
