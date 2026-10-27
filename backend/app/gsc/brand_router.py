from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import brand
from app.gsc.router import PeriodDep, Totals, _totals, has_history
from app.models import GscProperty, GscQueryMetric

router = APIRouter(prefix="/api/gsc/properties/{property_id}", tags=["gsc-brand"])

DbDep = Annotated[Session, Depends(get_db)]


class BrandTermsOut(BaseModel):
    terms: list[str]
    suggested: list[str]
    is_default: bool  # true until the user saves their own list


class BrandTermsIn(BaseModel):
    # null resets to the domain-based suggestion; [] means "this site has no brand terms".
    terms: list[str] | None = Field(default=None, max_length=brand.MAX_TERMS)


class SegmentTotals(BaseModel):
    totals: Totals
    previous: Totals | None
    click_share: float  # share of query-level clicks


class SegmentDay(BaseModel):
    date: date
    brand_clicks: int
    non_brand_clicks: int
    brand_impressions: int
    non_brand_impressions: int


class SegmentsOut(BaseModel):
    start_date: date
    end_date: date
    terms: list[str]
    brand: SegmentTotals
    non_brand: SegmentTotals
    # Clicks/impressions Google reports for the site but withholds at query level (anonymised queries).
    hidden_clicks: int
    hidden_impressions: int
    daily: list[SegmentDay]


def _property(db: Session, property_id: int) -> GscProperty:
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    return prop


def _terms_out(prop: GscProperty) -> BrandTermsOut:
    return BrandTermsOut(
        terms=brand.effective_terms(prop.brand_terms, prop.site_url),
        suggested=brand.suggest_terms(prop.site_url),
        is_default=prop.brand_terms is None,
    )


@router.get("/brand-terms", response_model=BrandTermsOut)
def get_brand_terms(property_id: int, db: DbDep):
    return _terms_out(_property(db, property_id))


@router.put("/brand-terms", response_model=BrandTermsOut)
def set_brand_terms(property_id: int, body: BrandTermsIn, db: DbDep):
    prop = _property(db, property_id)
    prop.brand_terms = None if body.terms is None else brand.clean_terms(body.terms)
    db.commit()
    return _terms_out(prop)


class CompetitorTermsIO(BaseModel):
    terms: list[str] = Field(default_factory=list, max_length=brand.MAX_TERMS)


@router.get("/competitor-terms", response_model=CompetitorTermsIO)
def get_competitor_terms(property_id: int, db: DbDep):
    return CompetitorTermsIO(terms=_property(db, property_id).competitor_terms or [])


@router.put("/competitor-terms", response_model=CompetitorTermsIO)
def set_competitor_terms(property_id: int, body: CompetitorTermsIO, db: DbDep):
    """Competitor names (brands, domains). Keywords containing one are tagged "competitor"."""
    prop = _property(db, property_id)
    prop.competitor_terms = brand.clean_terms(body.terms)
    db.commit()
    return CompetitorTermsIO(terms=prop.competitor_terms)


def _to_totals(clicks: int, impressions: int, weighted_pos: float) -> Totals:
    return Totals(
        clicks=clicks,
        impressions=impressions,
        ctr=clicks / impressions if impressions else 0.0,
        position=weighted_pos / impressions if impressions else 0.0,
    )


@router.get("/segments", response_model=SegmentsOut)
def segments(
    property_id: int,
    db: DbDep,
    period: PeriodDep,
):
    """Brand vs non-brand totals (with comparison period) and daily split, from query-level data."""
    prop = _property(db, property_id)
    terms = brand.effective_terms(prop.brand_terms, prop.site_url)
    start, end = period.start, period.end
    compare_start, compare_end = period.compare_start, period.compare_end

    is_brand = case((brand.brand_condition(GscQueryMetric.query_norm, terms), True), else_=False)

    def grouped(range_start: date, range_end: date):
        return db.execute(
            select(
                GscQueryMetric.date,
                is_brand,
                func.sum(GscQueryMetric.clicks),
                func.sum(GscQueryMetric.impressions),
                func.sum(GscQueryMetric.position * GscQueryMetric.impressions),
            )
            .where(
                GscQueryMetric.property_id == prop.id,
                GscQueryMetric.date >= range_start,
                GscQueryMetric.date <= range_end,
            )
            .group_by(GscQueryMetric.date, is_brand)
        ).all()

    # Two separate scans: for year-over-year the windows are a year apart.
    rows = [(0, *r) for r in grouped(start, end)]
    if compare_start is not None and has_history(db, prop.id, compare_start):
        rows += [(1, *r) for r in grouped(compare_start, compare_end)]

    # [current, comparison] accumulators per segment: clicks, impressions, weighted position
    acc = {seg: [[0, 0, 0.0], [0, 0, 0.0]] for seg in (True, False)}
    days_map: dict[date, SegmentDay] = {}
    for period, day, seg, clicks, impressions, weighted in rows:
        bucket = acc[seg][period]
        bucket[0] += clicks
        bucket[1] += impressions
        bucket[2] += weighted or 0.0
        if period == 0:
            point = days_map.setdefault(day, SegmentDay(date=day, brand_clicks=0, non_brand_clicks=0, brand_impressions=0, non_brand_impressions=0))
            if seg:
                point.brand_clicks += clicks
                point.brand_impressions += impressions
            else:
                point.non_brand_clicks += clicks
                point.non_brand_impressions += impressions

    query_clicks = acc[True][0][0] + acc[False][0][0]
    query_impressions = acc[True][0][1] + acc[False][0][1]
    site = _totals(db, prop.id, start, end)

    def seg_out(seg: bool) -> SegmentTotals:
        cur, prev = acc[seg]
        return SegmentTotals(
            totals=_to_totals(*cur),
            previous=_to_totals(*prev) if prev[1] else None,
            click_share=cur[0] / query_clicks if query_clicks else 0.0,
        )

    return SegmentsOut(
        start_date=start,
        end_date=end,
        terms=terms,
        brand=seg_out(True),
        non_brand=seg_out(False),
        hidden_clicks=max(0, (site.clicks if site else 0) - query_clicks),
        hidden_impressions=max(0, (site.impressions if site else 0) - query_impressions),
        daily=sorted(days_map.values(), key=lambda d: d.date),
    )
