"""Page-level keyword opportunities: striking distance and cannibalisation.

Both need query+page data, which is too large to store for 16 months. It's pulled live from
Search Console (free) the first time a range is opened and cached briefly (gsc_query_page_cache_*).
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from app.gsc import google_api
from app.gsc.keywords import Segment, brand_sql, min_impressions
from app.models import GscProperty, GscQueryPageCacheEntry, GscQueryPageCacheRow

log = logging.getLogger(__name__)

MAX_DAYS = 90  # larger ranges take minutes to pull live; rankings "now" are what matter here
CACHE_MAX_AGE = timedelta(hours=24)
CACHE_ENTRIES_PER_PROPERTY = 3
INSERT_BATCH = 5_000

# Striking distance: the keyword's main page ranks in this band …
STRIKING_MIN_POSITION = 4
STRIKING_MAX_POSITION = 20
# … and potential = impressions × (typical CTR at this position − current CTR).
TARGET_POSITION = 3
TYPICAL_CTR_MIN_IMPRESSIONS = 50
TYPICAL_CTR_MIN_KEYWORDS = 5

# Cannibalisation: 2+ of the site's pages each get at least this share of a keyword's impressions.
CANNIBAL_MIN_SHARE = 0.10
CANNIBAL_MIN_PAGES = 2
# 3+ competing pages all ranking in the top 3 is Google showing sitelinks for a navigational
# search (usually brand) — normal, so it's labelled rather than treated as a problem.
SITELINKS_MIN_PAGES = 3
SITELINKS_MAX_POSITION = 3

StrikingSort = Literal["potential", "impressions", "clicks", "position"]


def cached_entry(db: Session, prop: GscProperty, start: date, end: date) -> GscQueryPageCacheEntry:
    """The query+page pull for this range, fetched from Google if missing or stale."""
    # Two requests opening the same range at once would both pull from Google; the second waits
    # here (until the first commits) and then finds the fresh entry.
    db.execute(text("select pg_advisory_xact_lock(hashtext('gsc_query_page_cache'), :pid)"), {"pid": prop.id})
    entry = db.scalars(
        select(GscQueryPageCacheEntry).where(
            GscQueryPageCacheEntry.property_id == prop.id,
            GscQueryPageCacheEntry.start_date == start,
            GscQueryPageCacheEntry.end_date == end,
        )
    ).first()
    now = datetime.now(UTC)
    fresh = (
        entry is not None
        and entry.built_at > now - CACHE_MAX_AGE
        and (prop.last_synced_at is None or entry.built_at >= prop.last_synced_at)
        # UNLOGGED rows are emptied by Postgres after an unclean shutdown; the entry survives
        and db.scalar(select(select(GscQueryPageCacheRow.id).where(GscQueryPageCacheRow.entry_id == entry.id).exists()))
    )
    if fresh:
        return entry
    if entry:
        db.delete(entry)
        db.flush()

    token = google_api.access_token_for(db, prop.connection)
    rows = google_api.search_analytics(token, prop.site_url, start, end, ["query", "page"])

    entry = GscQueryPageCacheEntry(property_id=prop.id, start_date=start, end_date=end)
    db.add(entry)
    db.flush()
    values = [
        {
            "entry_id": entry.id,
            "query": r["keys"][0],
            "page": r["keys"][1],
            "clicks": int(r["clicks"]),
            "impressions": int(r["impressions"]),
            "position": r["position"],
        }
        for r in rows
    ]
    for i in range(0, len(values), INSERT_BATCH):
        db.execute(insert(GscQueryPageCacheRow), values[i : i + INSERT_BATCH])
    # Fresh statistics: without them Postgres expects a near-empty table and picks nested-loop
    # joins that take minutes on tens of thousands of rows.
    db.execute(text("analyze gsc_query_page_cache_rows"))

    stale = db.scalars(
        select(GscQueryPageCacheEntry.id)
        .where(GscQueryPageCacheEntry.property_id == prop.id)
        .order_by(GscQueryPageCacheEntry.built_at.desc(), GscQueryPageCacheEntry.id.desc())
        .offset(CACHE_ENTRIES_PER_PROPERTY)
    ).all()
    if stale:
        db.execute(delete(GscQueryPageCacheEntry).where(GscQueryPageCacheEntry.id.in_(stale)))
    db.commit()
    log.info("Pulled %s query+page rows for property %s (%s..%s)", len(values), prop.id, start, end)
    return entry


def _segment_where(segment: Segment) -> str:
    return {"all": "true", "brand": "brand", "non_brand": "not brand"}[segment]


def _typical_ctr(db: Session, entry_id: int, brand: str, params: dict) -> dict:
    """The site's own CTR around the target position, for brand and non-brand keywords.

    Clicks ÷ impressions of keyword/page rows at the target position with enough impressions.
    A segment with too few keywords there falls back to the pooled figure.
    """
    rows = db.execute(
        text(
            f"""
            select {brand} as brand, sum(clicks) as clicks, sum(impressions) as impressions, count(*) as n
            from gsc_query_page_cache_rows
            where entry_id = :entry_id and impressions >= :typ_min_impr
                  and round(position::numeric) = :target_pos
            group by 1
            """
        ),
        params,
    ).all()
    total_clicks = sum(r.clicks for r in rows)
    total_impressions = sum(r.impressions for r in rows)
    pooled = total_clicks / total_impressions if total_impressions else None
    by_brand = {r.brand: r.clicks / r.impressions for r in rows if r.n >= TYPICAL_CTR_MIN_KEYWORDS and r.impressions}
    return {"typical_brand": by_brand.get(True, pooled), "typical_non_brand": by_brand.get(False, pooled)}


def striking_distance(
    db: Session,
    entry_id: int,
    terms: list[str],
    days: int,
    segment: Segment,
    sort: StrikingSort,
    limit: int,
    offset: int,
) -> tuple[int, list[dict]]:
    """Keywords whose main page ranks 4–20, with potential extra clicks at position 3."""
    params: dict = {
        "entry_id": entry_id,
        "min_pos": STRIKING_MIN_POSITION,
        "max_pos": STRIKING_MAX_POSITION,
        "min_impr": min_impressions(days),
        "target_pos": TARGET_POSITION,
        "typ_min_impr": TYPICAL_CTR_MIN_IMPRESSIONS,
        "typ_min_kw": TYPICAL_CTR_MIN_KEYWORDS,
        "limit": limit,
        "offset": offset,
    }
    brand = brand_sql(terms, params, column="query_norm")
    params.update(_typical_ctr(db, entry_id, brand, params))
    order = {
        "potential": "potential desc nulls last, impressions desc",
        "impressions": "impressions desc",
        "clicks": "clicks desc, impressions desc",
        "position": "position asc, impressions desc",
    }[sort]
    # Per-keyword totals and the main page come from window functions over one scan, and the
    # typical CTRs arrive as parameters: any join between per-keyword sets got row estimates of
    # ~1 from the planner and turned into nested loops taking minutes on real data.
    sql = f"""
        with r as (
            select query, page, clicks, impressions, position, {brand} as brand
            from gsc_query_page_cache_rows
            -- Shopping / free-listing URLs (?variant=…&utm_…) aren't organic pages.
            where entry_id = :entry_id and position('?' in page) = 0
        ),
        ranked as (
            select r.*,
                   sum(impressions) over w as q_impressions,
                   count(*) over w as q_pages,
                   bool_or(brand) over w as q_brand,
                   row_number() over (partition by query order by impressions desc, clicks desc, page) as rn
            from r
            window w as (partition by query)
        ),
        main as (
            select *, case when q_brand then cast(:typical_brand as float)
                           else cast(:typical_non_brand as float) end as target_ctr
            from ranked
            where rn = 1 and position between :min_pos and :max_pos and q_impressions >= :min_impr
        ),
        result as (
            select query, page, clicks, impressions, position,
                   clicks::float / impressions as ctr,
                   q_pages - 1 as other_pages, q_brand as brand, target_ctr,
                   greatest(0, round(impressions * (target_ctr - clicks::float / impressions)))::int as potential
            from main
        )
    """
    where = _segment_where(segment).replace("brand", "result.brand")
    total = db.execute(text(f"{sql} select count(*) from result where {where}"), params).scalar_one()
    rows = db.execute(
        text(f"{sql} select * from result where {where} order by {order}, query limit :limit offset :offset"), params
    ).mappings().all()
    return total, [dict(r) for r in rows]


def cannibalisation(
    db: Session,
    entry_id: int,
    terms: list[str],
    days: int,
    segment: Segment,
    limit: int,
    offset: int,
) -> tuple[int, list[dict]]:
    """Keywords where 2+ pages each take ≥ 10% of impressions, with every competing page.

    Likely-sitelinks cases are flagged and listed after the real ones.
    """
    params: dict = {
        "entry_id": entry_id,
        "min_impr": min_impressions(days),
        "min_share": CANNIBAL_MIN_SHARE,
        "min_pages": CANNIBAL_MIN_PAGES,
        "sitelinks_pages": SITELINKS_MIN_PAGES,
        "sitelinks_pos": SITELINKS_MAX_POSITION,
        "limit": limit,
        "offset": offset,
    }
    brand = brand_sql(terms, params, column="query_norm")
    sql = f"""
        with r as (
            select query, page, clicks, impressions, position, {brand} as brand
            from gsc_query_page_cache_rows
            -- Shopping / free-listing URLs (?variant=…&utm_…) aren't organic pages.
            where entry_id = :entry_id and position('?' in page) = 0
        ),
        -- Per-keyword totals via window functions (no self-join; see striking_distance).
        shares as (
            select r.*,
                   bool_or(brand) over w as q_brand,
                   sum(clicks) over w as q_clicks,
                   sum(impressions) over w as q_impressions,
                   impressions::float / sum(impressions) over w as share
            from r
            window w as (partition by query)
        ),
        competing as (
            select * from shares where q_impressions >= :min_impr and share >= :min_share
        ),
        result as (
            select query, q_brand as brand, q_clicks as clicks, q_impressions as impressions,
                   count(*) as competing_pages,
                   count(*) >= :sitelinks_pages and max(position) <= :sitelinks_pos as sitelinks_likely,
                   json_agg(json_build_object(
                       'page', page, 'clicks', clicks, 'impressions', impressions,
                       'position', position, 'share', share
                   ) order by impressions desc) as pages
            from competing
            group by query, q_brand, q_clicks, q_impressions
            having count(*) >= :min_pages
        )
    """
    where = _segment_where(segment).replace("brand", "result.brand")
    total = db.execute(text(f"{sql} select count(*) from result where {where}"), params).scalar_one()
    rows = db.execute(
        text(f"{sql} select * from result where {where} order by sitelinks_likely, impressions desc, query limit :limit offset :offset"),
        params,
    ).mappings().all()
    return total, [dict(r) for r in rows]
