from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import brand, google_api, indexing, keywords, opportunities, pages, sync
from app.gsc.indexing_router import AdviceOut, _advice
from app.gsc.router import Compare, DailyPoint, Totals, _window, comparison_window
from app.models import (
    GscDailyMetric,
    GscIndexingExport,
    GscIndexingExportUrl,
    GscPageMetric,
    GscProperty,
    GscUrlInspection,
)

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


# ---------- one page ----------


class PageKeyword(BaseModel):
    query: str
    brand: bool
    clicks: int
    impressions: int
    ctr: float
    position: float
    other_pages: int  # other pages of the site shown for this search


class PageInspection(BaseModel):
    coverage_state: str | None
    indexed: bool
    last_crawl_time: datetime | None
    inspected_at: datetime | None
    google_canonical: str | None
    user_canonical: str | None
    in_sitemap: bool
    advice: AdviceOut | None  # for pages that aren't indexed


class ExportIssue(BaseModel):
    issue: str
    uploaded_at: datetime
    last_crawled: date | None
    advice: AdviceOut


class PageDetailOut(BaseModel):
    page: str
    type: pages.PageType
    flags: list[pages.PageFilter]
    expected_ctr: float | None
    start_date: date
    end_date: date
    compare: Compare
    compare_start: date
    compare_end: date
    totals: Totals
    previous_totals: Totals | None  # null when stored history doesn't cover the comparison window
    daily: list[DailyPoint]
    previous_daily: list[DailyPoint]
    # Keywords come from the live keyword+page pull (up to 90 days, cached until the next sync / 24 h).
    keywords_available: bool
    keywords_fetched_at: datetime | None
    keywords: list[PageKeyword]
    inspection: PageInspection | None  # null until the page is inspected
    export_issues: list[ExportIssue]  # uploaded Search Console URL lists that include this page


def _page_daily(db: Session, property_id: int, page: str, start: date, end: date) -> list[DailyPoint]:
    rows = db.execute(
        select(GscPageMetric.date, GscPageMetric.clicks, GscPageMetric.impressions, GscPageMetric.ctr, GscPageMetric.position)
        .where(
            GscPageMetric.property_id == property_id,
            GscPageMetric.page == page,
            GscPageMetric.date >= start,
            GscPageMetric.date <= end,
        )
        .order_by(GscPageMetric.date)
    ).all()
    return [DailyPoint(date=d, clicks=c, impressions=i, ctr=ctr, position=pos) for d, c, i, ctr, pos in rows]


def _totals(clicks: int | None, impressions: int | None, position: float | None) -> Totals:
    clicks, impressions = clicks or 0, impressions or 0
    return Totals(
        clicks=clicks,
        impressions=impressions,
        ctr=clicks / impressions if impressions else 0.0,
        position=position or 0.0,
    )


def _page_keywords(db: Session, prop: GscProperty, entry_id: int, url: str) -> list[PageKeyword]:
    """The searches this page was shown for, from the cached keyword+page pull."""
    params: dict = {"entry_id": entry_id, "page": url}
    is_brand = keywords.brand_sql(brand.effective_terms(prop.brand_terms, prop.site_url), params, column="query_norm")
    mine = db.execute(
        text(
            f"""
            select query, {is_brand} as brand, clicks, impressions, position
            from gsc_query_page_cache_rows
            where entry_id = :entry_id and page = :page
            order by clicks desc, impressions desc, query
            """
        ),
        params,
    ).all()
    # How many other (non-Shopping) pages of the site showed up for the same searches.
    others = dict(
        db.execute(
            text(
                """
                select query, count(*) filter (where page <> :page) from gsc_query_page_cache_rows
                where entry_id = :entry_id and query = any(:queries) and position('?' in page) = 0
                group by query
                """
            ),
            {"entry_id": entry_id, "page": url, "queries": [m.query for m in mine]},
        ).all()
    )
    return [
        PageKeyword(
            query=m.query,
            brand=m.brand,
            clicks=m.clicks,
            impressions=m.impressions,
            ctr=m.clicks / m.impressions if m.impressions else 0.0,
            position=m.position,
            other_pages=others.get(m.query, 0),
        )
        for m in mine
    ]


