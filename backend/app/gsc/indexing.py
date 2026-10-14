"""Rebuild Search Console's "Why pages aren't indexed" report via the URL Inspection API.

Google exposes no API for the Page Indexing report, so we:
1. discover the property's URLs (submitted sitemaps + pages seen in search performance data),
2. inspect each one (2,000 inspections / property / day), and
3. group the results by coverage state.
"""

import gzip
import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, desc, func, insert, nulls_first, or_, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.gsc import google_api
from app.models import GscInspectionRun, GscPageMetric, GscProperty, GscUrlInspection

log = logging.getLogger(__name__)

DAILY_INSPECTION_LIMIT = 2_000  # Google's per-property quota
WORKERS = 10  # concurrent inspections; each takes ~5-10s, so still far under 600/minute
MAX_URLS = 50_000  # cap on discovered URLs per property
MAX_SITEMAP_FILES = 200
MAX_SITEMAP_BYTES = 50 * 1024 * 1024  # sitemaps.org limit per file
MAX_URL_LENGTH = 2_000
COMMIT_EVERY = 25
RECHECK_AFTER = timedelta(days=7)  # don't spend quota re-inspecting fresh results

# Coverage states Search Console counts as indexed; everything else is a "why not indexed" reason.
INDEXED_STATES = frozenset(
    {
        "Submitted and indexed",
        "Indexed, not submitted in sitemap",
        "Indexed, though blocked by robots.txt",
    }
)


def is_indexed(coverage_state: str | None) -> bool:
    return coverage_state in INDEXED_STATES


def belongs_to(site_url: str, url: str) -> bool:
    """True if the URL is inside the property (domain property or URL-prefix property)."""
    if site_url.startswith("sc-domain:"):
        domain = site_url.removeprefix("sc-domain:").lower()
        host = (urlsplit(url).hostname or "").lower()
        return host == domain or host.endswith("." + domain)
    return url.startswith(site_url)


def is_clean_url(url: str) -> bool:
    """Exclude parameterised/fragment URLs (tracking, variants, faceted filters)."""
    parts = urlsplit(url)
    return not parts.query and not parts.fragment


# ---------- URL discovery ----------


