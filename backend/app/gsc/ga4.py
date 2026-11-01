"""GA4 properties: mirror what each account can read and link one to every Search Console site.

A site often has several GA4 properties (old / new, Shopify / site), so when more than one shares
the site's address the one with the most sessions in the last 28 days wins. A link the user picked
by hand (ga4_manual) is never changed by matching.
"""

from collections import defaultdict
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.gsc import google_api
from app.models import Ga4Property, GoogleConnection, GscProperty


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
    by_host: dict[str, list[Ga4Property]] = defaultdict(list)
    for g in db.scalars(select(Ga4Property).where(Ga4Property.website_url.is_not(None))):
        by_host[site_host(g.website_url)].append(g)

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
        candidates = by_host.get(site_host(prop.site_url), [])
        if len(candidates) > 1:
            # Most sessions wins; on a tie the newest property (higher GA4 id).
            candidates = sorted(candidates, key=lambda g: (session_count(g), int(g.property.split("/")[-1])), reverse=True)
        prop.ga4_property_id = candidates[0].id if candidates else None
    db.commit()
