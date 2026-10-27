export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SyncRun = {
  id: number;
  status: "running" | "success" | "failed";
  start_date: string;
  end_date: string;
  rows_written: number;
  chunks_total: number;
  chunks_done: number;
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
  data_start: string | null;
  data_end: string | null;
  pages_inspected: number;
  last_inspected_at: string | null;
  export_uploaded_at: string | null;
};

export type SyncRequest = { mode: "range"; days: number } | { mode: "latest" };

export type Compare = "previous" | "year";

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
  compare: Compare;
  compare_start: string;
  compare_end: string;
  totals: Totals;
  previous_totals: Totals | null;
  daily: (Totals & { date: string })[];
  previous_daily: (Totals & { date: string })[];
};

export type DimensionRow = Totals & {
  key: string;
  brand?: boolean | null;
  expected_ctr?: number | null; // pages: site's typical page CTR at this position
  low_ctr?: boolean | null;
};
export type TopPagesFilter = "all" | "low_ctr";

export type QuerySegment = "all" | "brand" | "non_brand";

export type BrandTerms = { terms: string[]; suggested: string[]; is_default: boolean };

export type SegmentTotals = { totals: Totals; previous: Totals | null; click_share: number };

export type Segments = {
  start_date: string;
  end_date: string;
  terms: string[];
  brand: SegmentTotals;
  non_brand: SegmentTotals;
  hidden_clicks: number;
  hidden_impressions: number;
  daily: {
    date: string;
    brand_clicks: number;
    non_brand_clicks: number;
    brand_impressions: number;
    non_brand_impressions: number;
  }[];
};

export type KeywordType =
  | "long_tail"
  | "question"
  | "buying"
  | "new"
  | "lost"
  | "rising"
  | "declining"
  | "low_ctr"
  | "zero_clicks"
  | "high_performance"
  | "competitor";

export type KeywordSort = "clicks" | "impressions" | "ctr" | "position" | "click_change" | "query";

export type KeywordRow = Totals & {
  query: string;
  position: number | null;
  prev_clicks: number | null;
  prev_impressions: number | null;
  prev_position: number | null;
  click_change: number;
  expected_ctr: number | null;
  brand: boolean;
  types: KeywordType[];
};

export type KeywordsResponse = {
  start_date: string;
  end_date: string;
  compare: Compare;
  compare_available: boolean;
  new_available: boolean;
  definitions: {
    long_tail_words: number;
    new_lookback_days: number;
    mover_min_clicks: number;
    mover_min_share: number;
    low_ctr_max_position: number;
    low_ctr_factor: number;
    min_impressions: number;
    high_performance_share: number;
  };
  counts: Record<"all" | KeywordType, number>;
  total: number;
  items: KeywordRow[];
};

export type KeywordQuery = {
  days: number;
  compare: Compare;
  segment: QuerySegment;
  types: KeywordType[];
  search: string;
  sort: KeywordSort;
  order: "asc" | "desc";
  limit: number;
  offset: number;
};

export type PageType = "home" | "collections" | "products" | "blogs" | "pages" | "other" | "shopping";
export type PageFilter =
  | "low_ctr"
  | "high_performance"
  | "rising"
  | "declining"
  | "new"
  | "lost"
  | "zero_clicks"
  | "striking";
export type PageSort = "clicks" | "impressions" | "ctr" | "position" | "click_change" | "page";

export type PageRow = {
  page: string;
  type: PageType;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number | null;
  prev_clicks: number | null;
  prev_impressions: number | null;
  prev_position: number | null;
  click_change: number;
  expected_ctr: number | null;
  flags: PageFilter[];
};

export type PageGroup = {
  type: PageType;
  pages: number;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number | null;
  prev_clicks: number | null;
  prev_impressions: number | null;
  prev_ctr: number | null;
  prev_position: number | null;
};

export type PageReport = {
  start_date: string;
  end_date: string;
  compare: Compare;
  compare_available: boolean;
  new_available: boolean;
  definitions: {
    new_lookback_days: number;
    mover_min_clicks: number;
    mover_min_share: number;
    low_ctr_max_position: number;
    low_ctr_factor: number;
    min_impressions: number;
    high_performance_share: number;
    striking_min_position: number;
    striking_max_position: number;
  };
  groups: PageGroup[];
  counts: Record<string, number>;
  total: number;
  items: PageRow[];
};

export type PageKeyword = {
  query: string;
  brand: boolean;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
  other_pages: number;
};

