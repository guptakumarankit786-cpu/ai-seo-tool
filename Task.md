# Tasks

_Last updated: 2026-10-15. Raw ideas live in [docs/ideas.md](docs/ideas.md); only move them here when the user decides to build them._

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
- [x] Backend test suite (146 tests)
- [x] Project docs: PRD, Architecture, Rules, Design, Task, Memory

## 🔜 Next — GSC phase (approved 2026-10-15, see docs/ideas.md)
- [ ] Keyword views part 2 (live query+page from Google): Striking distance, Cannibalisation
- [ ] Keyword views part 3: Competitor terms, Seasonal
- [ ] Test the export upload with a **real** Search Console export and adjust the parser if needed
- [ ] Decide what to merge from `test` into `main` (first stable release)

## 📋 Backlog (approved ideas, not started)
- [ ] Automatic scheduled syncs from Search Console (ideas #3)

## 🛠 Tech debt
- [ ] Move background jobs (sync, inspection) out of the API process into a worker — today a running job blocks backend auto-reload and dies on restart
- [ ] Rebuild the backend image so `pytest` and `python-multipart` are baked in (currently also pip-installed in the running container)
- [ ] App login / access control before hosting anywhere non-local
- [ ] Frontend automated tests (Playwright) once screens settle
- [ ] Production config: `next build` / `next start`, non-reload uvicorn, HTTPS redirect URI
- [ ] Silence the starlette `anyio.abc.BlockingPortal` deprecation warning (upgrade FastAPI/Starlette)
