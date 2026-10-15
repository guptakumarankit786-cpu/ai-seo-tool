# Project Memory

Decisions and learned facts, newest first. Add an entry whenever something is decided or discovered that isn't obvious from the code. **No client names or client data** — the repo is public.

## 2026-10-15

**Decisions**
- Project docs added: PRD, Architecture, Rules (for Claude), Design, Task, Memory.
- Indexing inspections run **only when the user clicks "Inspect pages"** for a client — no bulk/auto runs.
- Indexing has two sources: app inspection **and** Search Console export upload (user chose "both").
- "Worth fixing vs. waste of time" verdicts: `fix` / `review` / `ignore`, defined in `backend/app/gsc/advice.py`.
- "URL is unknown to Google" is **review**, not fix: on real data, unknown URLs from search data were genuine product/blog pages (likely Shopping-only), while unknown sitemap URLs were test pages that should leave the sitemap.
- Ideas the user shares go into `docs/ideas.md` and are **not** built until asked.
- Sync roadmap (user's order): manual 90-day sync now → longer periods later → automatic pulls after that.
- Use the installed Claude skills (Jeffallan/claude-skills) for every feature.

**Facts learned**
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
