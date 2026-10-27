"""Page explorer: every page in a window with its page type, comparison metrics and filter flags.

Page types come from the URL path (Shopify layout: /products/, /collections/, /blogs/, /pages/).
Filters reuse the keyword rules (keywords.py) so pages and keywords are judged the same way; the
typical CTR is learned from pages, though — page CTR runs far lower than keyword CTR.
Pages per property are thousands, not millions, so this is a live query with no cache.
"""

from typing import Literal, get_args
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.gsc import keywords, opportunities

PageType = Literal["home", "collections", "products", "blogs", "pages", "other", "shopping"]
PAGE_TYPES: tuple[str, ...] = get_args(PageType)
PageFilter = Literal["low_ctr", "high_performance", "rising", "declining", "new", "lost", "zero_clicks", "striking"]
PAGE_FILTERS: tuple[str, ...] = get_args(PageFilter)
SortKey = Literal["clicks", "impressions", "ctr", "position", "click_change", "page"]

# First path segment → page type. Shopify first; common WordPress / WooCommerce names too.
_SEGMENT_TYPES = {
    "products": "products",
    "product": "products",
    "collections": "collections",
    "collection": "collections",
    "product-category": "collections",
    "shop": "collections",
    "blogs": "blogs",
    "blog": "blogs",
    "news": "blogs",
    "articles": "blogs",
    "pages": "pages",
}


def page_type(url: str) -> str:
    """"https://x.com/collections/sale/products/a" → "products"; "?variant=" listing URLs → "shopping"."""
    if "?" in url:
        return "shopping"  # Shopping / free-listing URLs (…?variant=…&utm_…)
    path = [s for s in urlsplit(url).path.lower().split("/") if s]
    if not path:
        return "home"
    if "products" in path:  # Shopify also serves products under /collections/<c>/products/<p>
        return "products"
    return _SEGMENT_TYPES.get(path[0], "other")


def page_rows(db: Session, property_id: int, win: keywords.Window, days: int) -> list[dict]:
    """One dict per page seen in the window or the comparison window, with type and filter flags."""
    params = {
        "pid": property_id,
        "start": win.start,
        "end": win.end,
        "cstart": win.compare_start,
        "cend": win.compare_end,
        "lstart": win.lookback_start,
        "lend": win.lookback_end,
        "max_pos": keywords.LOW_CTR_MAX_POSITION,
        "exp_min_impr": keywords.EXPECTED_CTR_MIN_IMPRESSIONS,
        "exp_min_pages": keywords.EXPECTED_CTR_MIN_KEYWORDS,
    }
    has_compare = win.compare_start is not None
    has_lookback = win.lookback_start is not None
    prev_cte = (
        """prev as (
            select page, sum(clicks) as clicks, sum(impressions) as impressions,
                   sum(position * impressions) / nullif(sum(impressions), 0) as position
            from gsc_page_metrics
            where property_id = :pid and date between :cstart and :cend
            group by page
        )"""
        if has_compare
        else "prev as (select null::text as page, 0::bigint as clicks, 0::bigint as impressions, null::float as position where false)"
    )
    seen_cte = (
        """seen as (
            select distinct page from gsc_page_metrics
            where property_id = :pid and date between :lstart and :lend and impressions > 0
        )"""
        if has_lookback
        else "seen as (select null::text as page where false)"
    )
    rows = db.execute(
        text(f"""
            with cur as (
                select page, sum(clicks) as clicks, sum(impressions) as impressions,
                       sum(position * impressions) / nullif(sum(impressions), 0) as position
                from gsc_page_metrics
                where property_id = :pid and date between :start and :end
                group by page
            ),
            {prev_cte},
            {seen_cte},
            -- The site's typical page CTR per rounded position (Shopping "?" URLs left out)
            expected as (
                select round(position::numeric) as bucket, sum(clicks)::float / sum(impressions) as ctr
                from cur
                where impressions >= :exp_min_impr and position <= :max_pos + 0.5 and strpos(page, '?') = 0
                group by 1
                having count(*) >= :exp_min_pages
            )
            select coalesce(c.page, p.page), coalesce(c.clicks, 0), coalesce(c.impressions, 0), c.position,
                   p.clicks, p.impressions, p.position, e.ctr,
                   coalesce(c.impressions, 0) > 0 and s.page is null
            from cur c
            full outer join prev p on p.page = c.page
            left join seen s on s.page = coalesce(c.page, p.page)
            left join expected e on e.bucket = round(c.position::numeric)
        """),
        params,
    ).all()

    min_impr = keywords.min_impressions(days)
    pages = []
    for page, clicks, impr, pos, p_clicks, p_impr, p_pos, expected, unseen in rows:
        ctr = clicks / impr if impr else 0.0
        kind = page_type(page)
        flags = []
        if (
            kind != "shopping"
            and expected is not None
            and impr >= min_impr
            and pos is not None
            and pos <= keywords.LOW_CTR_MAX_POSITION
            and ctr < keywords.LOW_CTR_FACTOR * expected
        ):
            flags.append("low_ctr")
        if impr >= min_impr and clicks == 0:
            flags.append("zero_clicks")
        # Home ranks for thousands of searches, so its average position says little about any one of them.
        if (
            kind not in ("shopping", "home")
            and impr >= min_impr
            and pos is not None
            and opportunities.STRIKING_MIN_POSITION <= pos <= opportunities.STRIKING_MAX_POSITION
        ):
            flags.append("striking")
        # Unlike keywords, pages need real visibility to count as new: on real data most "new" pages had
        # 1-5 impressions. Shopping URLs churn (Google rotates ?variant=…), so they're never new or lost.
        if has_lookback and unseen and impr >= min_impr and kind != "shopping":
            flags.append("new")
        if has_compare:
            prev = p_clicks or 0
            moved = keywords.MOVER_MIN_CLICKS
            if prev > 0 and clicks == 0 and kind != "shopping":
                flags.append("lost")
            if clicks > 0 and clicks - prev >= max(moved, keywords.MOVER_MIN_SHARE * prev):
                flags.append("rising")
            if prev > 0 and prev - clicks >= max(moved, keywords.MOVER_MIN_SHARE * prev):
                flags.append("declining")
        pages.append(
            {
                "page": page,
                "type": kind,
                "clicks": clicks,
                "impressions": impr,
                "ctr": ctr,
                "position": pos,
                "prev_clicks": p_clicks if has_compare else None,
                "prev_impressions": p_impr if has_compare else None,
                "prev_position": p_pos if has_compare else None,
                "click_change": clicks - (p_clicks or 0),
                "expected_ctr": expected,
                "flags": flags,
            }
        )

    # High performance: the pages that together bring 80% of clicks.
    total = sum(p["clicks"] for p in pages)
    running = 0
    for p in sorted(pages, key=lambda p: (-p["clicks"], -p["impressions"], p["page"])):
        if p["clicks"] > 0 and running < keywords.HIGH_PERFORMANCE_SHARE * total:
            p["flags"].append("high_performance")
        running += p["clicks"]
    return pages


