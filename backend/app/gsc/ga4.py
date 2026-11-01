"""GA4 properties: mirror what each account can read and link one to every Search Console site.

GA4 is often named differently from Search Console: a property may track another domain or have
no website at all. So when no GA4 website matches, a site falls back to GA4 properties whose name
or account name contains the site's domain ("example.com - GA4") or brand ("Example Store").

A site often has several GA4 properties (old / new, Shopify / site), so when more than one shares
the site's address the one with the most sessions in the last 28 days wins. A link the user picked
by hand (ga4_manual) is never changed by matching.
"""

import re
import time
from collections import defaultdict
from datetime import date
from urllib.parse import unquote, urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.gsc import brand, google_api
from app.models import Ga4Property, GoogleConnection, GscProperty

# Google organic only, so GA4 sits like-for-like next to Search Console (which is Google only).
GOOGLE_ORGANIC = {
    "andGroup": {
        "expressions": [
            {"filter": {"fieldName": "sessionDefaultChannelGroup", "stringFilter": {"value": "Organic Search"}}},
            {"filter": {"fieldName": "sessionSource", "stringFilter": {"value": "google"}}},
        ]
    }
}
METRICS = ("sessions", "keyEvents", "ecommercePurchases", "purchaseRevenue")
FIELDS = ("sessions", "key_events", "orders", "revenue")
CACHE_SECONDS = 3600  # filters / sorting re-request the page report; one GA4 call per range per hour
_cache: dict[tuple, tuple[float, dict]] = {}


def site_host(url: str) -> str:
    """'sc-domain:example.com', 'https://www.example.com/shop' and 'example.com' -> 'example.com'."""
    url = url.removeprefix("sc-domain:").strip().lower()
    host = urlsplit(url if "://" in url else f"//{url}").hostname or ""
    return host.removeprefix("www.")


def refresh_properties(db: Session, conn: GoogleConnection) -> None:
    """Mirror the account's GA4 properties (if it granted Analytics access), then re-match sites."""
    if google_api.ANALYTICS_SCOPE not in conn.scopes.split():
        return
    found = {p["property"]: p for p in google_api.list_ga4_properties(google_api.access_token_for(db, conn))}
    existing = {g.property: g for g in db.scalars(select(Ga4Property).where(Ga4Property.connection_id == conn.id))}
    for name, g in existing.items():
        if name not in found:
            # A hand-picked property that's gone: fall back to automatic matching.
            db.execute(update(GscProperty).where(GscProperty.ga4_property_id == g.id).values(ga4_manual=False))
            db.delete(g)
    for name, p in found.items():
        g = existing.get(name) or Ga4Property(connection_id=conn.id, property=name)
        g.display_name, g.account_name, g.website_url = p["name"][:255], p["account"][:255], p["website_url"]
        db.add(g)
    db.commit()
    match_all(db)


def match_all(db: Session, property_id: int | None = None) -> None:
    """Link every Search Console property (or just `property_id`) not set by hand to its best GA4 property."""
    all_ga4 = db.scalars(select(Ga4Property)).all()
    by_host: dict[str, list[Ga4Property]] = defaultdict(list)
    for g in all_ga4:
        if g.website_url:
            by_host[site_host(g.website_url)].append(g)
    names = {g.id: brand.normalize(f"{g.display_name} {g.account_name}") for g in all_ga4}

    def by_name(site_url: str) -> list[Ga4Property]:
        """GA4 properties named after the site's domain, else after its brand (3+ letters)."""
        terms = [brand.normalize(site_host(site_url))] + [brand.normalize(t) for t in brand.suggest_terms(site_url)]
        for term in terms:
            found = [g for g in all_ga4 if len(term) >= 3 and term in names[g.id]]
            if found:
                return found
        return []

    sessions: dict[int, int] = {}  # fetched only for sites with several candidates
    tokens: dict[int, str] = {}

    def session_count(g: Ga4Property) -> int:
        if g.id not in sessions:
            try:
                if g.connection_id not in tokens:
                    tokens[g.connection_id] = google_api.access_token_for(db, db.get(GoogleConnection, g.connection_id))
                sessions[g.id] = google_api.ga4_sessions(tokens[g.connection_id], g.property)
            except google_api.GoogleAPIError:
                sessions[g.id] = -1  # no Data API access: rank below any readable property
        return sessions[g.id]

    props = select(GscProperty).where(GscProperty.ga4_manual.is_(False))
    if property_id is not None:
        props = props.where(GscProperty.id == property_id)
    for prop in db.scalars(props).all():
        candidates = by_host.get(site_host(prop.site_url)) or by_name(prop.site_url)
        if len(candidates) > 1:
            # Most sessions wins; on a tie the newest property (higher GA4 id).
            candidates = sorted(candidates, key=lambda g: (session_count(g), int(g.property.split("/")[-1])), reverse=True)
        prop.ga4_property_id = candidates[0].id if candidates else None
    db.commit()


