# Product Requirements — AI SEO Tool

_Last updated: 2026-10-27_

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
- **Clients list** (Integrations page): one row per **brand** — properties of the same site (Domain, `https://www.`, `http://`) are grouped; the brand shows the property with the newest data. Each brand shows its **search data** status (Up to date / N days behind / No data yet / Sync failed / Syncing… plus the stored date range), its **indexing data** (pages inspected, latest export upload) and a manual **Sync** button. Filter chips with counts by status, search, and an expandable list of the brand's other properties, each with its own Sync.
- Disconnect removes the account, its tokens and all synced data.

### 4.2 Performance ✅
- Manual sync per client, up to **16 months** of history (Google's maximum): choose *Latest days*, *3 months*, *6 months* or *Full 16 months*. Long syncs run month by month, newest first, with progress shown; *Latest days* only fetches days after what's stored.
- Dashboard: clicks, impressions, CTR, average position, daily chart, top queries, top pages; ranges 7d / 28d / 3m / 6m / 12m / 16m.
- Compare with the **previous period** or the **same period last year** (same weekdays, 52 weeks earlier); the comparison is drawn dashed on the chart. If stored history doesn't fully cover the comparison window, no change is shown ("Not enough history to compare") rather than a misleading one.
- Google returns at most ~5,000 keywords per day; the cut-off long tail had zero clicks in testing, so traffic numbers are unaffected.
- Numbers verified identical to Google's API.
- **Brand vs non-brand queries:** per-client brand terms (pre-filled from the domain, editable — add sub-brands and misspellings); brand / non-brand cards with change vs previous period and click share; daily brand vs non-brand chart; Top queries filter (All / Brand / Non-brand). Clicks Google hides at keyword level (anonymised queries) are shown separately, not guessed.
- **Low CTR pages:** Top pages has an All / Low CTR switch. A page is low CTR when it ranks top 10 with enough impressions (100 per 28 days) and its CTR is under half of the site's own typical **page** CTR at that position (no brand split; Shopping `?` URLs excluded). The Low CTR list is sorted by click shortfall — usually a title / description to rewrite.

### 4.3 Keywords ✅
A **Keywords** tab per client lists every keyword Google reported for the chosen range (7d–16m), with All / Brand / Non-brand, search, sortable columns, change vs the comparison period, and **combinable filter chips with counts**:

| Filter | Rule |
|---|---|
| High performance | The keywords that together bring 80% of clicks |
| Questions | how/what/why/when/where/which/who…, starts with can/should/is/do…, "?", "ways to", "tips for", "guide to", "meaning of" |
| Buying intent | buy, price, cost, cheap, discount, offer, deal, coupon, sale, best, top, review, vs, compare, alternative, online, delivery, COD, near me, free shipping… |
| Long-tail | 4+ words |
| New | Impressions now, none in the 90 days before |
| Lost | Clicks in the comparison period, none now |
| Rising / Declining | Clicks changed by ≥ 3 and ≥ 20% vs the comparison period |
| Low CTR | Top-10 position, enough impressions (100 per 28 days), CTR under half of the site's own typical CTR at that position — brand and non-brand judged separately |
| Zero clicks | Enough impressions, no clicks |

Comparison-based filters are disabled when stored history doesn't cover the comparison window. The first time a range is opened the keyword set is built (seconds to ~45 s for 16 months on very large sites); after that every filter, sort, search and page is instant. The 28-day set is pre-built at the end of each sync.

**Striking distance & Cannibalisation** (Keywords tab → view switch; 7 days – 3 months):

| View | Rule |
|---|---|
| Striking distance | The keyword's main page (most impressions) ranks 4–20 with enough impressions. Shows that page, other ranking pages, and **potential extra clicks** at position 3 using the site's own CTR there (brand / non-brand). |
| Cannibalisation | 2+ of the site's pages each get ≥ 10% of a keyword's impressions; every competing page with share, impressions, clicks, position. 3+ pages all in the top 3 = **likely sitelinks** (navigational search) — flagged as usually fine and listed last. |

Keyword+page data is pulled **live from Google** (free) the first time a range is opened (~5–30 s on large sites) and kept until the next sync or for 24 hours. Shopping / free-listing URLs (`?variant=…&utm_…`) are excluded.

**Competitors, Seasonal & Spikes:**

| Feature | Rule |
|---|---|
| Competitors chip | Editable competitor names per client (Keywords tab); searches mentioning one are tagged. Empty until the user adds names. |
| Seasonal | Over all stored history (full months, keywords with 1,000+ impressions): a calendar month seen in **both years** where the keyword had ≥ 2× its median month, ≥ 100 impressions, and stood out ≥ 25% from the months either side — **every time**. Status: in season / coming up (next 2 months) / off season. With Google's 16 months only ~3 calendar months repeat; coverage grows as stored history grows. |
| Spikes | Not seasonal, and one month holds ≥ 60% of the keyword's impressions at ≥ 5× its other months' median — spam/bot searches, news moments, short-lived rankings. Spikes in the first/last month of history are labelled as possibly a lost ranking / still growing. |

### 4.3b Pages ✅ (part 1)
A **Pages** tab per client (7d–16m, compare with previous period or last year):

- **Page types** from the URL: Home, Collections, Products, Blogs, Pages, Other, Shopping listings (`?variant=` URLs). A card per type with clicks, change, CTR, position and page count; click a card to list only that type.
- **Filter chips** (combinable, counts within the chosen type), same thresholds as keywords:

| Filter | Rule |
|---|---|
| High performance | The pages that together bring 80% of clicks |
| Low CTR | Top-10 position, 100+ impressions per 28 days, CTR under half of the site's typical **page** CTR at that position |
| Striking distance | Average position 4–20 with 100+ impressions per 28 days (home page left out — it ranks for too many searches) |
| Rising / Declining | Clicks changed by ≥ 3 and ≥ 20% vs the comparison period |
| New | 100+ impressions per 28 days now, none in the 90 days before (real data: most "new" pages without a minimum had 1–5 impressions) |
| Lost | Clicks in the comparison period, none now |
| Zero clicks | 100+ impressions per 28 days, no clicks |

Shopping listing URLs are never new, lost, low CTR or striking distance (Google rotates their parameters). Live query, ~0.3 s up to 16 months on a large site. Next: page detail (part 2), content decay (part 3).

### 4.4 Indexing — "Why pages aren't indexed" ✅
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
- Exports from a different site are rejected. Google's export doesn't name the site, so it's read from the exported URLs or Google's file name (`example.com-Coverage-…zip`); a renamed overview file can't be checked.
- Tested on a real export (2026-10-26): reasons, page counts, indexed / not-indexed totals and the 404 URL list match Search Console exactly.

**c) Worth fixing vs. safe to ignore**
- Every reason gets a verdict — **Worth fixing / Check pages / Safe to ignore** — with a one-line explanation and a concrete action.
- Flags sitemap URLs that shouldn't be in the sitemap (redirects, noindex, 404, etc.).

### 4.5 Planned
See [Task.md](Task.md) for the ordered backlog and [docs/ideas.md](docs/ideas.md) for raw ideas.
Highlights: keyword views (new, striking distance, long-tail, questions, buying intent…), automatic scheduled syncs, more data sources.

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