export type PageDetail = Omit<Summary, "site_url"> & {
  page: string;
  type: PageType;
  flags: PageFilter[];
  expected_ctr: number | null;
  keywords_available: boolean;
  keywords_fetched_at: string | null;
  keywords: PageKeyword[];
  inspection: {
    coverage_state: string | null;
    indexed: boolean;
    last_crawl_time: string | null;
    inspected_at: string | null;
    google_canonical: string | null;
    user_canonical: string | null;
    in_sitemap: boolean;
    advice: Advice | null;
  } | null;
  export_issues: { issue: string; uploaded_at: string; last_crawled: string | null; advice: Advice }[];
};

export type PageQuery = {
  days: number;
  compare: Compare;
  types: PageType[];
  filters: PageFilter[];
  search: string;
  sort: PageSort;
  order: "asc" | "desc";
  limit: number;
  offset: number;
};

export type StrikingRow = {
  query: string;
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
  other_pages: number;
  brand: boolean;
  target_ctr: number | null;
  potential: number | null;
};

export type StrikingSort = "potential" | "impressions" | "clicks" | "position";

export type StrikingResponse = {
  start_date: string;
  end_date: string;
  fetched_at: string;
  min_position: number;
  max_position: number;
  target_position: number;
  min_impressions: number;
  total: number;
  items: StrikingRow[];
};

export type CannibalRow = {
  query: string;
  brand: boolean;
  clicks: number;
  impressions: number;
  competing_pages: number;
  sitelinks_likely: boolean;
  pages: { page: string; clicks: number; impressions: number; position: number; share: number }[];
};

export type CannibalResponse = {
  start_date: string;
  end_date: string;
  fetched_at: string;
  min_share: number;
  min_impressions: number;
  total: number;
  items: CannibalRow[];
};

/** Page-level views pull keyword+page data live from Google; longer ranges would take minutes. */
export const OPPORTUNITY_MAX_DAYS = 90;

export type SeasonStatus = "in_season" | "coming_up" | "off_season";

type MonthlyRow = {
  query: string;
  brand: boolean;
  impressions: number[];
  total_impressions: number;
  total_clicks: number;
};

export type SeasonalRow = MonthlyRow & { peak_months: number[]; status: SeasonStatus };
export type SpikeRow = MonthlyRow & { spike_month: string; spike_impressions: number; share: number };

type MonthlyResponse = { months: string[]; available: boolean; min_impressions: number; total: number };
export type SeasonalResponse = MonthlyResponse & {
  repeating_months: string[];
  counts: Record<SeasonStatus, number>;
  items: SeasonalRow[];
};
export type SpikesResponse = MonthlyResponse & { items: SpikeRow[] };

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

export type Verdict = "fix" | "review" | "ignore";

export type Advice = {
  verdict: Verdict;
  summary: string;
  action: string;
  sitemap_cleanup: boolean;
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
  reasons: { reason: string; pages: number; in_sitemap: number; advice: Advice }[];
};

export type ExportReason = {
  reason: string;
  source: string | null;
  validation: string | null;
  pages: number;
  critical: boolean | null;
  advice: Advice;
  urls_uploaded: number;
  urls_uploaded_at: string | null;
};

export type IndexingExport = {
  id: number;
  filename: string;
  uploaded_at: string;
  chart_date: string | null;
  indexed: number | null;
  not_indexed: number | null;
  reasons: ExportReason[];
};