# ---------- organic landing pages ----------


# GA4 sent from Shopify's custom-pixel sandbox records "/web-pixels@…/sandbox/modern/<real path>".
_PIXEL_PREFIX = re.compile(r"^/web-pixels@[^/]*/(?:custom/)?web-pixel-[^/]*/sandbox(?:/modern|/legacy)?")


def clean_path(path: str) -> str:
    """GA4 landing page with Shopify's pixel-sandbox prefix removed ('/web-pixels@…/sandbox/modern/x' -> '/x')."""
    return _PIXEL_PREFIX.sub("", path) or "/" if path.startswith("/web-pixels@") else path


def page_key(host: str, path: str) -> tuple[str, str]:
    """GA4 hostName + landingPage and a Search Console URL meet here: no www, decoded path, no trailing slash."""
    return site_host(host), unquote(clean_path(path)).rstrip("/") or "/"


def organic_landing_pages(db: Session, prop: GscProperty, start: date, end: date) -> dict | None:
    """Google-organic sessions / key events / orders / revenue per landing page from the site's linked
    GA4 property: {"name", "currency", "pages": {page_key: [sessions, key_events, orders, revenue]}}.
    None when the site has no GA4 link."""
    if not prop.ga4_property_id:
        return None
    g = db.get(Ga4Property, prop.ga4_property_id)
    return _cached(("pages", g.property, start, end), lambda: _landing_pages(db, g, start, end))


def _cached(key: tuple, build):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    out = build()
    if len(_cache) > 50:
        _cache.clear()
    _cache[key] = (time.monotonic(), out)
    return out


def _token(db: Session, g: Ga4Property) -> str:
    return google_api.access_token_for(db, db.get(GoogleConnection, g.connection_id))


def _landing_pages(db: Session, g: Ga4Property, start: date, end: date) -> dict:
    report = google_api.ga4_run_report(
        _token(db, g),
        g.property,
        {
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": "hostName"}, {"name": "landingPage"}],
            "metrics": [{"name": m} for m in METRICS],
            "dimensionFilter": GOOGLE_ORGANIC,
            # Sessions don't add up exactly across landing pages; GA4's own total matches GA4's reports.
            "metricAggregations": ["TOTAL"],
        },
    )
    pages: dict[tuple, list[float]] = {}
    for r in report["rows"]:
        k = page_key(*(d["value"] for d in r["dimensionValues"]))
        values = [float(m["value"]) for m in r["metricValues"]]
        pages[k] = [a + b for a, b in zip(pages.get(k, [0.0] * len(METRICS)), values)]
    totals = report["totals"] or [sum(v[i] for v in pages.values()) for i in range(len(METRICS))]
    return {"name": g.display_name, "currency": report["currency"], "pages": pages, "totals": totals}


def attach(rows: list[dict], report: dict) -> dict:
    """Put GA4 numbers on each clean page row (Shopping `?` rows get none); return the site totals,
    including sessions GA4 couldn't tie to any of these pages (e.g. Shopify's pixel sandbox URLs)."""
    pages, used = report["pages"], set()
    for r in rows:
        url = urlsplit(r["page"])
        k = None if url.query else page_key(url.hostname or "", url.path)
        # http:// and https:// rows of one page share a key: the numbers go to the first only.
        values = pages.get(k, [0.0] * len(METRICS)) if k and k not in used else None
        if k:
            used.add(k)
        for field, v in zip(FIELDS, values or [None] * len(FIELDS)):
            r[field] = v if field == "revenue" or v is None else int(v)
    totals = report["totals"]
    unmatched = max(0.0, totals[0] - sum(v[0] for k, v in pages.items() if k in used))
    return {
        "name": report["name"],
        "currency": report["currency"],
        **{f: (t if f == "revenue" else int(t)) for f, t in zip(FIELDS, totals)},
        # Orders counted but no order value sent: show "not tracked", not 0.
        "revenue_tracked": not (totals[2] > 0 and totals[3] == 0),
        "unmatched_sessions": int(unmatched),
    }


