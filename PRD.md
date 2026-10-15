# Product Requirements — AI SEO Tool

_Last updated: 2026-10-15_

## 1. Vision

One workspace where an SEO agency team can see every client's search data in one place and get **clear, prioritised advice** on what to fix — instead of jumping between Search Console accounts and spreadsheets.

The tool connects to each data source once, keeps its own history, and turns raw reports into "here's what's worth your time".

## 2. Users

| User | Needs |
|---|---|
| **SEO specialist** (primary) | Check a client's traffic and indexing quickly, find problems, know which ones actually matter. |
| **SEO lead / agency owner** | See all clients at a glance, spot who needs attention, report progress. |

The agency manages many client sites (dozens of Search Console properties) from one Google Workspace account.

## 3. Principles

1. **Feature by feature.** Ship one small, working slice at a time; test it on real data before moving on.
2. **The user decides when heavy work runs.** Expensive actions (syncs, URL inspections) are triggered per client by the user — no automatic bulk jobs unless explicitly added later.
3. **Advice over raw data.** Every report should answer "is this worth fixing?" — not just list numbers.
4. **Match Google's numbers.** Where we show Google data, it must equal what Google reports.
5. **Read-only towards clients.** The tool only reads from Google; it never changes anything in Search Console.

## 4. Features

### 4.1 Integrations — Google Search Console ✅
- Connect one or more Google accounts via OAuth (read-only Search Console scope).
- Auto-discover every Search Console property the account can see.
- Per client: **Performance** and **Indexing** pages.
- Disconnect removes the account, its tokens and all synced data.

### 4.2 Performance ✅
- Manual **Sync 90 days** per client: daily totals, per-query and per-page metrics.
- Dashboard: clicks, impressions, CTR, average position (vs previous period), daily chart, top queries, top pages; 7 / 28 / 90-day views.
- Numbers verified identical to Google's API.

### 4.3 Indexing — "Why pages aren't indexed" ✅
Google offers **no API** for the Page Indexing report, so there are two sources:

**a) Inspected by app**
- User clicks **Inspect pages** for a client.
- The app finds URLs from submitted sitemaps + clean pages seen in search data, and checks each with Google's URL Inspection API.
- Respects Google's quota (2,000 inspections / property / day); continues on later runs; re-checks results older than 7 days.
- Shows indexed / not indexed / waiting, and the list of reasons with affected pages.

**b) Search Console export**
- User uploads the Page indexing export (ZIP/CSV) from Search Console.
- Shows Search Console's exact reasons, page counts, source and validation status.
- Uploading a single reason's export adds its example URLs.
- Exports from a different site are rejected.

**c) Worth fixing vs. safe to ignore**
- Every reason gets a verdict — **Worth fixing / Check pages / Safe to ignore** — with a one-line explanation and a concrete action.
- Flags sitemap URLs that shouldn't be in the sitemap (redirects, noindex, 404, etc.).

### 4.4 Planned
See [Task.md](Task.md) for the ordered backlog and [docs/ideas.md](docs/ideas.md) for raw ideas.
Highlights: longer sync periods (up to 16 months), automatic scheduled syncs, more data sources.

## 5. Non-goals (for now)
- Writing to Search Console (submitting sitemaps, requesting indexing).
- Multi-tenant SaaS / customer logins — this is an internal agency tool.
- Bulk "inspect all clients" jobs.

## 6. Constraints
- **Google limits:** Search Console keeps 16 months of performance data; data lags ~2–3 days; URL Inspection is 2,000/day/property and ~5–10 s per call.
- **OAuth app is Internal** to the agency's Google Workspace: only workspace accounts can connect (no weekly re-consent). Switching to External is needed to connect outside accounts.
- **Public repository:** no secrets, client names or client data in the repo.

## 7. Success measures
- Time to answer "what's wrong with client X's indexing?" drops from tens of minutes to under a minute.
- Every number shown matches Google for the same date range.
- Recommendations lead to fixes: tracked later via re-inspection / export comparisons.
