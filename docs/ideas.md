# Product ideas & roadmap notes

Ideas captured for later. Nothing here is implemented unless marked ✅. Status: ✅ built · 🎯 approved (GSC phase, building next) · 💡 later.

**Direction (2026-10-15):** cover every aspect of Google Search Console first, then move to other data sources (GA4, backlinks, crawler, AI).

## Google Search Console sync

| # | Idea | Status |
|---|------|--------|
| 1 | **Manual sync** — user clicks "Sync" per property; pulls the last 90 days (daily totals, queries, pages). | ✅ Built |
| 2 | **16 months of data** — choose 3 / 6 / 16 months; first run fetches full history, later runs only fetch new days; 90-day "vs previous period" and year-over-year work. | ✅ Built 2026-10-15 |
| 3 | **Automatic pulls** — the app syncs on a schedule (e.g. daily, last few days only), building history beyond 16 months with no manual clicks. | 💡 Later |

## Performance — keyword views (Top queries)

All views are filter chips with counts that can be combined (e.g. Non-brand + Striking distance). Brand / Non-brand stays a simple switch.

| # | View | Definition / decision | Status |
|---|------|------|--------|
| — | Brand / Non-brand | Editable brand terms per client. | ✅ Built |
| 5a | **New keywords** | Impressions in the latest period, none in the months before (uses 16-month history). | ✅ Built |
| 5b | **Striking distance** | Avg position ~4–20 with real impressions, with the ranking page. Query+page data **fetched live from Google** when opened (free, nothing extra stored). | ✅ Built |
| 5c | **Long-tail** | 4+ words (adjustable). | ✅ Built |
| 5d | **High performance** | Keywords bringing the most **traffic and impressions** (e.g. those making up ~80% of clicks). | ✅ Built |
| 5e | **Question keywords** | Every question-style keyword: who/what/when/where/why/which/whose/whom/how, can/could/should/would/will, is/are/was/were, do/does/did, has/have, "?", plus forms like "how to", "what is", "ways to", "tips for", "guide to". | ✅ Built |
| 5f | **Buying-intent keywords** | Every buying-intent keyword: buy, order, shop, purchase, price, cost, cheap, affordable, discount, offer, deal, coupon, sale, best, top, review(s), vs, compare, alternative, online, near me, delivery, COD, free shipping, for sale… | ✅ Built |
| 5g | Lost keywords | Had clicks before, none now. | ✅ Built |
| 5h | Rising / Declining | Biggest click gains / losses vs previous period or last year. | ✅ Built |
| 5i | Low CTR | High impressions, CTR well below normal for that position. | ✅ Built |
| 5j | Zero clicks | High impressions, no clicks. | ✅ Built |
| 5k | Cannibalisation | One keyword split across several pages (same live query+page data as 5b). | ✅ Built |
| 5l | Competitor terms | Editable competitor list per client, like brand terms. | ✅ Built |
| 5m | Seasonal keywords (+ Spikes) | Peak repeats in the same months in both years; one-off surges shown as Spikes. | ✅ Built |
| 5n | Other types | Product, local, etc. | 💡 Later |
| 5o | **Hinglish keywords** | Per-client switch adding Hinglish question words (kya, kaise, kyu, kab, kahan, kitna…) and buying words (sasta, kharidna…). | 💡 Later |

## Insights & AI

| # | Idea | Status |
|---|------|--------|
| 6 | **Prioritise pages *within* an issue** — e.g. of 900 404s, rank which are worth fixing (lost traffic, impressions, backlinks, internal links, money pages) vs. safe to leave. | 💡 Later |
| 7 | **Low-CTR fixes** — suggest a new meta title & description for low-CTR pages. | 💡 Later |
| 8 | **Why impressions dropped** — seasonality vs. ranking loss vs. lost pages vs. indexing vs. SERP features, with a recovery plan. | 💡 Later |
| 9 | **AI layer** across all insights — explanations, rewrites, recovery plans. | 💡 Later |
| 10 | **Borrow from open-seo** — device/country/text filters, GA4 join, reports, AI chat over our data (striking distance & new keywords moved to 5a/5b). | 💡 Later |
| 11 | **Revenue per keyword** — after GA4 is connected, estimate how much revenue keywords bring (GSC page↔keyword joined with GA4 page revenue). | 💡 Later (after GA4) |

## Indexing — "Why pages aren't indexed"

| # | Idea | Status |
|---|------|--------|
| — | **Decision:** inspection runs only when the user clicks "Inspect pages" for a client — no automatic or bulk runs. | ✅ Current behaviour |
| 4 | **Worth fixing vs. waste of time** — verdict + what-to-do per reason, sitemap-cleanup flags. | ✅ Built |

## Constraints agreed
- Keep it **free**: only Google's free APIs for the GSC phase; paid APIs (DataForSEO, AI) come later and need approval.
