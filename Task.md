# Tasks

_Last updated: 2026-10-27. Raw ideas live in [docs/ideas.md](docs/ideas.md); only move them here when the user decides to build them._

## ✅ Done
- [x] Repo setup: `main` (stable) + `test` (development), public repo hygiene, `.gitattributes` (LF)
- [x] Stack scaffold: FastAPI + Postgres + Alembic + Next.js 16 in Docker Compose
- [x] Google OAuth (Internal Workspace app), encrypted token storage, multi-account
- [x] Property discovery (all Search Console properties of an account)
- [x] Performance: manual 90-day sync, dashboard (KPIs vs previous period, chart, top queries/pages, 7/28/90d) — verified identical to Google
- [x] Indexing (inspected by app): sitemap + search URL discovery, URL Inspection within 2,000/day quota, reasons with page lists
- [x] Indexing (Search Console export upload): overview + per-reason URL lists, wrong-site protection
- [x] Worth fixing vs. safe to ignore: verdict + action per reason, sitemap-cleanup flags
- [x] Integrations: Performance + Indexing links for every client
- [x] Performance: brand vs non-brand queries — editable brand terms, segment cards, daily chart, Top queries filter, hidden-clicks note
- [x] 16 months of data: 3 / 6 / 16-month sync in monthly chunks with progress, "Latest days" sync, 3m–16m ranges, compare with previous period or last year (dashed on chart), generated `query_norm` for fast keyword matching — verified identical to Google
- [x] Keywords tab (part 1): High performance, Questions, Buying intent, Long-tail, New, Lost, Rising, Declining, Low CTR, Zero clicks — combinable chips with counts, All/Brand/Non-brand, search, sort, paging; cached tagged sets, 28-day set pre-built after sync
- [x] Keywords tab (part 2): Striking distance (main page 4–20, potential clicks at position 3) and Cannibalisation (2+ pages ≥ 10%, sitelinks flagged) from live query+page data, cached until next sync / 24 h
- [x] Keywords tab (part 3): Competitors chip with editable competitor terms; Seasonal (peak repeats in both years, status in / coming up / off season) and Spikes (one-off surges) from a monthly cache rebuilt after sync
- [x] Low CTR pages: Top pages All / Low CTR switch, page flagged when CTR < half the site's typical page CTR at its position (ideas #5p)
- [x] Export upload tested on a real Search Console export: fixed header-row bug (every real upload was rejected), site check from URLs / file name, British-spelling reasons
- [x] Fix: Keywords tab empty after an unclean shutdown (UNLOGGED cache rows lost) — empty cache entries are rebuilt; Next.js 16.4.0 → 16.4.3 (critical security advisories)
- [x] Integrations redesign: clients grouped by brand, search-data status (up to date / behind / no data / failed / syncing) with range, indexing data (pages inspected, export), manual Sync, status filter chips, search
- [x] Pages tab part 1: page-type cards (Home / Collections / Products / Blogs / Pages / Other / Shopping listings) + filter chips (High performance, Low CTR, Striking distance, Rising, Declining, New, Lost, Zero clicks); Top pages reuses the same page rows
- [x] Pages tab part 2: page detail — KPIs vs comparison, daily chart, keywords bringing the page traffic, indexing status + export lists; opened from the Pages tab and Top pages
- [x] Fix: two requests opening the same range no longer both pull from Google / build the keyword set (advisory lock per property)
- [x] Backend test suite (224 tests)
- [x] Project docs: PRD, Architecture, Rules, Design, Task, Memory
- [x] First stable release **v0.1.0** (2026-10-26): `main` fast-forwarded to `test`, tagged; clean Docker rebuild + 194 tests + smoke test passed
- [x] Release **v0.1.1** (2026-10-26): empty-Keywords-cache fix + Next.js 16.4.3 security upgrade
- [x] Release **v0.1.2** (2026-10-27): Integrations redesigned as a clients list grouped by brand

## 🔜 Next — GSC phase (approved 2026-10-15, see docs/ideas.md)
- [ ] Pages tab part 3: content decay (#13d)

## 📋 Backlog (approved ideas, not started)
- [ ] Automatic scheduled syncs from Search Console (ideas #3)

## 🛠 Tech debt
- [ ] Move background jobs (sync, inspection) out of the API process into a worker — today a running job blocks backend auto-reload and dies on restart
- [ ] App login / access control before hosting anywhere non-local
- [ ] Frontend automated tests (Playwright) once screens settle
- [ ] Production config: `next build` / `next start`, non-reload uvicorn, HTTPS redirect URI
- [ ] Silence the starlette `anyio.abc.BlockingPortal` deprecation warning (upgrade FastAPI/Starlette)
