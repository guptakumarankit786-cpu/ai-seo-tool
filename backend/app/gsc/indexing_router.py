from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import indexing
from app.models import GscInspectionRun, GscProperty, GscUrlInspection

router = APIRouter(prefix="/api/gsc/properties/{property_id}/indexing", tags=["gsc-indexing"])

DbDep = Annotated[Session, Depends(get_db)]
# A run normally finishes in well under an hour; older "running" rows were orphaned by a restart.
STALE_RUN = timedelta(hours=2)


class InspectionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    urls_known: int
    urls_queued: int
    urls_inspected: int
    urls_failed: int
    quota_exhausted: bool
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ReasonRow(BaseModel):
    reason: str
    pages: int


class IndexingSummary(BaseModel):
    latest_run: InspectionRunOut | None
    known: int
    inspected: int
    indexed: int
    not_indexed: int
    daily_limit: int
    used_last_24h: int
    last_inspected_at: datetime | None
    reasons: list[ReasonRow]


class InspectedPage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    coverage_state: str | None
    verdict: str | None
    indexing_state: str | None
    robots_txt_state: str | None
    page_fetch_state: str | None
    google_canonical: str | None
    user_canonical: str | None
    last_crawl_time: datetime | None
    inspected_at: datetime | None
    in_sitemap: bool
    in_search: bool


class PageList(BaseModel):
    total: int
    items: list[InspectedPage]


def _property(db: Session, property_id: int) -> GscProperty:
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    return prop


def _latest_run(db: Session, property_id: int) -> GscInspectionRun | None:
    return db.scalars(
        select(GscInspectionRun)
        .where(GscInspectionRun.property_id == property_id)
        .order_by(desc(GscInspectionRun.started_at))
        .limit(1)
    ).first()


@router.post("", response_model=InspectionRunOut, status_code=202)
def start_inspection(property_id: int, background: BackgroundTasks, db: DbDep):
    """Discover the property's URLs and inspect as many as today's quota allows."""
    prop = _property(db, property_id)
    latest = _latest_run(db, prop.id)
    if latest and latest.status == "running":
        if latest.started_at > datetime.now(UTC) - STALE_RUN:
            raise HTTPException(409, "An inspection is already running for this property")
        latest.status, latest.error, latest.finished_at = "failed", "Interrupted", datetime.now(UTC)
    if indexing.inspections_used_last_24h(db, prop.id) >= indexing.DAILY_INSPECTION_LIMIT:
        raise HTTPException(429, "Today's 2,000-inspection quota for this property is used up")

    run = GscInspectionRun(property_id=prop.id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    background.add_task(indexing.run_inspection, run.id)
    return run


@router.get("", response_model=IndexingSummary)
def summary(property_id: int, db: DbDep):
    """Indexed vs not indexed, plus the "Why pages aren't indexed" breakdown."""
    prop = _property(db, property_id)
    run = _latest_run(db, prop.id)

    counts = db.execute(
        select(GscUrlInspection.coverage_state, func.count())
        .where(GscUrlInspection.property_id == prop.id)
        .group_by(GscUrlInspection.coverage_state)
    ).all()
    known = sum(n for _, n in counts)
    inspected = sum(n for state, n in counts if state is not None)
    indexed = sum(n for state, n in counts if indexing.is_indexed(state))
    reasons = sorted(
        (ReasonRow(reason=state, pages=n) for state, n in counts if state and not indexing.is_indexed(state)),
        key=lambda r: (-r.pages, r.reason),
    )
    last_inspected_at = db.scalar(
        select(func.max(GscUrlInspection.inspected_at)).where(GscUrlInspection.property_id == prop.id)
    )

    return IndexingSummary(
        latest_run=InspectionRunOut.model_validate(run) if run else None,
        known=known,
        inspected=inspected,
        indexed=indexed,
        not_indexed=inspected - indexed,
        daily_limit=indexing.DAILY_INSPECTION_LIMIT,
        used_last_24h=indexing.inspections_used_last_24h(db, prop.id),
        last_inspected_at=last_inspected_at,
        reasons=reasons,
    )


@router.get("/pages", response_model=PageList)
def pages(
    property_id: int,
    db: DbDep,
    reason: Annotated[str | None, Query(description="Coverage state, e.g. 'Crawled - currently not indexed'")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Inspected URLs, optionally filtered to one not-indexed reason."""
    prop = _property(db, property_id)
    where = [GscUrlInspection.property_id == prop.id, GscUrlInspection.inspected_at.is_not(None)]
    if reason is not None:
        where.append(GscUrlInspection.coverage_state == reason)

    total = db.scalar(select(func.count()).select_from(GscUrlInspection).where(*where))
    items = db.scalars(
        select(GscUrlInspection)
        .where(*where)
        .order_by(GscUrlInspection.url)
        .limit(limit)
        .offset(offset)
    ).all()
    return PageList(total=total, items=[InspectedPage.model_validate(i) for i in items])