def summarize(pages: list[dict], has_compare: bool) -> list[dict]:
    """Totals per page type (current and comparison window), in PAGE_TYPES order, empty types dropped."""
    out = []
    for kind in PAGE_TYPES:
        group = [p for p in pages if p["type"] == kind]
        if not group:
            continue
        clicks = sum(p["clicks"] for p in group)
        impr = sum(p["impressions"] for p in group)
        wpos = sum((p["position"] or 0) * p["impressions"] for p in group)
        prev_clicks = sum(p["prev_clicks"] or 0 for p in group)
        prev_impr = sum(p["prev_impressions"] or 0 for p in group)
        prev_wpos = sum((p["prev_position"] or 0) * (p["prev_impressions"] or 0) for p in group)
        out.append(
            {
                "type": kind,
                "pages": sum(1 for p in group if p["impressions"] > 0),
                "clicks": clicks,
                "impressions": impr,
                "ctr": clicks / impr if impr else 0.0,
                "position": wpos / impr if impr else None,
                "prev_clicks": prev_clicks if has_compare else None,
                "prev_impressions": prev_impr if has_compare else None,
                "prev_ctr": (prev_clicks / prev_impr if prev_impr else 0.0) if has_compare else None,
                "prev_position": (prev_wpos / prev_impr if prev_impr else None) if has_compare else None,
            }
        )
    return out


def explore(
    pages: list[dict],
    page_types: list[str],
    filters: list[str],
    search: str | None,
    sort: str,
    descending: bool,
    limit: int,
    offset: int,
) -> tuple[dict[str, int], int, list[dict]]:
    """(chip counts within the chosen page types and filters, total matches, one page of rows)."""
    scoped = [p for p in pages if not page_types or p["type"] in page_types]
    if search:
        needle = search.strip().lower()
        scoped = [p for p in scoped if needle in p["page"].lower()]
    matches = [p for p in scoped if all(f in p["flags"] for f in filters)]
    counts = {"all": len(scoped)} | {f: sum(1 for p in matches if f in p["flags"]) for f in PAGE_FILTERS}

    def key(p: dict):
        value = p[sort]
        if value is None:  # lost pages have no position; keep them last either way
            return (1, 0)
        return (0, -value if descending and sort != "page" else value)

    rows = sorted(matches, key=lambda p: (key(p), -p["clicks"], p["page"]))
    if sort == "page" and descending:
        rows.reverse()
    return counts, len(matches), rows[offset : offset + limit]
