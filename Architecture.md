# Architecture — AI SEO Tool

_Last updated: 2026-10-27_

## 1. Overview

```
 Browser ──► Next.js frontend (:3000) ──fetch──► FastAPI backend (:8000) ──► Postgres (:5432)
                                                     │
                                                     ├─► Google OAuth 2.0
                                                     ├─► Search Console API (sites, searchAnalytics, sitemaps)
                                                     ├─► GA4 Admin API (accountSummaries, dataStreams) + Data API (runReport)
                                                     ├─► URL Inspection API
                                                     └─► Client sitemaps (HTTP)
```

Everything runs in **Docker Compose** (`docker-compose.yml`): `db`, `backend`, `frontend`.

| Layer | Tech | Folder |
|---|---|---|
| Frontend | Next.js 16 (App Router, `cacheComponents`), React 19, TypeScript, Tailwind v4, Recharts | `frontend/` |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 (sync), Alembic, httpx | `backend/` |
| Database | Postgres 16 | volume `postgres_data` |
| Tests | pytest against a separate `seo_tool_test` DB; Google APIs mocked | `backend/tests/` |

## 2. Backend layout

```
backend/app/
  main.py              app, CORS, routers, startup cleanup of interrupted jobs
  config.py            settings from env (.env)
  db.py                engine, SessionLocal, Base
  crypto.py            Fernet encrypt/decrypt for OAuth tokens
  models.py            all tables
  gsc/
    google_api.py      thin wrappers: OAuth, sites, searchAnalytics, sitemaps, URL Inspection, GA4 properties + sessions
    ga4.py             GA4 property list per connection, matching each Search Console site to one,
                       Google-organic landing pages (cached 1 h) joined to Search Console pages
    router.py          /api/gsc/... connections, OAuth, sync, performance reports
    sync.py            property discovery + performance sync job
    nightly.py         nightly "Latest days" sync loop for properties with data
    indexing.py        URL discovery (sitemaps + search pages) + inspection job
    indexing_router.py /api/gsc/properties/{id}/indexing/... inspection, export upload
    export_parser.py   Search Console Page-indexing export (ZIP/CSV) parser
    advice.py          reason → verdict (fix / review / ignore) + action
    brand.py           brand-term normalisation, suggestion from domain, SQL match condition
    brand_router.py    /api/gsc/properties/{id}/brand-terms, /segments
    keywords.py        keyword-type definitions, tagging SQL, cache build + filter/sort/page
    keywords_router.py /api/gsc/properties/{id}/keywords
    opportunities.py   live query+page pull + cache, striking distance, cannibalisation
    seasonal.py        monthly keyword series cache, seasonal + spike detection
    opportunities_router.py /api/gsc/properties/{id}/opportunities/{striking-distance,cannibalisation}
    pages.py           page types from URL, per-page flags, type totals (also backs Top pages / Low CTR)
    pages_router.py    /api/gsc/properties/{id}/page-report, /page-detail, /page-decay
    ga4_router.py      /api/gsc/properties/{id}/ga4-overview, /ai-traffic
```

## 3. Data model

| Table | Purpose |
|---|---|
| `oauth_states` | Short-lived CSRF state for the OAuth redirect (10 min, single use). |
| `google_connections` | Connected Google account; **encrypted** refresh + access tokens. |
| `gsc_properties` | Search Console properties per connection; `brand_terms` (text[], null = use domain suggestion); `competitor_terms` (text[]); `ga4_property_id` (linked GA4 property, `SET NULL` on delete) + `ga4_manual` (picked by the user). |
| `ga4_properties` | GA4 properties per connection: `property` ("properties/123"), name, account, web stream `website_url`. |
| `gsc_sync_runs` | Performance sync jobs (status, range, rows, chunk progress). |
| `gsc_daily_metrics` | Per-day totals (PK property+date). |
| `gsc_query_metrics`, `gsc_page_metrics` | Per-day per-query / per-page metrics; queries carry generated `query_norm`. |
| `gsc_inspection_runs` | URL inspection jobs (known / queued / inspected / failed, quota). |
| `gsc_url_inspections` | Latest inspection per URL (coverage state, canonicals, last crawl, in_sitemap / in_search). |
| `gsc_keyword_cache_entries` | One cached tagged keyword set per (property, window, comparison, look-back, brand terms) — max 8 per property. |
| `gsc_keyword_cache_rows` | **UNLOGGED** rows of a cached set: metrics, comparison metrics, typical CTR, brand flag, `t_<type>` flags. |
| `gsc_query_page_cache_entries` | Live query+page pull per (property, start, end); refreshed after a sync or after 24 h; max 3 per property. |
| `gsc_query_page_cache_rows` | **UNLOGGED** query, page, clicks, impressions, position (+ generated `query_norm`). |