# ---------- AI assistant traffic ----------

# GA4's own "AI Assistant" channel catches most of it; these sources add visits GA4 files as
# Unassigned / Referral / Organic (e.g. utm_source=chatgpt.com). "cgpt_…" is ChatGPT ads (paid).
AI_SOURCES = (
    r"(.*\.)?(chatgpt\.com|chat\.openai\.com|openai\.com|gemini\.google\.com|bard\.google\.com|perplexity\.ai"
    r"|claude\.ai|copilot\.microsoft\.com|copilot\.com|chat\.deepseek\.com|deepseek\.com|grok\.com|meta\.ai"
    r"|chat\.mistral\.ai)|chatgpt|gemini|perplexity|claude|copilot|deepseek|grok|cgpt_.*"
)
AI_FILTER = {
    "orGroup": {
        "expressions": [
            {"filter": {"fieldName": "sessionDefaultChannelGroup", "stringFilter": {"value": "AI Assistant"}}},
            {"filter": {"fieldName": "sessionSource", "stringFilter": {"matchType": "FULL_REGEXP", "value": AI_SOURCES, "caseSensitive": False}}},
        ]
    }
}
# Checked in order; the first word found in the source names the assistant.
ASSISTANTS = (
    ("chatgpt", "ChatGPT"), ("openai", "ChatGPT"), ("gemini", "Gemini"), ("bard", "Gemini"),
    ("perplexity", "Perplexity"), ("claude", "Claude"), ("copilot", "Copilot"), ("deepseek", "DeepSeek"),
    ("grok", "Grok"), ("meta.ai", "Meta AI"), ("mistral", "Mistral"),
)
ADS = "ChatGPT ads"


def assistant(source: str) -> str:
    """'chatgpt.com' -> 'ChatGPT'; 'cgpt_ads' -> 'ChatGPT ads'; other AI Assistant sources -> 'Other AI'."""
    source = source.lower()
    if source.startswith("cgpt_"):
        return ADS
    return next((name for word, name in ASSISTANTS if word in source), "Other AI")


def _ranges(start: date, end: date, compare_start: date | None, compare_end: date | None) -> list[dict]:
    ranges = [{"startDate": start.isoformat(), "endDate": end.isoformat(), "name": "now"}]
    if compare_start:
        ranges.append({"startDate": compare_start.isoformat(), "endDate": compare_end.isoformat(), "name": "before"})
    return ranges


def ai_traffic(db: Session, prop: GscProperty, start: date, end: date, compare_start: date | None, compare_end: date | None) -> dict | None:
    """AI-assistant visits for the period (and comparison) from the site's linked GA4 property; None when not linked.

    Rows: {window: "now"|"before", date, assistant, host, path, sessions, key_events, orders, revenue},
    plus all-channel sessions per window for the AI share."""
    if not prop.ga4_property_id:
        return None
    g = db.get(Ga4Property, prop.ga4_property_id)
    return _cached(("ai", g.property, start, end, compare_start, compare_end), lambda: _ai(db, g, start, end, compare_start, compare_end))


def _ai(db: Session, g: Ga4Property, start, end, compare_start, compare_end) -> dict:
    token, ranges = _token(db, g), _ranges(start, end, compare_start, compare_end)
    report = google_api.ga4_run_report(
        token,
        g.property,
        {
            "dateRanges": ranges,
            "dimensions": [{"name": n} for n in ("date", "sessionSource", "hostName", "landingPage")],
            "metrics": [{"name": m} for m in METRICS],
            "dimensionFilter": AI_FILTER,
        },
    )
    rows = []
    for r in report["rows"]:
        day, source, host, path, *rest = (d["value"] for d in r["dimensionValues"])
        window = rest[0] if rest else "now"  # GA4 adds the range name as a last dimension with 2+ ranges
        values = [float(m["value"]) for m in r["metricValues"]]
        rows.append({
            "window": window, "date": date(int(day[:4]), int(day[4:6]), int(day[6:])), "assistant": assistant(source),
            "host": site_host(host), "path": clean_path(path), **dict(zip(FIELDS, values)),
        })
    everything = google_api.ga4_run_report(token, g.property, {"dateRanges": ranges, "metrics": [{"name": "sessions"}]})
    all_sessions = {"now": 0, "before": 0}
    for r in everything["rows"]:
        name = r["dimensionValues"][0]["value"] if r.get("dimensionValues") else "now"
        all_sessions[name] = int(float(r["metricValues"][0]["value"]))
    return {"name": g.display_name, "currency": report["currency"], "rows": rows, "all_sessions": all_sessions}


