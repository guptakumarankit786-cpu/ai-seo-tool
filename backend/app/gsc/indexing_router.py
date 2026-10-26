from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.gsc import indexing
from app.gsc.advice import VERDICT_ORDER, Verdict, advice_for, normalize_reason
from app.gsc.export_parser import ExportError, parse_export
from app.models import (
    GscIndexingExport,
    GscIndexingExportReason,
    GscIndexingExportUrl,
    GscInspectionRun,
    GscProperty,
    GscUrlInspection,
)

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


class AdviceOut(BaseModel):
    verdict: Verdict
    summary: str
    action: str
    sitemap_cleanup: bool


class ReasonRow(BaseModel):
    reason: str
    pages: int
    in_sitemap: int  # how many of these pages are listed in a sitemap
    advice: AdviceOut


def _advice(reason: str) -> AdviceOut:
    a = advice_for(reason)
    return AdviceOut(verdict=a.verdict, summary=a.summary, action=a.action, sitemap_cleanup=a.sitemap_cleanup)


def _by_priority(row) -> tuple:
    """Worth-fixing first, then biggest."""
    return (VERDICT_ORDER[row.advice.verdict], -row.pages, row.reason)


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
        select(
            GscUrlInspection.coverage_state,
            func.count(),
            func.count().filter(GscUrlInspection.in_sitemap),
        )
        .where(GscUrlInspection.property_id == prop.id)
        .group_by(GscUrlInspection.coverage_state)
    ).all()
    known = sum(n for _, n, _ in counts)
    inspected = sum(n for state, n, _ in counts if state is not None)
    indexed = sum(n for state, n, _ in counts if indexing.is_indexed(state))
    reasons = sorted(
        (
            ReasonRow(reason=state, pages=n, in_sitemap=in_sitemap, advice=_advice(state))
            for state, n, in_sitemap in counts
            if state and not indexing.is_indexed(state)
        ),
        key=_by_priority,
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


# ---------- Search Console export uploads ----------


class ExportReasonRow(BaseModel):
    reason: str
    source: str | None
    validation: str | None
    pages: int
    critical: bool | None
    advice: AdviceOut
    # Example URLs from the latest uploaded drill-down for this reason, if any.
    urls_uploaded: int
    urls_uploaded_at: datetime | None


class ExportSummary(BaseModel):
    id: int
    filename: str
    uploaded_at: datetime
    chart_date: date | None
    indexed: int | None
    not_indexed: int | None
    reasons: list[ExportReasonRow]


class UploadResult(BaseModel):
    kind: str  # overview | issue
    filename: str
    issue: str | None
    reasons: int
    urls: int


class ExportUrl(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    last_crawled: date | None


class ExportUrlList(BaseModel):
    total: int
    uploaded_at: datetime | None
    items: list[ExportUrl]


def _host(site: str) -> str:
    """"sc-domain:example.com", "https://www.example.com/" or "www.example.com" → "example.com"."""
    site = site.strip().lower().removeprefix("sc-domain:")
    if "://" in site:
        site = urlsplit(site).hostname or ""
    return site.rstrip("/").removeprefix("www.")


def _same_property(site_url: str, exported: str) -> bool:
    prop, exp = _host(site_url), _host(exported)
    return exp == prop or exp.endswith("." + prop)  # a domain property covers its subdomains


def _latest_issue_exports(db: Session, property_id: int) -> dict[str, GscIndexingExport]:
    """Newest drill-down upload per reason (keyed by normalised reason)."""
    latest: dict[str, GscIndexingExport] = {}
    for exp in db.scalars(
        select(GscIndexingExport)
        .where(GscIndexingExport.property_id == property_id, GscIndexingExport.kind == "issue")
        .order_by(GscIndexingExport.uploaded_at, GscIndexingExport.id)
    ):
        latest[normalize_reason(exp.issue or "")] = exp
    return latest


@router.post("/uploads", response_model=UploadResult, status_code=201)
async def upload_export(property_id: int, db: DbDep, file: Annotated[UploadFile, File()]):
    """Upload Search Console's Page indexing export: the overview ZIP, or one reason's drill-down ZIP."""
    prop = _property(db, property_id)
    data = await file.read()
    try:
        parsed = parse_export(file.filename or "export", data)
    except ExportError as exc:
        raise HTTPException(422, str(exc))
    if parsed.site_url and not _same_property(prop.site_url, parsed.site_url):
        raise HTTPException(
            422, f"This export is for {parsed.site_url}, not {prop.site_url}. Check you picked the right client."
        )

    export = GscIndexingExport(
        property_id=prop.id,
        kind=parsed.kind,
        filename=(file.filename or "export")[:255],
        issue=parsed.issue,
        chart_date=parsed.chart_date,
        indexed=parsed.indexed,
        not_indexed=parsed.not_indexed,
    )
    export.reasons = [
        GscIndexingExportReason(
            reason=r.reason[:255], source=r.source, validation=r.validation, pages=r.pages, critical=r.critical
        )
        for r in parsed.reasons
    ]
    export.urls = [GscIndexingExportUrl(url=u.url, last_crawled=u.last_crawled) for u in parsed.urls]
    db.add(export)
    db.commit()
    return UploadResult(
        kind=export.kind, filename=export.filename, issue=export.issue, reasons=len(parsed.reasons), urls=len(parsed.urls)
    )


@router.get("/export", response_model=ExportSummary | None)
def latest_export(property_id: int, db: DbDep):
    """The most recently uploaded overview export, with advice per reason. Null if none uploaded."""
    prop = _property(db, property_id)
    export = db.scalars(
        select(GscIndexingExport)
        .where(GscIndexingExport.property_id == prop.id, GscIndexingExport.kind == "overview")
        .order_by(desc(GscIndexingExport.uploaded_at), desc(GscIndexingExport.id))
        .limit(1)
    ).first()
    if not export:
        return None

    drills = _latest_issue_exports(db, prop.id)
    url_counts = dict(
        db.execute(
            select(GscIndexingExportUrl.export_id, func.count())
            .where(GscIndexingExportUrl.export_id.in_([e.id for e in drills.values()] or [0]))
            .group_by(GscIndexingExportUrl.export_id)
        ).all()
    )
    rows = []
    for r in export.reasons:
        drill = drills.get(normalize_reason(r.reason))
        rows.append(
            ExportReasonRow(
                reason=r.reason,
                source=r.source,
                validation=r.validation,
                pages=r.pages,
                critical=r.critical,
                advice=_advice(r.reason),
                urls_uploaded=url_counts.get(drill.id, 0) if drill else 0,
                urls_uploaded_at=drill.uploaded_at if drill else None,
            )
        )
    return ExportSummary(
        id=export.id,
        filename=export.filename,
        uploaded_at=export.uploaded_at,
        chart_date=export.chart_date,
        indexed=export.indexed,
        not_indexed=export.not_indexed,
        reasons=sorted(rows, key=_by_priority),
    )


@router.get("/export/pages", response_model=ExportUrlList)
def export_pages(
    property_id: int,
    db: DbDep,
    reason: Annotated[str, Query()],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Example URLs for one reason, from the latest uploaded drill-down export."""
    prop = _property(db, property_id)
    drill = _latest_issue_exports(db, prop.id).get(normalize_reason(reason))
    if not drill:
        return ExportUrlList(total=0, uploaded_at=None, items=[])
    total = db.scalar(select(func.count()).where(GscIndexingExportUrl.export_id == drill.id))
    items = db.scalars(
        select(GscIndexingExportUrl)
        .where(GscIndexingExportUrl.export_id == drill.id)
        .order_by(GscIndexingExportUrl.url)
        .limit(limit)
        .offset(offset)
    ).all()
    return ExportUrlList(total=total, uploaded_at=drill.uploaded_at, items=[ExportUrl.model_validate(i) for i in items])