def _parse_sitemap(content: bytes) -> tuple[list[str], list[str]]:
    """Return (page URLs, child sitemap URLs) from a urlset or sitemapindex document."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    root = ET.fromstring(content)
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    if root.tag.endswith("sitemapindex"):
        return [], locs
    return locs, []


def sitemap_urls(sitemap_paths: list[str]) -> set[str]:
    """Fetch sitemaps (following sitemap indexes) and collect page URLs."""
    pages: set[str] = set()
    queue, seen = list(sitemap_paths), set()
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "AI-SEO-Tool/0.1"}) as client:
        while queue and len(seen) < MAX_SITEMAP_FILES and len(pages) < MAX_URLS:
            path = queue.pop(0)
            if path in seen:
                continue
            seen.add(path)
            try:
                resp = client.get(path)
                resp.raise_for_status()
                if len(resp.content) > MAX_SITEMAP_BYTES:
                    log.warning("Skipping oversized sitemap %s", path)
                    continue
                found, children = _parse_sitemap(resp.content)
            except (httpx.HTTPError, ET.ParseError, OSError) as exc:
                log.warning("Could not read sitemap %s: %s", path, exc)
                continue
            pages.update(found)
            queue.extend(children)
    return pages


def discover_urls(db: Session, prop: GscProperty, token: str) -> int:
    """Upsert every known URL for the property into gsc_url_inspections. Returns the total known."""
    sitemap_paths = [s["path"] for s in google_api.list_sitemaps(token, prop.site_url)]
    from_sitemaps = {u for u in sitemap_urls(sitemap_paths) if belongs_to(prop.site_url, u)}
    # Search data also contains Shopping/free-listing URLs (?variant=…&utm_…) that aren't crawlable
    # pages; Google reports those as "URL is unknown". Only clean URLs are worth an inspection.
    from_search = {
        url
        for url in db.scalars(
            select(GscPageMetric.page).where(GscPageMetric.property_id == prop.id).distinct()
        )
        if is_clean_url(url)
    }
    wanted = from_sitemaps | from_search

    existing = {
        row.url: row
        for row in db.scalars(select(GscUrlInspection).where(GscUrlInspection.property_id == prop.id))
    }
    stale = [url for url in existing if url not in wanted]
    if stale:
        db.execute(
            delete(GscUrlInspection).where(
                GscUrlInspection.property_id == prop.id, GscUrlInspection.url.in_(stale)
            )
        )
        for url in stale:
            del existing[url]

    new_rows = []
    for url in wanted:
        if len(url) > MAX_URL_LENGTH:
            continue
        in_sitemap, in_search = url in from_sitemaps, url in from_search
        if url in existing:
            existing[url].in_sitemap, existing[url].in_search = in_sitemap, in_search
        elif len(existing) + len(new_rows) < MAX_URLS:
            new_rows.append(
                {"property_id": prop.id, "url": url, "in_sitemap": in_sitemap, "in_search": in_search}
            )
    if new_rows:
        db.execute(insert(GscUrlInspection), new_rows)
    db.commit()
    return len(existing) + len(new_rows)


# ---------- inspection ----------


def inspections_used_last_24h(db: Session, property_id: int) -> int:
    used = db.scalar(
        select(func.coalesce(func.sum(GscInspectionRun.urls_inspected + GscInspectionRun.urls_failed), 0)).where(
            GscInspectionRun.property_id == property_id,
            GscInspectionRun.started_at > datetime.now(UTC) - timedelta(hours=24),
        )
    )
    return int(used)


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _apply_result(row: GscUrlInspection, result: dict) -> None:
    row.coverage_state = result.get("coverageState")
    row.verdict = result.get("verdict")
    row.indexing_state = result.get("indexingState")
    row.robots_txt_state = result.get("robotsTxtState")
    row.page_fetch_state = result.get("pageFetchState")
    row.google_canonical = result.get("googleCanonical")
    row.user_canonical = result.get("userCanonical")
    row.last_crawl_time = _parse_time(result.get("lastCrawlTime"))
    row.inspected_at = datetime.now(UTC)
    row.error = None


def run_inspection(run_id: int) -> None:
    """Background job: discover URLs, then inspect as many as today's quota allows.

    Never-inspected URLs go first (sitemap URLs before search-only ones), then the stalest results,
    so repeated runs walk the whole site.
    """
    db = SessionLocal()
    try:
        run = db.get(GscInspectionRun, run_id)
        prop = db.get(GscProperty, run.property_id)
        token = google_api.access_token_for(db, prop.connection)

        run.urls_known = discover_urls(db, prop, token)
        budget = max(0, DAILY_INSPECTION_LIMIT - inspections_used_last_24h(db, prop.id))
        rows = db.scalars(
            select(GscUrlInspection)
            .where(
                GscUrlInspection.property_id == prop.id,
                or_(
                    GscUrlInspection.inspected_at.is_(None),
                    GscUrlInspection.inspected_at < datetime.now(UTC) - RECHECK_AFTER,
                ),
            )
            .order_by(
                nulls_first(GscUrlInspection.inspected_at),
                desc(GscUrlInspection.in_sitemap),
                GscUrlInspection.id,
            )
            .limit(budget)
        ).all()
        run.urls_queued = len(rows)
        db.commit()

        # Long runs can outlive the 1h access token; workers read the current one from here.
        auth = {"token": token}

        def inspect(url: str) -> dict:
            return google_api.inspect_url(auth["token"], prop.site_url, url)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(inspect, r.url): r for r in rows}
            for i, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    _apply_result(row, future.result())
                    run.urls_inspected += 1
                except google_api.QuotaExceeded:
                    run.quota_exhausted = True
                    for f in futures:
                        f.cancel()
                    break
                except Exception as exc:  # one bad URL shouldn't stop the run
                    row.error = str(exc)[:1000]
                    run.urls_failed += 1
                if i % COMMIT_EVERY == 0:
                    db.commit()
                    auth["token"] = google_api.access_token_for(db, prop.connection)  # refreshes near expiry

        pending = db.scalar(
            select(func.count()).where(
                GscUrlInspection.property_id == prop.id, GscUrlInspection.inspected_at.is_(None)
            )
        )
        run.status = "partial" if (pending or run.quota_exhausted) else "success"
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        log.exception("Inspection run %s failed", run_id)
        db.rollback()
        db.execute(
            update(GscInspectionRun)
            .where(GscInspectionRun.id == run_id)
            .values(status="failed", error=str(exc)[:2000], finished_at=datetime.now(UTC))
        )
        db.commit()
    finally:
        db.close()
