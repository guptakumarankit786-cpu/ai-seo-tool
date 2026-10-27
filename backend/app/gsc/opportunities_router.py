from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import brand, google_api, opportunities
from app.gsc.keywords import Segment, min_impressions
from app.gsc.router import Period, PeriodDep
from app.models import GscProperty

router = APIRouter(prefix="/api/gsc/properties/{property_id}/opportunities", tags=["gsc-opportunities"])

DbDep = Annotated[Session, Depends(get_db)]


class Source(BaseModel):
    start_date: date
    end_date: date
    fetched_at: datetime  # when the query+page data was pulled from Google


class StrikingRow(BaseModel):
    query: str
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float
    other_pages: int
    brand: bool
    target_ctr: float | None  # site's typical CTR at the target position
    potential: int | None  # extra clicks if this page reached the target position


class StrikingOut(Source):
    min_position: int
    max_position: int
    target_position: int
    min_impressions: int
    total: int
    items: list[StrikingRow]


class CompetingPage(BaseModel):
    page: str
    clicks: int
    impressions: int
    position: float
    share: float


class CannibalRow(BaseModel):
    query: str
    brand: bool
    clicks: int
    impressions: int
    competing_pages: int
    sitelinks_likely: bool  # 3+ pages all in the top 3: Google sitelinks, usually fine
    pages: list[CompetingPage]


class CannibalOut(Source):
    min_share: float
    min_impressions: int
    total: int
    items: list[CannibalRow]


def _load(db: Session, property_id: int, period: Period):
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    if period.days > opportunities.MAX_DAYS:
        raise HTTPException(422, f"Pick up to {opportunities.MAX_DAYS} days: page-level data is pulled live from Google")
    try:
        entry = opportunities.cached_entry(db, prop, period.start, period.end)
    except google_api.GoogleAPIError as exc:
        raise HTTPException(502, f"Couldn't fetch page-level data from Google: {exc}")
    return prop, entry, brand.effective_terms(prop.brand_terms, prop.site_url)


@router.get("/striking-distance", response_model=StrikingOut)
def striking_distance(
    property_id: int,
    db: DbDep,
    period: PeriodDep,
    segment: Segment = "all",
    sort: opportunities.StrikingSort = "potential",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Keywords whose main page ranks 4–20: the quickest wins, ranked by potential extra clicks."""
    prop, entry, terms = _load(db, property_id, period)
    days = period.days
    total, items = opportunities.striking_distance(db, entry.id, terms, days, segment, sort, limit, offset)
    return StrikingOut(
        start_date=entry.start_date,
        end_date=entry.end_date,
        fetched_at=entry.built_at,
        min_position=opportunities.STRIKING_MIN_POSITION,
        max_position=opportunities.STRIKING_MAX_POSITION,
        target_position=opportunities.TARGET_POSITION,
        min_impressions=min_impressions(days),
        total=total,
        items=[StrikingRow(**i) for i in items],
    )


@router.get("/cannibalisation", response_model=CannibalOut)
def cannibalisation(
    property_id: int,
    db: DbDep,
    period: PeriodDep,
    segment: Segment = "all",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Keywords where several of the site's pages compete for the same searches."""
    prop, entry, terms = _load(db, property_id, period)
    days = period.days
    total, items = opportunities.cannibalisation(db, entry.id, terms, days, segment, limit, offset)
    return CannibalOut(
        start_date=entry.start_date,
        end_date=entry.end_date,
        fetched_at=entry.built_at,
        min_share=opportunities.CANNIBAL_MIN_SHARE,
        min_impressions=min_impressions(days),
        total=total,
        items=[CannibalRow(**i) for i in items],
    )
