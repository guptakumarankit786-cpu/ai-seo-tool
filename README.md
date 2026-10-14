# AI SEO Tool

AI-powered SEO tool, built feature by feature.

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy, Alembic — `backend/`
- **Frontend:** Next.js 16 (TypeScript, Tailwind) — `frontend/`
- **Database:** Postgres 16
- Everything runs in Docker Compose.

## Getting started

1. Copy the env file and fill it in:
   ```bash
   cp .env.example .env
   ```
   Generate `TOKEN_ENCRYPTION_KEY` with the command in `.env.example`, and add your Google OAuth client (see [docs/gsc-setup.md](docs/gsc-setup.md)).
2. Start everything:
   ```bash
   docker compose up -d --build
   ```
3. Open <http://localhost:3000>. The API is at <http://localhost:8000/docs>.

## Tests

Backend tests run against a separate `seo_tool_test` database (Google APIs are mocked):

```bash
docker compose exec db psql -U seo -d seo_tool -c "CREATE DATABASE seo_tool_test"   # once
docker compose exec backend python -m pytest -q
```

## Features

| Feature | Status |
| --- | --- |
| Google Search Console connection (OAuth, property list, 90-day sync, dashboard) | ✅ |
| Indexing — "Why pages aren't indexed" via URL Inspection (sitemaps + search pages, 2,000/day quota) | ✅ |
| Indexing — upload Search Console's Page indexing export | ⏳ Next |

## Branches

- `main` — stable, release-ready code
- `test` — active development; features land here first, then merge into `main`