def _inspection(db: Session, property_id: int, url: str) -> PageInspection | None:
    insp = db.scalars(
        select(GscUrlInspection).where(GscUrlInspection.property_id == property_id, GscUrlInspection.url == url)
    ).first()
    if not insp or not insp.inspected_at:
        return None
    indexed = indexing.is_indexed(insp.coverage_state)
    return PageInspection(
        coverage_state=insp.coverage_state,
        indexed=indexed,
        last_crawl_time=insp.last_crawl_time,
        inspected_at=insp.inspected_at,
        google_canonical=insp.google_canonical,
        user_canonical=insp.user_canonical,
        in_sitemap=insp.in_sitemap,
        advice=None if indexed or not insp.coverage_state else _advice(insp.coverage_state),
    )


def _export_issues(db: Session, property_id: int, url: str) -> list[ExportIssue]:
    """Search Console reason lists (uploaded drill-downs) that include this page, newest upload per reason."""
    newest: dict[str, ExportIssue] = {}
    for issue, uploaded_at, last_crawled in db.execute(
        select(GscIndexingExport.issue, GscIndexingExport.uploaded_at, GscIndexingExportUrl.last_crawled)
        .join(GscIndexingExportUrl, GscIndexingExportUrl.export_id == GscIndexingExport.id)
        .where(GscIndexingExport.property_id == property_id, GscIndexingExportUrl.url == url)
        .order_by(GscIndexingExport.uploaded_at, GscIndexingExport.id)
    ).all():
        if issue:
            newest[issue] = ExportIssue(issue=issue, uploaded_at=uploaded_at, last_crawled=last_crawled, advice=_advice(issue))
    return list(newest.values())


@router.get("/page-detail", response_model=PageDetailOut)
def page_detail(
    property_id: int,
    db: DbDep,
    url: Annotated[str, Query(min_length=1, max_length=2000)],
    days: Annotated[int, Query(ge=1, le=sync.MAX_HISTORY_DAYS)] = 28,
    compare: Compare = "previous",
):
    """One page: totals and daily series vs the comparison window, its keywords, its indexing status."""
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    if not db.scalar(select(GscPageMetric.id).where(GscPageMetric.property_id == prop.id, GscPageMetric.page == url).limit(1)):
        raise HTTPException(404, "This page isn't in the client's search data")

    start, end = _window(db, prop.id, days)
    compare_start, compare_end = comparison_window(start, end, compare)
    first_stored = db.scalar(select(func.min(GscDailyMetric.date)).where(GscDailyMetric.property_id == prop.id))
    win = keywords.window_for(start, end, compare_start, compare_end, first_stored)
    has_compare = win.compare_start is not None
    row = next((r for r in pages.page_rows(db, prop.id, win, days) if r["page"] == url), None) or {}

    keywords_available = days <= opportunities.MAX_DAYS
    page_keywords: list[PageKeyword] = []
    fetched_at = None
    if keywords_available:
        try:
            entry = opportunities.cached_entry(db, prop, start, end)
        except google_api.GoogleAPIError as exc:
            raise HTTPException(502, f"Couldn't fetch page-level data from Google: {exc}")
        fetched_at = entry.built_at
        page_keywords = _page_keywords(db, prop, entry.id, url)

    return PageDetailOut(
        page=url,
        type=pages.page_type(url),
        flags=row.get("flags", []),
        expected_ctr=row.get("expected_ctr"),
        start_date=start,
        end_date=end,
        compare=compare,
        compare_start=compare_start,
        compare_end=compare_end,
        totals=_totals(row.get("clicks"), row.get("impressions"), row.get("position")),
        previous_totals=(
            _totals(row.get("prev_clicks"), row.get("prev_impressions"), row.get("prev_position")) if has_compare else None
        ),
        daily=_page_daily(db, prop.id, url, start, end),
        previous_daily=_page_daily(db, prop.id, url, compare_start, compare_end) if has_compare else [],
        keywords_available=keywords_available,
        keywords_fetched_at=fetched_at,
        keywords=page_keywords,
        inspection=_inspection(db, prop.id, url),
        export_issues=_export_issues(db, prop.id, url),
    )
