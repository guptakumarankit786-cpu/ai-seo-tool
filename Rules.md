# Rules for Claude

How to work on this project. Read before every task.

## Workflow
1. **Build feature by feature.** One small, working slice at a time. Don't start the next feature until the current one is tested.
2. **Ideas are not tasks.** When the user shares an idea, add it to [docs/ideas.md](docs/ideas.md) (dated, status 💡 Later). Only build it when the user explicitly says so.
3. **Plan before big changes.** For a new feature, check what Google's APIs actually allow first (probe with real calls), then confirm the approach with the user if there's a real trade-off.
4. **Use the matching skills** before working: `fastapi-expert`, `python-pro`, `postgres-pro` (backend); `nextjs-developer`, `react-expert`, `typescript-pro` (frontend); `feature-forge` (planning); `test-master` (tests); `code-reviewer`, `secure-code-guardian` (before commit); `debugging-wizard` (bugs).
5. **Keep docs current.** After each feature, update [Task.md](Task.md), [Memory.md](Memory.md), and the README feature table; update [PRD.md](PRD.md) / [Architecture.md](Architecture.md) / [Design.md](Design.md) when behaviour or structure changes.

## Git
- Work on the **`test`** branch. Never commit or push to `main` unless the user asks.
- Commit only when the feature is tested; push to `origin test`.
- Commit author is the repo-local git config (GitHub no-reply email). End commit messages with the Claude co-author line.
- Never force-push or rewrite history without the user's explicit OK.

## Security & privacy — the repo is PUBLIC
- Never commit secrets: `.env`, client secrets, tokens, keys. Scan the staged diff before every commit.
- Never put **client names, client URLs or client data** in the repo (code, docs, tests, commit messages). Use `example.com` in tests.
- Never copy secrets (e.g. Google client secret) into files yourself — the user pastes them into `.env`.
- Never enter passwords; the user signs in.
- Fake test data on a real client must be clearly marked (e.g. `TEST-…`) and deleted right after.

## Product rules
- Expensive Google actions (sync, URL inspection) run **only when the user triggers them** for a client. No auto/bulk runs unless the user asks.
- Only use **current clients the user approves** for live tests; ask if unsure.
- Numbers from Google must match Google — verify against a live API call when changing report logic.
- Respect Google quotas (URL Inspection 2,000/day/property; Search Console data 16 months, ~3-day lag).

## Code
- Match the surrounding code: naming, comment density, patterns.
- Backend: sync SQLAlchemy sessions, Pydantic v2, `Annotated` deps; schema changes via `alembic revision --autogenerate`, then **read** the migration before applying.
- Frontend: Next.js 16 differs from older versions — read `frontend/node_modules/next/dist/docs/` before using an API. Pages using params/search params need `<Suspense>`.
- Every new backend behaviour gets pytest tests (Google mocked). All tests must pass before commit:
  `docker compose exec backend python -m pytest -q`
- Frontend must pass `npx tsc --noEmit` and `npm run lint`.

## Environment quirks (Windows + Docker)
- Hot reload needs polling (already configured). New route folders may need `docker compose restart frontend`.
- A running background job blocks backend auto-reload; restart the backend if needed (interrupted runs are marked failed on startup and can be resumed).
- Docker image builds are slow on this network — run them in the background.
- The in-app preview pane can stall rendering; verify UI in the user's browser when that happens.

## Communicating with the user
- Plain, simple language; step-by-step instructions when the user has to do something.
- Report honestly: what was tested, what wasn't, and any issues found.
- Ask before anything destructive or outward-facing (deleting data, force-push, accepting terms, granting access).
