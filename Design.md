# Design — AI SEO Tool

_Last updated: 2026-10-15_

## 1. Principles
- **Calm, data-first.** Numbers and advice are the hero; chrome stays quiet.
- **Answer "what should I do?"** Verdicts and actions sit next to the data, not on a separate page.
- **Honest states.** Always show where data came from, when it was fetched, and what's still loading or missing.
- **Light and dark** follow the system setting.
- **Works on a phone** (single column, wrapping toolbars) but optimised for desktop.

## 2. Tokens (`frontend/src/app/globals.css`)

| Token | Light | Dark | Use |
|---|---|---|---|
| `background` | `#f7f7f8` | `#0e0e11` | page |
| `surface` | `#ffffff` | `#17171c` | cards, tables |
| `foreground` | `#16161a` | `#ececf1` | text |
| `muted` | `#6b6b76` | `#9a9aa6` | secondary text, labels |
| `border` | `#e4e4e9` | `#2a2a31` | dividers, outlines |
| `accent` / `accent-soft` | `#2563eb` / `#e8efff` | `#60a5fa` / `#1b2740` | primary actions, active states, links |
| `positive` | `#15803d` | `#4ade80` | good change, indexed, safe to ignore |
| `negative` | `#b91c1c` | `#f87171` | bad change, not indexed, worth fixing |
| `chart-clicks` / `chart-impressions` | blue / purple | lighter variants | chart lines |
| `chart-brand` / `chart-non-brand` | `#2563eb` / `#d97706` | `#60a5fa` / `#fbbf24` | brand (blue) vs non-brand (amber) everywhere: dots, share bars, chart lines |

Use tokens through Tailwind (`bg-surface`, `text-muted`, `border-border`, `bg-negative/15`) — never hard-coded colours.

**Type:** Geist Sans (UI), Geist Mono (code). Page title `text-2xl font-semibold`, section title `text-sm font-medium`, body `text-sm`, meta `text-xs text-muted`. Numbers use `tabular-nums`.

## 3. Layout
- Left sidebar (`md:w-56`) with app name + nav; becomes a top bar on mobile.
- Content max width: `max-w-4xl` (Integrations), `max-w-6xl` (client pages). Spacing `space-y-6` between sections.
- Client pages: back link → title + property badge → **Performance | Indexing** tabs → content.

## 4. Components (`frontend/src/components/ui.tsx`)
| Component | Notes |
|---|---|
| `Card` | rounded-xl, border, surface background. |
| `Button` | `primary` (accent), `secondary` (outlined), `danger` (red text). Disabled = 50% opacity. |
| `Banner` | success / error message line. |
| `Badge` | small pill: property type, "sitemap". |
| `PropertyTabs` | underline tabs per client. |
| KPI card | label (xs muted) → big number → optional delta / hint. |
| Verdict badge | 🔴 **Worth fixing** (`negative/15`), 🔵 **Check pages** (`accent-soft`), 🟢 **Safe to ignore** (`positive/15`). |
| Expandable row | chevron + title + badges + count; opens advice box + URL table + "Show more". |
| Progress card | text + thin accent bar, polled every 2–3 s. |
| Segmented control | 7d / 28d / 3m / 6m / 12m / 16m ranges; "Inspected by app / Search Console export"; Top queries All / Brand / Non-brand. |
| Segment card | coloured dot + label, share-of-clicks bar, 4 metrics with change vs previous period. |
| Sync controls | select (Latest days / 3 / 6 / 16 months) + Sync button; status line underneath ("Data Jun 14, 2025 – Oct 12 · synced …", or "Syncing — month 4 of 17…"). |
| Compare select | "Compare: previous period / same period last year"; KPI deltas say "vs previous period" / "vs last year"; chart shows the comparison as dashed, faded lines. |
| Terms editor | chips + Edit → comma-separated input, Save / Cancel / Reset to suggestion. |

## 5. Patterns
- **Tables:** `table-fixed` with narrow fixed-width number columns so the text column gets the space; sticky header, truncated URLs with full URL on hover, host stripped (`/products/x`), numbers right-aligned, extra columns hidden on small screens.
- **Advice box:** muted summary line, then **What to do:** action; red sitemap-cleanup note when relevant.
- **Empty states** say what to do next ("Run an inspection…", "Upload an export…").
- **Errors** show the backend's message in plain words.
- **Long jobs** show live progress and quota remaining; never block the page.
- **Dates** show the year only when it isn't the current year ("Oct 12" vs "Jun 14, 2025"); long chart ranges label months ("Jun 25").

## 6. Copy
- Plain English, short sentences, no jargon where a simple word works ("Pages found", "Waiting to be inspected").
- Use Google's exact reason names so they match Search Console.
- Buttons are verbs: "Sync 90 days", "Inspect pages", "Upload export".

## 7. Accessibility
- Semantic buttons/links, `aria-expanded` on expandable rows, `aria-current` on tabs, `role="tablist"` on segmented controls.
- Colour is never the only signal — verdicts always have text labels.