# ---------- GA4 overview (all channels) ----------

OVERVIEW_METRICS = ("sessions", "totalUsers", "engagedSessions", "keyEvents", "ecommercePurchases", "purchaseRevenue")
OVERVIEW_FIELDS = ("sessions", "users", "engaged_sessions", "key_events", "orders", "revenue")
TOP_PAGES = 100


def overview(db: Session, prop: GscProperty, start: date, end: date, compare_start: date | None, compare_end: date | None) -> dict | None:
    """All-channel GA4 for the period: totals and daily sessions per window, channels, top landing pages, devices.
    None when the site has no GA4 link."""
    if not prop.ga4_property_id:
        return None
    g = db.get(Ga4Property, prop.ga4_property_id)
    return _cached(("overview", g.property, start, end, compare_start, compare_end), lambda: _overview(db, g, start, end, compare_start, compare_end))


def _values(row: dict, fields=OVERVIEW_FIELDS) -> dict:
    return {f: float(m["value"]) for f, m in zip(fields, row["metricValues"])}


def _merge_pages(rows: list[dict]) -> list[dict]:
    """Landing pages with pixel-sandbox copies folded into the real page, most sessions first."""
    merged: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["dimensionValues"][0]["value"], clean_path(r["dimensionValues"][1]["value"]))
        values = _values(r)
        if key in merged:
            for f, v in values.items():
                merged[key][f] += v
        else:
            merged[key] = {"host": key[0], "path": key[1], **values}
    return sorted(merged.values(), key=lambda p: -p["sessions"])


def _overview(db: Session, g: Ga4Property, start, end, compare_start, compare_end) -> dict:
    token, ranges = _token(db, g), _ranges(start, end, compare_start, compare_end)
    metrics = [{"name": m} for m in OVERVIEW_METRICS]
    # Users don't add up across days or channels, so the window totals are GA4's own (TOTAL).
    by_day = google_api.ga4_run_report(
        token, g.property,
        {"dateRanges": ranges, "dimensions": [{"name": "date"}], "metrics": metrics, "metricAggregations": ["TOTAL"]},
    )
    daily = []
    for r in by_day["rows"]:
        day, *rest = (d["value"] for d in r["dimensionValues"])
        daily.append({"window": rest[0] if rest else "now", "date": date(int(day[:4]), int(day[4:6]), int(day[6:])), **_values(r)})
    # A session crossing midnight counts on both days, so channels come from their own report.
    by_channel = google_api.ga4_run_report(
        token, g.property, {"dateRanges": ranges, "dimensions": [{"name": "sessionDefaultChannelGroup"}], "metrics": metrics},
    )
    channels = []
    for r in by_channel["rows"]:
        channel, *rest = (d["value"] for d in r["dimensionValues"])
        channels.append({"window": rest[0] if rest else "now", "channel": channel, **_values(r)})
    current = ranges[:1]
    pages = google_api.ga4_run_report(
        token, g.property,
        {
            "dateRanges": current, "dimensions": [{"name": "hostName"}, {"name": "landingPage"}], "metrics": metrics,
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}], "limit": TOP_PAGES,
        },
    )
    devices = google_api.ga4_run_report(
        token, g.property, {"dateRanges": current, "dimensions": [{"name": "deviceCategory"}], "metrics": metrics},
    )
    return {
        "name": g.display_name,
        "currency": by_day["currency"],
        "totals": {w: dict(zip(OVERVIEW_FIELDS, v)) for w, v in by_day["range_totals"].items()},
        "daily": daily,
        "channels": channels,
        "pages": _merge_pages(pages["rows"]),
        "devices": [{"device": r["dimensionValues"][0]["value"], **_values(r)} for r in devices["rows"]],
    }