UNLOGGED tables are emptied by Postgres after an unclean shutdown while their entry rows survive, so a cache entry with no rows is treated as missing and rebuilt.
| `gsc_monthly_keyword_cache` | Per property: full calendar months + JSONB `{keyword: {impressions[], clicks[]}}` for keywords with 1,000+ impressions; rebuilt after each sync (~5–15 s on a large site). |
| `gsc_indexing_exports` | Uploaded Search Console exports (`overview` or per-reason `issue`). |
| `gsc_indexing_export_reasons`, `gsc_indexing_export_urls` | Parsed rows of those uploads. |

Deleting a connection cascades to everything below it. Schema changes go through **Alembic** (`backend/alembic/versions/`).

## 4. Key flows

**OAuth connect** — `GET /api/gsc/oauth/start` stores a random state and redirects to Google (offline access, `webmasters.readonly`). Callback verifies state, exchanges the code, rejects grants without Search Console scope, encrypts tokens, fetches the email, discovers properties, redirects to `/integrations`.

**Performance sync** — `POST /properties/{id}/sync` with `{"mode": "range", "days": 90|180|486}` or `{"mode": "latest"}` creates a run and returns 202. The range ends 3 days ago (Google data lag); `latest` starts 3 days before the newest stored day (Google may revise recent days). A background task splits the range into **30-day chunks, newest first**; for each chunk it pulls `date`, `date+query`, `date+page` (paged by 25k rows), **replaces** that chunk and commits, updating `chunks_done/chunks_total`. Each of the three downloads asks for its own token, and `access_token_for` renews any token with under 10 minutes left (`TOKEN_MARGIN`), so a slow month can't outlive its token. An interrupted run keeps finished chunks; re-running replaces them (idempotent). Full 16 months on a large site: ~2.8M rows in ~12 min.

**GA4 link** — the OAuth callback and `POST /connections/{id}/refresh-properties` also call `ga4.refresh_properties` when the connection granted `analytics.readonly`: `accountSummaries` (paged) + one `dataStreams` call per property (8 threads; ~30 s for 60 properties) mirror `ga4_properties`, then `match_all` links every non-manual Search Console property by host (`site_host`: scheme, `www.`, path removed). Several candidates → `runReport` sessions for the last 28 days, highest wins, newest property id on a tie (unreadable = −1). `PUT /properties/{id}/ga4` with `{"ga4_property_id": n|null}` sets a manual link, `{"auto": true}` re-matches just that property. No website match → `by_name`: GA4 properties whose normalised name + account name contain the site's normalised host, else its brand term (`brand.suggest_terms`, 3+ letters).

