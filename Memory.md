# Project Memory

Decisions and learned facts, newest first. Add an entry whenever something is decided or discovered that isn't obvious from the code. **No client names or client data** — the repo is public.

## 2026-10-27

**Decisions**
- **Pages tab** (user chose page types + filters, page detail, content decay; "pages vs indexing" later). Part 1 built: page types from the URL path (Shopify layout), filter chips reusing the keyword thresholds, live query (no cache).
- Page "new" needs 100+ impressions per 28 days (unlike keywords); Shopping `?variant=` URLs are never new / lost / low CTR / striking; the home page is never striking distance.
- A lost page also counts as declining — same as keywords.
- Content decay rule chosen on real data: a 30% drop alone flagged 66 pages, requiring all 3 months to fall only 18 (too strict — one flat month hides decay); "falling in 2 of the last 3 months" gave 50 real cases. Cause order: sudden (one month −70%) → ranking (≥ 1 place worse) → fewer searches (impressions −30%) → lower CTR (−30%) → mixed.
- Page detail keywords reuse the live keyword+page pull (≤ 90 days); beyond that the page shows "pick 28 days / 3 months" instead of pulling more from Google.
- Ideas added: #12 track page changes (before/after), #13f service-brand support (today's clients are D2C / e-commerce).
- Integrations page = **clients list grouped by brand** (user chose this over one row per property) and it shows **indexing data** too. A brand's row uses the property with the newest data (Domain on ties); the rest are under "n more properties".
- No "sync all" button — syncs stay per client, user-triggered (product rule).

**Facts learned**
- Real data (large Shopify client, 28 d): Home CTR ~11%, Products ~1%, Collections ~0.7%, **Blogs ~0.5%** — blogs get many impressions but the fewest clicks. Without a minimum, ~80% of "new" pages had 1–5 impressions; ~1/4 of all page URLs are Shopping `?variant=` listings.
- Real decay causes (large store, 15 months, 50 pages): ranking 24, sudden 10, fewer searches 10, lower CTR 4, mixed 2. Product "sudden drops" (e.g. 411 → 16 clicks in a month) are usually stock / URL changes, not content decay.
- Clients synced for only 3 months can't use content decay (needs 6 full months).
- **Concurrent first opens pulled from Google twice** (React dev mode fires each request twice; two users could too) and raced on the cache cleanup. Fixed with a Postgres advisory transaction lock per property around the query+page pull and the keyword-set build.
- Real example of what page detail surfaces: a blog post at position ~3 with 31k impressions and 0.04% CTR (site typical 1.1%), its top keyword at position 2.5 — a title/description problem, not a ranking one.
- A page's average position is diluted when it ranks for many searches (home page ~position 18) — don't treat it as striking distance.
- Of 38 properties, 33 brands: 26 with no data, 6 ~2 weeks behind, 1 up to date (2026-10-27). Some brands have both `http://` and `https://` URL properties, with data on only one.

## 2026-10-26

**Decisions**
- First stable release **v0.1.0**: everything on `test` (all features tested on real data) went to `main` as a fast-forward, keeping the feature-by-feature history. Releases are annotated tags on `main`; development continues on `test`.

**Facts learned**
- Real Page indexing exports (checked 2026-10-26): ZIP of `Chart.csv`, `Critical issues.csv`, `Non-critical issues.csv`, `Metadata.csv` (drill-down: `Chart.csv`, `Table.csv`, `Metadata.csv`). No BOM, LF line endings, no Trend column. `Metadata.csv` is `Property,Value` + `Sitemap,All known pages` (+ `Issue,<reason>`) — it **never names the site**. File name is `<domain>-Coverage-<date>.zip`.
- The "Property,Value" header was being read as the site "Value", so every real upload was rejected — sample fixtures had hidden this. Lesson: build test fixtures from a real file.
- Accounts with UK/Indian English get British wording: "Alternative page with proper canonical tag", "Blocked due to unauthorised request (401)".
- Chart.csv has blank Not indexed / Indexed values for its early days (impressions only).
- **UNLOGGED cache rows vanish after an unclean shutdown** (Docker Desktop stopping, laptop power-off): Postgres crash recovery truncates them, but the cache entries survive. Keywords tab showed 0 keywords. Fix: an entry with no rows counts as missing and is rebuilt (keyword sets and query+page pulls).
- Next.js 16.0.0–16.4.0 had critical advisories (RCE in image optimisation / `use cache`, Server Actions DoS) → upgraded to 16.4.3. The frontend container has its own `node_modules`: after a dependency change run `docker compose build frontend` and `docker compose up -d --force-recreate -V frontend`.
- The connected Search Console account is a second Google account in Chrome (`/u/1/`); add `authuser=<email>` to Search Console URLs to open it.

