# Project Memory

Decisions and learned facts, newest first. Add an entry whenever something is decided or discovered that isn't obvious from the code. **No client names or client data** — the repo is public.

## 2026-10-15

**Decisions**
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