export type UploadResult = {
  kind: "overview" | "issue";
  filename: string;
  issue: string | null;
  reasons: number;
  urls: number;
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
  const isForm = init?.body instanceof FormData; // browser sets the multipart boundary itself
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: isForm ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
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
  sync: (id: number, body: SyncRequest) =>
    request<SyncRun>(`/api/gsc/properties/${id}/sync`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  summary: (id: number, days: number, compare: Compare = "previous") =>
    request<Summary>(`/api/gsc/properties/${id}/summary?days=${days}&compare=${compare}`),
  queries: (id: number, days: number, limit = 50, segment: QuerySegment = "all") =>
    request<DimensionRow[]>(
      `/api/gsc/properties/${id}/queries?days=${days}&limit=${limit}&segment=${segment}`,
    ),
  brandTerms: (id: number) => request<BrandTerms>(`/api/gsc/properties/${id}/brand-terms`),
  setBrandTerms: (id: number, terms: string[] | null) =>
    request<BrandTerms>(`/api/gsc/properties/${id}/brand-terms`, {
      method: "PUT",
      body: JSON.stringify({ terms }),
    }),
  segments: (id: number, days: number, compare: Compare = "previous") =>
    request<Segments>(`/api/gsc/properties/${id}/segments?days=${days}&compare=${compare}`),
  pages: (id: number, days: number, limit = 50, filter: TopPagesFilter = "all") =>
    request<DimensionRow[]>(`/api/gsc/properties/${id}/pages?days=${days}&limit=${limit}&filter=${filter}`),
  keywords: (id: number, q: KeywordQuery) => {
    const params = new URLSearchParams({
      days: String(q.days),
      compare: q.compare,
      segment: q.segment,
      sort: q.sort,
      order: q.order,
      limit: String(q.limit),
      offset: String(q.offset),
    });
    q.types.forEach((t) => params.append("types", t));
    if (q.search.trim()) params.set("search", q.search.trim());
    return request<KeywordsResponse>(`/api/gsc/properties/${id}/keywords?${params}`);
  },
  pageReport: (id: number, q: PageQuery) => {
    const params = new URLSearchParams({
      days: String(q.days),
      compare: q.compare,
      sort: q.sort,
      order: q.order,
      limit: String(q.limit),
      offset: String(q.offset),
    });
    q.types.forEach((t) => params.append("type", t));
    q.filters.forEach((f) => params.append("filter", f));
    if (q.search.trim()) params.set("search", q.search.trim());
    return request<PageReport>(`/api/gsc/properties/${id}/page-report?${params}`);
  },
  pageDetail: (id: number, url: string, days: number, compare: Compare) =>
    request<PageDetail>(
      `/api/gsc/properties/${id}/page-detail?${new URLSearchParams({ url, days: String(days), compare })}`,
    ),
  competitorTerms: (id: number) => request<{ terms: string[] }>(`/api/gsc/properties/${id}/competitor-terms`),
  setCompetitorTerms: (id: number, terms: string[]) =>
    request<{ terms: string[] }>(`/api/gsc/properties/${id}/competitor-terms`, {
      method: "PUT",
      body: JSON.stringify({ terms }),
    }),
  seasonal: (id: number, segment: QuerySegment, status: SeasonStatus | null, limit = 100, offset = 0) =>
    request<SeasonalResponse>(
      `/api/gsc/properties/${id}/keywords/seasonal?segment=${segment}${status ? `&status=${status}` : ""}&limit=${limit}&offset=${offset}`,
    ),
  spikes: (id: number, segment: QuerySegment, limit = 100, offset = 0) =>
    request<SpikesResponse>(`/api/gsc/properties/${id}/keywords/spikes?segment=${segment}&limit=${limit}&offset=${offset}`),
  strikingDistance: (id: number, days: number, segment: QuerySegment, sort: StrikingSort, limit = 100, offset = 0) =>
    request<StrikingResponse>(
      `/api/gsc/properties/${id}/opportunities/striking-distance?days=${days}&segment=${segment}&sort=${sort}&limit=${limit}&offset=${offset}`,
    ),
  cannibalisation: (id: number, days: number, segment: QuerySegment, limit = 100, offset = 0) =>
    request<CannibalResponse>(
      `/api/gsc/properties/${id}/opportunities/cannibalisation?days=${days}&segment=${segment}&limit=${limit}&offset=${offset}`,
    ),
  indexing: (id: number) => request<IndexingSummary>(`/api/gsc/properties/${id}/indexing`),
  startInspection: (id: number) =>
    request<InspectionRun>(`/api/gsc/properties/${id}/indexing`, { method: "POST" }),
  inspectedPages: (id: number, reason: string, limit = 100, offset = 0) =>
    request<{ total: number; items: InspectedPage[] }>(
      `/api/gsc/properties/${id}/indexing/pages?reason=${encodeURIComponent(reason)}&limit=${limit}&offset=${offset}`,
    ),
  indexingExport: (id: number) =>
    request<IndexingExport | null>(`/api/gsc/properties/${id}/indexing/export`),
  uploadIndexingExport: (id: number, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<UploadResult>(`/api/gsc/properties/${id}/indexing/uploads`, { method: "POST", body });
  },
  exportPages: (id: number, reason: string, limit = 100, offset = 0) =>
    request<{ total: number; uploaded_at: string | null; items: { url: string; last_crawled: string | null }[] }>(
      `/api/gsc/properties/${id}/indexing/export/pages?reason=${encodeURIComponent(reason)}&limit=${limit}&offset=${offset}`,
    ),
};

export const fmt = {
  int: (n: number) => n.toLocaleString("en-US"),
  pct: (n: number) => `${(n * 100).toFixed(2)}%`,
  pos: (n: number) => n.toFixed(1),
  /** "Oct 12", or "Jun 14, 2025" when not in the current year. */
  date: (iso: string) => {
    const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      ...(d.getFullYear() !== new Date().getFullYear() && { year: "numeric" }),
    });
  },
  month: (iso: string) =>
    new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-US", {
      month: "short",
      year: "2-digit",
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