## 2026-10-24

**Decisions**
- Low CTR pages (idea 5p) reuse the keyword rule (top 10, enough impressions, CTR < half of typical) but learn a separate **page-level** typical CTR per position, with no brand split. Shopping `?` URLs are excluded. The Low CTR list is sorted by click shortfall, so the most-missed clicks come first. It's a live query with no cache.

**Facts learned**
- On a large site the page-level typical CTR at positions 1–5 is only ~0.8–1.6%. Page impressions include many long-tail queries, so judge pages against page baselines, not keyword ones.
- A stale backend image lacked `pytest` and `python-multipart` (the API failed with "Form data requires python-multipart"). The Dockerfile already installs both; a `docker compose build --no-cache` on 2026-10-26 fixed it — rebuild images when requirements change.

## 2026-10-15

**Decisions**
- Seasonal = peak repeats in the same calendar month in both years (local peak, ≥ 2× median, ≥ 100); plus a separate **Spikes** view (user chose "Seasonal + Spikes"). Competitor terms are user-entered per client (no suggestion).
- Striking distance & cannibalisation use query+page data pulled **live** and cached (until next sync / 24 h); limited to ≤ 90 days. Shopping URLs (with `?`) excluded. 3+ competing pages all in the top 3 = "likely sitelinks", flagged as fine.
- Keyword types are combinable chips (AND). Definitions live in `backend/app/gsc/keywords.py` and PRD §4.3.
- Low CTR uses the site's **own** typical CTR per position — overall clicks ÷ impressions (not the median), brand vs non-brand separately.
- Tagged keyword sets are cached per (window, comparison, look-back, brand terms) and served from the cache; the 28-day set is pre-built after each sync.
- 16-month sync is chunked by 30 days, newest first, committed per chunk; "Latest days" re-fetches 3 days of overlap.
- Year-over-year = same window 364 days earlier (weekday-aligned). No comparison is shown when stored history only partly covers the comparison window.
- Keyword text is normalised once in a Postgres generated column (`query_norm`) — reused for brand matching and the upcoming keyword views.
- Direction: cover **all of Google Search Console** first, then other sources. Keep the GSC phase **free** (Google APIs only).
- "High performance" keywords = the ones bringing the most traffic and impressions. Revenue per keyword comes later via GA4.
- Question and buying-intent views cover **all** English question / buying-intent patterns. Hinglish is postponed to a later idea (#5o).
- Striking distance / cannibalisation use query+page data **fetched live** from Google when opened — nothing extra stored.
- Keyword views are combinable filter chips (they overlap); Brand / Non-brand stays a switch.
- Brand vs non-brand: per-client editable **brand terms**, default suggested from the domain name. Matching ignores case, spaces and punctuation. Classification runs in SQL at read time (no stored flag) so term edits apply instantly.
- Anonymised queries: Google withholds a large share of clicks at keyword level (~30% on a real client). We show them as "hidden by Google" instead of assigning them to brand or non-brand.
- More query types (questions, product, local, competitor…) noted as idea #5 — not built.
- Project docs added: PRD, Architecture, Rules (for Claude), Design, Task, Memory.
- Indexing inspections run **only when the user clicks "Inspect pages"** for a client — no bulk/auto runs.
- Indexing has two sources: app inspection **and** Search Console export upload (user chose "both").
- "Worth fixing vs. waste of time" verdicts: `fix` / `review` / `ignore`, defined in `backend/app/gsc/advice.py`.
- "URL is unknown to Google" is **review**, not fix: on real data, unknown URLs from search data were genuine product/blog pages (likely Shopping-only), while unknown sitemap URLs were test pages that should leave the sitemap.
- Ideas the user shares go into `docs/ideas.md` and are **not** built until asked.
- Sync roadmap (user's order): manual 90-day sync now → longer periods later → automatic pulls after that.
- Use the installed Claude skills (Jeffallan/claude-skills) for every feature.

**Facts learned**
- A naive "half the year's impressions in 3 months" rule flags mostly one-off spikes (spam such as betting-app searches, short ranking jumps), not seasons. With 16 months only ~3 calendar months appear twice — true seasonality needs stored history beyond Google's window.
- Spikes surface spam/bot and junk searches (betting apps, adult terms, `site:` operator queries) — useful hygiene signal.
- Monthly aggregation of ~2.4M keyword rows takes ~14 s → cached per property after each sync.
- Live query+page pull on a large site: 28 d ≈ 68k rows / 6 s; 3 m ≈ 154k rows / 30 s.
- Postgres row estimates on freshly inserted / CTE data were off by 1000×+, turning joins into nested loops that ran for minutes. Fixes that worked: `ANALYZE` after bulk insert, window functions instead of self-joins, and passing small lookups (typical CTR) as parameters.
- Cannibalisation on brand / navigational searches is mostly Google sitelinks (many pages at position ~1) — not a real problem.
- On a real site the sharpest cannibalisation finds were two blog posts on the same topic splitting a "how to" query.
- On real data most keywords at positions 5–10 have zero clicks → the **median** CTR there is 0%, which made a median-based low-CTR rule blind. Use clicks ÷ impressions.
- Postgres regex alternations with word boundaries cost ~70–100 µs per keyword; splitting into words once and using array overlap is ~20× faster. Postgres JIT also added ~1.5 s to the tagging query because of bad row estimates — disabled for that statement.
- Keyword tagging cost (large site): first build ~3 s (7d) / ~6 s (28d) / ~14 s (3m) / ~25–45 s (16m); cached filters ~0.1 s; cache ≈ 77 MB for 5 ranges.
- Null-safety matters for cached flags (e.g. a keyword "." has no words; lost keywords have no current impressions) — flags default to false.
- Google returns the full 486 days (16 months) of performance data.
- **Google caps keyword rows at 5,000 per day** (date+query), regardless of request size. On a large site the cut-off keywords had **zero clicks** — clicks are unaffected. Splitting by device recovers ~20% more impression-only long-tail keywords (+36% rows); revisit for long-tail/question views.
- 16 months on a large site ≈ 2.8M rows, ~12 min to sync; regex-at-read brand matching took 12–14 s → generated column brought it to ~1.5 s.
- Brand terms need sub-brands/product lines and common misspellings — a domain-only term misses them (seen on real data).
- Tailwind classes from a newly added file may not appear in the Docker dev server until its cache is cleared: `docker compose exec frontend sh -c "rm -rf .next/*"` then restart the frontend.
- Google has **no API for the Page Indexing report**. Options: URL Inspection API (per URL) or the Search Console export.
- URL Inspection: 2,000 / property / day, 600 / minute, ~5–10 s per call; works for restricted users too; returns Search Console's own reason wording (curly quotes in "noindex").
- Search performance "pages" include Shopping/free-listing URLs with `?variant=…&utm_…` → Google reports them "unknown". Only clean URLs are inspected.
- Search Console keeps 16 months of performance data, ~2–3 day lag; 25k rows per API request.
- Re-checking freshly inspected URLs wastes quota → only re-inspect results older than 7 days.

## 2026-10-14

**Decisions**
- Fresh start: Docker wiped, new repo, build feature by feature.
- Stack: FastAPI + SQLAlchemy 2 + Alembic, Next.js 16 (TypeScript, Tailwind), Postgres 16, Docker Compose.
- Branches: `main` = stable, `test` = all development work.
- Repo is **public** → GitHub email privacy on; commits use the GitHub no-reply address; history rewritten once to remove personal emails.
- Google OAuth client lives in the agency's Workspace Cloud project; consent screen **Internal** (no 7-day token expiry, only workspace accounts can connect).
- Client secret is pasted into `.env` by the user — never handled by Claude.

**Facts learned**
- Windows + Docker bind mounts don't send file-change events → polling for Next.js (`NEXT_DEV_POLL_MS`) and uvicorn (`WATCHFILES_FORCE_POLLING`).
- Recharts' line animation stalls in background/throttled tabs → animations disabled.
- Next.js 16 with `cacheComponents`: pages reading params/search params must wrap them in `<Suspense>`; route types come from `next typegen`.
- Docker package downloads are very slow on this network; builds take several minutes.