**GA4 on pages** — `page-report` and `page-detail` call `ga4.organic_landing_pages` (one `runReport`: `hostName` × `landingPage`, metrics `sessions, keyEvents, ecommercePurchases, purchaseRevenue`, filter channel group = Organic Search AND source = google, `metricAggregations: TOTAL`, paged 100k rows; cached in-process for 1 h per GA4 property + range, so filters and sorting don't call GA4 again). `ga4.attach` joins by `page_key` (host without `www.`, unquoted path, no trailing slash) onto clean page rows; http/https duplicates get the numbers once. Site totals use GA4's TOTAL (sessions don't add up exactly across landing pages); `unmatched_sessions` = total − matched pages. A GA4 error returns `ga4_error` and the Search Console report still works. `clean_path` strips Shopify's pixel-sandbox prefix (`/web-pixels@…/sandbox/modern`) so those sessions count for the real page.

**GA4 tab** — `GET /properties/{id}/ga4-overview` (Period): `ga4.overview` makes 4 `runReport` calls (cached 1 h): `date` with both ranges + `metricAggregations: TOTAL` (window totals — users don't add up across days — and daily sessions), `sessionDefaultChannelGroup` with both ranges (channels: per-row values equal GA4's; their sum exceeds the total by ~1% as GA4 sessions are estimates), top 100 `hostName`×`landingPage` (body `limit` → no paging; pixel-sandbox copies merged), `deviceCategory`. `ga4_run_report` returns `range_totals` keyed by range name ("now" / "before").

**AI traffic** — `GET /properties/{id}/ai-traffic`: one `runReport` (`date`×`sessionSource`×`hostName`×`landingPage`, both ranges) filtered to channel "AI Assistant" OR source matching `ga4.AI_SOURCES`, plus one all-sessions call for the share. `ga4.assistant()` names the source (first word match: chatgpt/openai → ChatGPT, gemini/bard → Gemini…, `cgpt_…` → ChatGPT ads, else Other AI); the router sums totals (ads excluded), per assistant, per day and per landing page. `/status` returns `ga4_properties` and each property's link.

**Clients list** — `GET /api/gsc/status` returns every property with its data range, latest sync run and indexing counts (`pages_inspected`, `last_inspected_at`, `export_uploaded_at` of the newest overview export). The frontend groups properties into brands by host (scheme, `www.` and path removed) and derives the status: data ending ≤ 1 day after the expected newest day (today − 3) is up to date.

**Date range & comparisons** — every report endpoint takes the same `Period` dependency (`router.period_params`): `days` (ending at the latest synced day) **or** `start`+`end` (custom, ≤ 486 days), and `compare=previous|year|custom|none` (+ `compare_start`/`compare_end` for custom). *previous* = the equal-length window before; *year* = same window 364 days earlier (weekday-aligned); *none* = no comparison window at all. Invalid combinations return 422 with a plain message. If stored data doesn't reach back to the start of the comparison window, comparison values are `null` (no partial comparisons); `/queries` and `/pages` rows carry `prev_clicks` the same way. Live views (`opportunities/*`, page keywords) reject ranges over 90 days. Frontend: `components/range-controls.tsx` holds one shared range (`useDateRange`, `useSyncExternalStore` + `sessionStorage`, so each visit starts at the 28-day default) and the `DateBar`; `rangeParams()` in `lib/api.ts` turns it into query parameters for every call.

**Indexing inspection** — `POST /properties/{id}/indexing` (user-triggered):
1. Discover URLs: sitemaps from the Sitemaps API (follows indexes, gzip, size/count caps) + distinct clean pages (no `?`/`#`) from performance data; scoped to the property; prune URLs no longer found.
2. Budget = 2,000 − inspections in the last 24 h.
3. Queue: never-inspected first (sitemap before search-only), then results older than 7 days.
4. Inspect with 10 threads; access token refreshed during long runs; 429 stops the run as `partial`.

**Export upload** — `POST /properties/{id}/indexing/uploads` (multipart). Files recognised by header, not name. Real exports have a `Property,Value` header row and no site in `Metadata.csv`, so the site comes from the URLs' host or Google's file name; it must be the property's domain or a subdomain of it. Reason names are normalised for quotes, dashes and British spellings ("Alternative page…", "unauthorised").

**Brand vs non-brand** — a query is brand if `query_norm` (a Postgres **generated column**: `lower(query)` with spaces/punctuation removed) contains any brand term normalised the same way (so "acme co" = "acmeco"). Matching is a plain `LIKE` at read time, so editing terms takes effect immediately; 16 months (~2.4M keyword rows) takes ~1.5 s, 28 days ~0.2 s. `/segments` returns brand / non-brand totals (current + previous period), click share, a daily split, and the clicks hidden by Google (site total − query-level total). `/queries?segment=brand|non_brand` filters top queries.

**Keyword explorer** — `GET /properties/{id}/keywords?days&compare&segment&types&search&sort&order&limit&offset`. One SQL statement aggregates queries for the current window, the comparison window and a 90-day "new" look-back (each only if stored history covers it), joins them, computes the site's typical CTR per rounded position separately for brand / non-brand (clicks ÷ impressions of keywords with ≥ 50 impressions, ≥ 5 keywords per position), a running click total for the 80% high-performance cut, and splits each keyword into words once (`regexp_split_to_array`) so question / buying matching is word-list overlap (`&&`) plus a few `LIKE` phrases. The result is inserted into the cache tables (JIT off, larger `work_mem` for that statement); filters/sort/paging then read the cache (~0.1 s). Cache entries are rebuilt when older than `last_synced_at`; brand-term changes produce a new key; `run_sync` pre-builds the default 28-day set.

**Striking distance / cannibalisation** — `GET /properties/{id}/opportunities/{striking-distance|cannibalisation}?days≤90`. The first request for a range pulls `query+page` from Search Analytics (28 d ≈ 68k rows in ~6 s, 3 m ≈ 154k rows in ~30 s on a large site), stores it, and runs `ANALYZE` (without stats the planner chose nested loops taking minutes). Per-keyword totals and the main page are computed with **window functions over a single scan** — joins between per-keyword CTEs got row estimates of ~1 and nested-looped for minutes on real data. The site's typical CTR at position 3 is computed in a separate tiny query and passed in as parameters for the same reason. URLs containing `?` are excluded.

**Pages / Low CTR pages** — `pages.page_rows` aggregates pages for the window, the comparison window and the 90-day look-back in one SQL statement (like the keyword explorer, on `gsc_page_metrics`), learns the site's typical page CTR per rounded position (pages with ≥ 50 impressions, ≥ 5 pages per position, no `?` URLs), then tags page type and flags in Python. `GET /properties/{id}/page-report?days&compare&type&filter&search&sort&order&limit&offset` returns type totals, chip counts and a page of rows; `GET /properties/{id}/pages?filter=all|low_ctr` (Top pages on Performance) uses the same rows, `low_ctr` sorted by impressions × (typical − actual CTR). Pages per property are thousands, so it's a live query with no cache (~0.3 s up to 16 months on a large site). `GET /properties/{id}/page-detail?url&days&compare` returns that page's totals and daily series (same shape as `/summary`, so the chart and KPI cards are reused), its keywords from the query+page cache (≤ 90 days) with how many other pages showed for each search, its URL inspection and any uploaded reason lists containing it.

**Content decay** — `GET /properties/{id}/page-decay?type` aggregates `gsc_page_metrics` per page and calendar month over the full months of stored history (`seasonal.full_month_range`, `work_mem` raised so the grouping doesn't spill), then applies the rule and cause classification in Python (`pages.decaying_pages`, `pages.decay_cause`). ~0.8 s on a large site with 15 months; no cache.

**Cache builds are serialised per property** — `cached_entry` (query+page pull) and the keyword set build take a Postgres advisory transaction lock first, so two requests opening the same range at once (React dev mode fires each twice) don't both pull from Google; the second waits and reuses the first one's result.

**Seasonal / spikes** — `GET /properties/{id}/keywords/{seasonal|spikes}` read the monthly cache and classify in Python (fast: ~2k keywords × ~15 months). `run_sync` rebuilds the cache after the keyword cache. Competitor terms (`/competitor-terms`) feed a `t_competitor` flag in the keyword explorer and its cache key.

**Advice** — `advice.py` normalises Google's wording (quotes, dashes, case) and maps each reason to a verdict + action; reasons sorted worth-fixing first.

## 5. Background jobs
FastAPI `BackgroundTasks` run inside the API process. **Nightly sync:** `lifespan` starts `nightly.scheduler()`, which every 10 minutes syncs (sequentially, `run_sync` in a thread) each property that has stored data, nothing running, and no run started since the last `NIGHTLY_SYNC_TIME` in `TIMEZONE` (default 02:00 Asia/Kolkata). No extra table: due-ness comes from `gsc_sync_runs.started_at`, so missed nights catch up and a failed run waits for the next night. `NIGHTLY_SYNC_ENABLED=false` turns it off (tests do). On startup, any run still marked `running` is set to `failed: Interrupted by a server restart`.
**Known limitation:** a running job blocks `uvicorn --reload` until it finishes (dev only). Planned: move jobs to a separate worker (see Task.md).

## 6. Frontend layout

```
frontend/src/
  app/layout.tsx                     sidebar shell
  app/integrations/                  connect Google, list properties, sync
  app/gsc/[propertyId]/              Performance dashboard
  app/gsc/[propertyId]/keywords/     Keywords explorer (filter chips, search, sort, paging)
  app/gsc/[propertyId]/pages/        Pages explorer (page-type cards, filter chips, search, sort, paging)
  app/gsc/[propertyId]/pages/detail/ Page detail (?url=…): KPIs, chart, keywords, indexing
  app/gsc/[propertyId]/pages/decay-panel.tsx  Content decay view (month bars, cause + advice)
  app/gsc/[propertyId]/indexing/     Indexing (inspected / export, advice)
  app/gsc/[propertyId]/ga4/          GA4 tab (all channels: KPIs, daily chart, channels, devices, landing pages)
  app/gsc/[propertyId]/ai/           AI traffic tab (assistants, daily chart, landing pages)
  components/ga4-ui.tsx              MetricCard (value + change), SessionsChart, change()
  components/ui.tsx                  Card, Button, Banner, Badge
  components/property-tabs.tsx       Performance | Keywords | Pages | Indexing tabs
  components/use-sync.ts             start + poll a sync
  components/terms-editor.tsx        chips + Edit editor (brand terms, competitor terms)
  components/client-toolbar.tsx      Period → Data bar on client pages (DateBar + sync + missing-history hint)
  components/range-controls.tsx      shared date range store + DateBar (presets, custom dates, compare previous / year / custom / none)
  components/sync-controls.tsx       sync range picker + status line (shared by Integrations and Performance)
  lib/api.ts                         typed API client + formatters
```
Pages are thin server components wrapping client components in `<Suspense>` (required by `cacheComponents` for runtime params / search params). Data is fetched from the browser; running jobs are polled.

## 7. Security
- Secrets only in `.env` (gitignored); `.env.example` is the template.
- OAuth tokens encrypted at rest with Fernet (`TOKEN_ENCRYPTION_KEY`).
- Read-only Google scopes; OAuth state is single-use and expires.
- Upload limits: 20 MB file, 100 MB unzipped, 20 CSVs.
- No app login yet — run locally / on a trusted network only.

## 8. Configuration (`.env`)
`BACKEND_URL`, `FRONTEND_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY`, optional `NIGHTLY_SYNC_ENABLED` / `NIGHTLY_SYNC_TIME` / `TIMEZONE`. Compose sets `DATABASE_URL`, and polling env vars because Windows bind mounts don't emit file events.

## 9. Testing
```bash
docker compose exec backend python -m pytest -q
```
289 tests: OAuth, encryption, sync, reports maths, inspection discovery/quota/ordering, export parsing, advice, brand matching/segments, chunked/latest sync, comparisons, keyword types/filters/cache, striking distance / cannibalisation / live cache, seasonal / spikes / competitors, low-CTR pages, nightly sync, GA4 matching / pages / overview / AI traffic, endpoints. Frontend: typecheck + lint; verified manually in the browser.
