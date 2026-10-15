from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import brand, keywords, sync
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
