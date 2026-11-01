"""GA4 properties: mirror what each account can read and link one to every Search Console site.

GA4 is often named differently from Search Console: a property may track another domain or have
no website at all. So when no GA4 website matches, a site falls back to GA4 properties whose name
or account name contains the site's domain ("example.com - GA4") or brand ("Example Store").

A site often has several GA4 properties (old / new, Shopify / site), so when more than one shares
the site's address the one with the most sessions in the last 28 days wins. A link the user picked
by hand (ga4_manual) is never changed by matching.
"""

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


def page_key(host: str, path: str) -> tuple[str, str]:
    """GA4 hostName + landingPage and a Search Console URL meet here: no www, decoded path, no trailing slash."""
    return site_host(host), unquote(path).rstrip("/") or "/"


def organic_landing_pages(db: Session, prop: GscProperty, start: date, end: date) -> dict | None:
    """Google-organic sessions / key events / orders / revenue per landing page from the site's linked
    GA4 property: {"name", "currency", "pages": {page_key: [sessions, key_events, orders, revenue]}}.
    None when the site has no GA4 link."""
    if not prop.ga4_property_id:
        return None
    g = db.get(Ga4Property, prop.ga4_property_id)
    key = (g.property, start, end)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]

    token = google_api.access_token_for(db, db.get(GoogleConnection, g.connection_id))
    report = google_api.ga4_run_report(
        token,
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
    out = {"name": g.display_name, "currency": report["currency"], "pages": pages, "totals": totals}

    if len(_cache) > 50:
        _cache.clear()
    _cache[key] = (time.monotonic(), out)
    return out


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
