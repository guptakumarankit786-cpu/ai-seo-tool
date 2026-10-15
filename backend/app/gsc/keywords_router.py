from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import brand, keywords, seasonal, sync
from app.gsc.router import Compare, _window, comparison_window
from app.models import GscDailyMetric, GscProperty

router = APIRouter(prefix="/api/gsc/properties/{property_id}", tags=["gsc-keywords"])

DbDep = Annotated[Session, Depends(get_db)]


class KeywordRow(BaseModel):
    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float | None  # null for lost keywords (no impressions now)
    prev_clicks: int | None
    prev_impressions: int | None
    prev_position: float | None
    click_change: int
    expected_ctr: float | None  # site's typical CTR at this position
    brand: bool
    types: list[keywords.KeywordType]


class Definitions(BaseModel):
    long_tail_words: int
    new_lookback_days: int
    mover_min_clicks: int
    mover_min_share: float
    low_ctr_max_position: int
    low_ctr_factor: float
    min_impressions: int
    high_performance_share: float


class KeywordsOut(BaseModel):
    start_date: date
    end_date: date
    compare: Compare
    compare_available: bool  # needed for lost / rising / declining
    new_available: bool  # needed for new
    definitions: Definitions
    counts: dict[str, int]
    total: int
    items: list[KeywordRow]


@router.get("/keywords", response_model=KeywordsOut)
def explore_keywords(
    property_id: int,
    db: DbDep,
    days: Annotated[int, Query(ge=1, le=sync.MAX_HISTORY_DAYS)] = 28,
    compare: Compare = "previous",
    segment: keywords.Segment = "all",
    types: Annotated[list[keywords.KeywordType] | None, Query(description="Keyword types; combined with AND")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: keywords.SortKey = "clicks",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Every keyword in the window, tagged with keyword types, filterable and sortable."""
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")

    start, end = _window(db, prop.id, days)
    compare_start, compare_end = comparison_window(start, end, compare)
    first_stored = db.scalar(select(func.min(GscDailyMetric.date)).where(GscDailyMetric.property_id == prop.id))
    win = keywords.window_for(start, end, compare_start, compare_end, first_stored)

    counts, total, items = keywords.explore(
        db,
        prop.id,
        win,
        days,
        brand.effective_terms(prop.brand_terms, prop.site_url),
        prop.competitor_terms or [],
        prop.last_synced_at,
        segment,
        list(dict.fromkeys(types or [])),
        search,
        sort,
        order == "desc",
        limit,
        offset,
    )
    return KeywordsOut(
        start_date=start,
        end_date=end,
        compare=compare,
        compare_available=win.compare_start is not None,
        new_available=win.lookback_start is not None,
        definitions=Definitions(
            long_tail_words=keywords.LONG_TAIL_WORDS,
            new_lookback_days=keywords.NEW_LOOKBACK_DAYS,
            mover_min_clicks=keywords.MOVER_MIN_CLICKS,
            mover_min_share=keywords.MOVER_MIN_SHARE,
            low_ctr_max_position=keywords.LOW_CTR_MAX_POSITION,
            low_ctr_factor=keywords.LOW_CTR_FACTOR,
            min_impressions=keywords.min_impressions(days),
            high_performance_share=keywords.HIGH_PERFORMANCE_SHARE,
        ),
        counts=counts,
        total=total,
        items=[KeywordRow(**i) for i in items],
    )


# ---------- seasonal & spikes (monthly history) ----------

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class MonthlyRow(BaseModel):
    query: str
    brand: bool
    impressions: list[int]  # aligned with `months`
    total_impressions: int
    total_clicks: int


class SeasonalRow(MonthlyRow):
    peak_months: list[int]  # calendar months 1-12
    status: seasonal.Status


class SpikeRow(MonthlyRow):
    spike_month: date
    spike_impressions: int
    share: float


class MonthlyOut(BaseModel):
    months: list[date]
    available: bool  # false until at least one full month of history is stored
    min_impressions: int
    total: int


class SeasonalOut(MonthlyOut):
    repeating_months: list[str]  # calendar months seen in both years: the only ones checkable
    counts: dict[str, int]
    items: list[SeasonalRow]


class SpikesOut(MonthlyOut):
    items: list[SpikeRow]


def _monthly_rows(db: Session, property_id: int):
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    cache = seasonal.monthly(db, prop)
    terms = brand.effective_terms(prop.brand_terms, prop.site_url)
    return cache, terms


def _in_segment(is_brand: bool, segment: keywords.Segment) -> bool:
    return segment == "all" or (segment == "brand") == is_brand


def _base(query: str, s: dict, terms: list[str]) -> dict:
    return {
        "query": query,
        "brand": brand.is_brand(query, terms),
        "impressions": s["impressions"],
        "total_impressions": sum(s["impressions"]),
        "total_clicks": sum(s["clicks"]),
    }


STATUS_ORDER = {"coming_up": 0, "in_season": 1, "off_season": 2}


@router.get("/keywords/seasonal", response_model=SeasonalOut)
def seasonal_keywords(
    property_id: int,
    db: DbDep,
    segment: keywords.Segment = "all",
    status: Annotated[seasonal.Status | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Keywords whose peak repeats in the same calendar months in both years of history."""
    cache, terms = _monthly_rows(db, property_id)
    months = cache.months if cache else []
    today = date.today()
    found = []
    for query, s in (cache.series.items() if cache else []):
        hit = seasonal.find_seasonal(query, months, s["impressions"], today)
        if hit:
            row = SeasonalRow(**_base(query, s, terms), peak_months=hit.peak_months, status=hit.status)
            if _in_segment(row.brand, segment):
                found.append(row)
    counts = {k: sum(r.status == k for r in found) for k in STATUS_ORDER}
    if status:
        found = [r for r in found if r.status == status]
    found.sort(key=lambda r: (STATUS_ORDER[r.status], -r.total_impressions, r.query))
    return SeasonalOut(
        months=months,
        available=bool(months),
        min_impressions=seasonal.MIN_TOTAL_IMPRESSIONS,
        repeating_months=[MONTH_NAMES[m - 1] for m in seasonal.repeating_months(months)],
        counts=counts,
        total=len(found),
        items=found[offset : offset + limit],
    )


@router.get("/keywords/spikes", response_model=SpikesOut)
def spike_keywords(
    property_id: int,
    db: DbDep,
    segment: keywords.Segment = "all",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """One-off surges: one month holds most of a keyword's impressions and it isn't seasonal."""
    cache, terms = _monthly_rows(db, property_id)
    months = cache.months if cache else []
    today = date.today()
    found = []
    for query, s in (cache.series.items() if cache else []):
        if seasonal.find_seasonal(query, months, s["impressions"], today):
            continue
        hit = seasonal.find_spike(query, months, s["impressions"])
        if hit:
            row = SpikeRow(
                **_base(query, s, terms),
                spike_month=hit.month,
                spike_impressions=hit.impressions,
                share=hit.share,
            )
            if _in_segment(row.brand, segment):
                found.append(row)
    found.sort(key=lambda r: (r.spike_month, r.spike_impressions), reverse=True)
    return SpikesOut(
        months=months,
        available=bool(months),
        min_impressions=seasonal.MIN_TOTAL_IMPRESSIONS,
        total=len(found),
        items=found[offset : offset + limit],
    )
