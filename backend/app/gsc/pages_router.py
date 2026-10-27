from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import keywords, opportunities, pages, sync
from app.gsc.router import Compare, _window, comparison_window
from app.models import GscDailyMetric, GscProperty

router = APIRouter(prefix="/api/gsc/properties/{property_id}", tags=["gsc-pages"])

DbDep = Annotated[Session, Depends(get_db)]


class PageRow(BaseModel):
    page: str
    type: pages.PageType
    clicks: int
    impressions: int
    ctr: float
    position: float | None  # null for lost pages (no impressions now)
    prev_clicks: int | None
    prev_impressions: int | None
    prev_position: float | None
    click_change: int
    expected_ctr: float | None  # site's typical page CTR at this position
    flags: list[pages.PageFilter]


class PageGroup(BaseModel):
    type: pages.PageType
    pages: int
    clicks: int
    impressions: int
    ctr: float
    position: float | None
    prev_clicks: int | None  # null when stored history doesn't cover the comparison window
    prev_impressions: int | None
    prev_ctr: float | None
    prev_position: float | None


class Definitions(BaseModel):
    new_lookback_days: int
    mover_min_clicks: int
    mover_min_share: float
    low_ctr_max_position: int
    low_ctr_factor: float
    min_impressions: int
    high_performance_share: float
    striking_min_position: int
    striking_max_position: int


class PagesOut(BaseModel):
    start_date: date
    end_date: date
    compare: Compare
    compare_available: bool  # needed for lost / rising / declining
    new_available: bool  # needed for new
    definitions: Definitions
    groups: list[PageGroup]
    counts: dict[str, int]
    total: int
    items: list[PageRow]


@router.get("/page-report", response_model=PagesOut)
def page_report(
    property_id: int,
    db: DbDep,
    days: Annotated[int, Query(ge=1, le=sync.MAX_HISTORY_DAYS)] = 28,
    compare: Compare = "previous",
    page_types: Annotated[list[pages.PageType] | None, Query(alias="type", description="Page types; any of")] = None,
    filters: Annotated[list[pages.PageFilter] | None, Query(alias="filter", description="Combined with AND")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: pages.SortKey = "clicks",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Page-type totals plus every page in the window, flagged and filterable like keywords."""
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")

    start, end = _window(db, prop.id, days)
    compare_start, compare_end = comparison_window(start, end, compare)
    first_stored = db.scalar(select(func.min(GscDailyMetric.date)).where(GscDailyMetric.property_id == prop.id))
    win = keywords.window_for(start, end, compare_start, compare_end, first_stored)

    rows = pages.page_rows(db, prop.id, win, days)
    counts, total, items = pages.explore(
        rows,
        list(dict.fromkeys(page_types or [])),
        list(dict.fromkeys(filters or [])),
        search,
        sort,
        order == "desc",
        limit,
        offset,
    )
    return PagesOut(
        start_date=start,
        end_date=end,
        compare=compare,
        compare_available=win.compare_start is not None,
        new_available=win.lookback_start is not None,
        definitions=Definitions(
            new_lookback_days=keywords.NEW_LOOKBACK_DAYS,
            mover_min_clicks=keywords.MOVER_MIN_CLICKS,
            mover_min_share=keywords.MOVER_MIN_SHARE,
            low_ctr_max_position=keywords.LOW_CTR_MAX_POSITION,
            low_ctr_factor=keywords.LOW_CTR_FACTOR,
            min_impressions=keywords.min_impressions(days),
            high_performance_share=keywords.HIGH_PERFORMANCE_SHARE,
            striking_min_position=opportunities.STRIKING_MIN_POSITION,
            striking_max_position=opportunities.STRIKING_MAX_POSITION,
        ),
        groups=pages.summarize(rows, win.compare_start is not None),
        counts=counts,
        total=total,
        items=[PageRow(**i) for i in items],
    )
