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
- [x] Backend test suite (89 tests)
- [x] Project docs: PRD, Architecture, Rules, Design, Task, Memory

## 🔜 Next
- [ ] Test the export upload with a **real** Search Console export and adjust the parser if needed
- [ ] Decide what to merge from `test` into `main` (first stable release)

## 📋 Backlog (approved ideas, not started)
- [ ] Longer sync periods — user picks a range up to 16 months (ideas #2)
- [ ] Automatic scheduled syncs from Search Console (ideas #3)

## 🛠 Tech debt
- [ ] Move background jobs (sync, inspection) out of the API process into a worker — today a running job blocks backend auto-reload and dies on restart
- [ ] Rebuild the backend image so `pytest` and `python-multipart` are baked in (currently also pip-installed in the running container)
- [ ] App login / access control before hosting anywhere non-local
- [ ] Frontend automated tests (Playwright) once screens settle
- [ ] Production config: `next build` / `next start`, non-reload uvicorn, HTTPS redirect URI
- [ ] Silence the starlette `anyio.abc.BlockingPortal` deprecation warning (upgrade FastAPI/Starlette)
