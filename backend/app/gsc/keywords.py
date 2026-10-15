"""Keyword explorer: tag every query in a window with keyword types, then filter / sort / page.

Tagging runs as one SQL statement over queries aggregated per window (current, comparison and
"new" look-back), so cost scales with distinct queries rather than daily rows. It still takes
seconds on large sites, so each tagged set is cached (gsc_keyword_cache_*) and every filter,
sort and page is served from the cache until the property is re-synced.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, get_args

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.gsc import brand
from app.models import GscDailyMetric, GscKeywordCacheEntry

# ---------- definitions (keep in sync with docs/ideas.md #5) ----------

LONG_TAIL_WORDS = 4

# Keywords are split into lower-case words once; types are word-list overlaps plus a few
# multi-word phrases. (Regex alternations were ~100x slower on real data.)
QUESTION_WORDS = ["how", "what", "why", "when", "where", "which", "who", "whom", "whose"]
QUESTION_STARTS = [
    "can", "could", "should", "would", "will", "is", "are", "was", "were", "do", "does", "did", "has", "have", "am",
]
QUESTION_PHRASES = ["ways to", "tips for", "guide to", "meaning of"]
BUYING_WORDS = [
    "buy", "buying", "order", "shop", "shopping", "purchase", "price", "prices", "pricing", "cost", "costs",
    "cheap", "cheapest", "affordable", "discount", "discounts", "offer", "offers", "deal", "deals", "coupon",
    "coupons", "promo", "sale", "sales", "best", "top", "review", "reviews", "vs", "versus", "compare",
    "comparison", "alternative", "alternatives", "online", "delivery", "cod", "wholesale", "bulk",
]
BUYING_PHRASES = ["near me", "free shipping", "for sale", "cash on delivery"]


def _phrase_patterns(phrases: list[str]) -> list[str]:
    """LIKE patterns matching whole words inside ' word word ' padded text."""
    return [f"% {p} %" for p in phrases]

NEW_LOOKBACK_DAYS = 90  # "new": impressions now, none in the 90 days before the window
MOVER_MIN_CLICKS = 3  # rising / declining: a change of at least 3 clicks …
MOVER_MIN_SHARE = 0.2  # … and at least 20%
LOW_CTR_MAX_POSITION = 10
LOW_CTR_FACTOR = 0.5  # CTR below half of the site's own typical CTR at that position
EXPECTED_CTR_MIN_IMPRESSIONS = 50  # keywords used to learn the site's typical CTR per position …
EXPECTED_CTR_MIN_KEYWORDS = 5  # … and how many are needed before a position has a typical CTR
HIGH_PERFORMANCE_SHARE = 0.8  # keywords that together bring 80% of clicks

KeywordType = Literal[
    "long_tail",
    "question",
    "buying",
    "new",
    "lost",
    "rising",
    "declining",
    "low_ctr",
    "zero_clicks",
    "high_performance",
]
KEYWORD_TYPES: tuple[str, ...] = get_args(KeywordType)
Segment = Literal["all", "brand", "non_brand"]
SortKey = Literal["clicks", "impressions", "ctr", "position", "click_change", "query"]


def min_impressions(days: int) -> int:
    """Impressions a keyword needs for the low-CTR / zero-click flags: 100 per 28 days, at least 20."""
    return max(20, round(100 * days / 28))


@dataclass
class Window:
    start: date
    end: date
    compare_start: date | None  # None when stored history doesn't cover the comparison window
    compare_end: date | None
    lookback_start: date | None  # None when stored history doesn't cover the "new" look-back
    lookback_end: date | None


def window_for(start: date, end: date, compare_start: date, compare_end: date, first_stored: date | None) -> Window:
    lookback_start = start - timedelta(days=NEW_LOOKBACK_DAYS)

    def covered(since: date) -> bool:
        return first_stored is not None and first_stored <= since

    return Window(
        start=start,
        end=end,
        compare_start=compare_start if covered(compare_start) else None,
        compare_end=compare_end if covered(compare_start) else None,
        lookback_start=lookback_start if covered(lookback_start) else None,
        lookback_end=start - timedelta(days=1) if covered(lookback_start) else None,
    )


def _brand_sql(terms: list[str], params: dict) -> str:
    keys = [brand.normalize(t) for t in terms if brand.normalize(t)]
    if not keys:
        return "false"
    clauses = []
    for i, key in enumerate(keys):
        escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params[f"brand_{i}"] = f"%{escaped}%"
        clauses.append(f"norm like :brand_{i}")
    return "(" + " or ".join(clauses) + ")"


def _tagged_sql(win: Window, terms: list[str], days: int, params: dict) -> str:
    """One row per keyword: metrics, comparison metrics, brand flag and t_<type> flags."""
    params.update(
        start=win.start,
        end=win.end,
        cstart=win.compare_start,
        cend=win.compare_end,
        lstart=win.lookback_start,
        lend=win.lookback_end,
        question_words=QUESTION_WORDS,
        question_starts=QUESTION_STARTS,
        question_phrases=_phrase_patterns(QUESTION_PHRASES),
        buying_words=BUYING_WORDS,
        buying_phrases=_phrase_patterns(BUYING_PHRASES),
        long_tail_words=LONG_TAIL_WORDS,
        mover_clicks=MOVER_MIN_CLICKS,
        mover_share=MOVER_MIN_SHARE,
        low_ctr_pos=LOW_CTR_MAX_POSITION,
        low_ctr_factor=LOW_CTR_FACTOR,
        exp_min_impr=EXPECTED_CTR_MIN_IMPRESSIONS,
        exp_min_keywords=EXPECTED_CTR_MIN_KEYWORDS,
        min_impr=min_impressions(days),
        hp_share=HIGH_PERFORMANCE_SHARE,
    )
    has_compare = win.compare_start is not None
    has_lookback = win.lookback_start is not None

    if has_compare:
        prev_cte = """
            prev as (
                select query, sum(clicks) as clicks, sum(impressions) as impressions,
                       sum(position * impressions) as wpos
                from gsc_query_metrics
                where property_id = :pid and date between :cstart and :cend
                group by query
            )"""
    else:
        prev_cte = """
            prev as (select null::text as query, 0::bigint as clicks, 0::bigint as impressions,
                            0::float as wpos where false)"""
    if has_lookback:
        seen_cte = """
            seen as (
                select distinct query from gsc_query_metrics
                where property_id = :pid and date between :lstart and :lend and impressions > 0
            )"""
    else:
        seen_cte = "seen as (select null::text as query where false)"
    new_flag = "coalesce(c.impressions > 0 and s.query is null, false)" if has_lookback else "false"
    movers = "true" if has_compare else "false"

    return f"""
        with cur as (
            select query, min(query_norm) as norm, sum(clicks) as clicks, sum(impressions) as impressions,
                   sum(position * impressions) as wpos
            from gsc_query_metrics
            where property_id = :pid and date between :start and :end
            group by query
        ),
        {prev_cte},
        {seen_cte},
        joined as (
            select coalesce(c.query, p.query) as query,
                   coalesce(c.norm, regexp_replace(lower(p.query), '[[:space:][:punct:]]', '', 'g')) as norm,
                   coalesce(c.clicks, 0) as clicks,
                   coalesce(c.impressions, 0) as impressions,
                   case when c.impressions > 0 then c.wpos / c.impressions end as position,
                   p.clicks as prev_clicks,
                   p.impressions as prev_impressions,
                   case when p.impressions > 0 then p.wpos / p.impressions end as prev_position,
                   {new_flag} as is_new
            from cur c
            full outer join prev p on p.query = c.query
            left join seen s on s.query = c.query
        ),
        branded as (
            select j.*, {_brand_sql(terms, params)} as brand from joined j
        ),
        -- The site's typical CTR per rounded position, separately for brand and non-brand
        -- (brand searches click far more). Overall clicks / impressions, not the median: on
        -- real sites most keywords at positions 5+ have zero clicks, so the median is 0.
        expected as (
            select round(position::numeric) as bucket, brand,
                   sum(clicks)::float / sum(impressions) as ctr
            from branded
            where impressions >= :exp_min_impr and position <= :low_ctr_pos + 0.5
            group by 1, 2
            having count(*) >= :exp_min_keywords
        ),
        ranked as (
            select b.*,
                   case when b.impressions > 0 then b.clicks::float / b.impressions else 0 end as ctr,
                   e.ctr as expected_ctr,
                   sum(b.clicks) over (order by b.clicks desc, b.impressions desc, b.query
                                       rows unbounded preceding) - b.clicks as clicks_before,
                   sum(b.clicks) over () as total_clicks
            from branded b
            left join expected e on e.bucket = round(b.position::numeric) and e.brand = b.brand
        ),
        words as (
            select r.*, array_remove(regexp_split_to_array(lower(r.query), '[^[:alnum:]]+'), '') as words
            from ranked r
        ),
        tok as (
            select w.*, ' ' || array_to_string(w.words, ' ') || ' ' as padded from words w
        )
        select query, clicks, impressions, ctr, position,
               prev_clicks, prev_impressions, prev_position, expected_ctr,
               clicks - coalesce(prev_clicks, 0) as click_change,
               brand,
               cardinality(words) >= :long_tail_words as t_long_tail,
               (words && cast(:question_words as text[])
                    or coalesce(words[1] = any(cast(:question_starts as text[])), false)
                    or position('?' in query) > 0
                    or padded like any(cast(:question_phrases as text[]))) as t_question,
               (words && cast(:buying_words as text[])
                    or padded like any(cast(:buying_phrases as text[]))) as t_buying,
               is_new as t_new,
               {movers} and coalesce(prev_clicks, 0) > 0 and clicks = 0 as t_lost,
               {movers} and clicks > 0
                   and clicks - coalesce(prev_clicks, 0)
                       >= greatest(:mover_clicks, :mover_share * coalesce(prev_clicks, 0)) as t_rising,
               {movers} and coalesce(prev_clicks, 0) > 0
                   and prev_clicks - clicks >= greatest(:mover_clicks, :mover_share * prev_clicks) as t_declining,
               coalesce(impressions >= :min_impr and position <= :low_ctr_pos
                        and ctr < :low_ctr_factor * expected_ctr, false) as t_low_ctr,
               impressions >= :min_impr and clicks = 0 as t_zero_clicks,
               clicks > 0 and clicks_before < :hp_share * total_clicks as t_high_performance
        from tok
    """


CACHE_ENTRIES_PER_PROPERTY = 8
_METRIC_COLUMNS = (
    "query, clicks, impressions, ctr, position, prev_clicks, prev_impressions, prev_position, expected_ctr, "
    "click_change, brand"
)
_ROW_COLUMNS = _METRIC_COLUMNS + ", " + ", ".join(f"t_{t}" for t in KEYWORD_TYPES)
# When filling the cache, an unknown (null) flag means "not this type".
_INSERT_SELECT = (
    _METRIC_COLUMNS.replace("brand", "coalesce(brand, false)")
    + ", "
    + ", ".join(f"coalesce(t_{t}, false)" for t in KEYWORD_TYPES)
)


def cache_key(win: Window, days: int, terms: list[str]) -> str:
    parts = [win.start, win.end, win.compare_start, win.lookback_start, days, sorted(brand.normalize(t) for t in terms)]
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def _cached_entry(db: Session, property_id: int, win: Window, days: int, terms: list[str], synced_at) -> int:
    """Id of a cache entry for this key, (re)building it if missing or older than the last sync."""
    key = cache_key(win, days, terms)
    entry = db.scalars(
        select(GscKeywordCacheEntry).where(
            GscKeywordCacheEntry.property_id == property_id, GscKeywordCacheEntry.cache_key == key
        )
    ).first()
    if entry and (synced_at is None or entry.built_at >= synced_at):
        return entry.id
    if entry:
        db.delete(entry)
        db.flush()

    # Row estimates for these CTEs are far off, which makes Postgres JIT-compile for ~1.5 s,
    # and the per-query aggregations spill to disk with the default 4 MB work_mem.
    db.execute(text("set local jit = off"))
    db.execute(text("set local work_mem = '128MB'"))
    entry = GscKeywordCacheEntry(property_id=property_id, cache_key=key)
    db.add(entry)
    db.flush()
    params: dict = {"pid": property_id, "entry_id": entry.id}
    tagged = _tagged_sql(win, terms, days, params)
    db.execute(
        text(
            f"insert into gsc_keyword_cache_rows (entry_id, {_ROW_COLUMNS}) "
            f"select :entry_id, {_INSERT_SELECT} from ({tagged}) t"
        ),
        params,
    )
    # Keep only the most recent few sets per property.
    stale = db.scalars(
        select(GscKeywordCacheEntry.id)
        .where(GscKeywordCacheEntry.property_id == property_id)
        .order_by(GscKeywordCacheEntry.built_at.desc(), GscKeywordCacheEntry.id.desc())
        .offset(CACHE_ENTRIES_PER_PROPERTY)
    ).all()
    if stale:
        db.execute(delete(GscKeywordCacheEntry).where(GscKeywordCacheEntry.id.in_(stale)))
    db.commit()
    return entry.id


def explore(
    db: Session,
    property_id: int,
    win: Window,
    days: int,
    terms: list[str],
    synced_at,
    segment: Segment,
    types: list[str],
    search: str | None,
    sort: SortKey,
    descending: bool,
    limit: int,
    offset: int,
) -> tuple[dict[str, int], int, list[dict]]:
    """Returns (counts per type within the brand segment, total matching rows, one page of rows)."""
    entry_id = _cached_entry(db, property_id, win, days, terms, synced_at)

    seg_where = {"all": "true", "brand": "brand", "non_brand": "not brand"}[segment]
    # Lost keywords have no current impressions; they're only listed when "lost" is selected.
    visible = "true" if "lost" in types else "impressions > 0"
    type_where = " and ".join(f"t_{t}" for t in types) or "true"
    q: dict = {"entry_id": entry_id}
    search_where = "true"
    if search and search.strip():
        q["search"] = f"%{search.strip().lower()}%"
        search_where = "lower(query) like :search"
    base = "from gsc_keyword_cache_rows where entry_id = :entry_id"

    counts_sql = ", ".join(
        f"count(*) filter (where t_{t}{'' if t == 'lost' else ' and impressions > 0'}) as {t}" for t in KEYWORD_TYPES
    )
    row = db.execute(
        text(f"select count(*) filter (where impressions > 0) as all_kw, {counts_sql} {base} and {seg_where}"), q
    ).mappings().one()
    counts = {"all": row["all_kw"], **{t: row[t] for t in KEYWORD_TYPES}}

    where = f"{seg_where} and {visible} and {type_where} and {search_where}"
    total = db.execute(text(f"select count(*) {base} and {where}"), q).scalar_one()
    direction = "desc" if descending else "asc"
    rows = db.execute(
        text(
            f"select {_ROW_COLUMNS} {base} and {where} "
            f"order by {sort} {direction} nulls last, clicks desc, impressions desc, query "
            "limit :limit offset :offset"
        ),
        {**q, "limit": limit, "offset": offset},
    ).mappings().all()

    items = []
    for r in rows:
        item = {k: v for k, v in r.items() if not k.startswith("t_")}
        item["types"] = [t for t in KEYWORD_TYPES if r[f"t_{t}"]]
        items.append(item)
    return counts, total, items


DEFAULT_DAYS = 28


def warm_default_cache(db: Session, prop) -> None:
    """Pre-build the default view (last 28 days vs previous period) right after a sync."""
    first, last = db.execute(
        select(func.min(GscDailyMetric.date), func.max(GscDailyMetric.date)).where(
            GscDailyMetric.property_id == prop.id
        )
    ).one()
    if last is None:
        return
    start = last - timedelta(days=DEFAULT_DAYS - 1)
    win = window_for(start, last, start - timedelta(days=DEFAULT_DAYS), start - timedelta(days=1), first)
    _cached_entry(db, prop.id, win, DEFAULT_DAYS, brand.effective_terms(prop.brand_terms, prop.site_url), prop.last_synced_at)
