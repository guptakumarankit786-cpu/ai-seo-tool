import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.gsc import brand, google_api, keywords, pages, sync
from app.models import (
    GoogleConnection,
    GscDailyMetric,
    GscIndexingExport,
    GscProperty,
    GscQueryMetric,
    GscSyncRun,
    GscUrlInspection,
    OAuthState,
)

router = APIRouter(prefix="/api/gsc", tags=["gsc"])

STATE_TTL = timedelta(minutes=10)


# ---------- schemas ----------


class SyncRunOut(BaseModel):
    id: int
    status: str
    start_date: date
    end_date: date
    rows_written: int
    chunks_total: int
    chunks_done: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class PropertyOut(BaseModel):
    id: int
    site_url: str
    permission_level: str
    last_synced_at: datetime | None
    latest_run: SyncRunOut | None
    # Range of synced performance data (null until the first sync).
    data_start: date | None
    data_end: date | None
    # Indexing data we hold: pages checked with URL Inspection, newest Search Console export upload.
    pages_inspected: int = 0
    last_inspected_at: datetime | None = None
    export_uploaded_at: datetime | None = None


class ConnectionOut(BaseModel):
    id: int
    email: str
    created_at: datetime
    properties: list[PropertyOut]


class StatusOut(BaseModel):
    configured: bool
    connections: list[ConnectionOut]


class SyncIn(BaseModel):
    # "range": (re)fetch the last `days` days. "latest": only days after what's already stored.
    mode: Literal["range", "latest"] = "range"
    days: int = 90


# previous: the equal-length window before · year: same weekdays 52 weeks earlier ·
# custom: compare_start..compare_end · none: no comparison at all.
Compare = Literal["previous", "year", "custom", "none"]
# Year-over-year compares with the same weekdays 52 weeks earlier.
YEAR_OFFSET = timedelta(days=364)


def comparison_window(start: date, end: date, compare: Compare) -> tuple[date, date]:
    """Window for the "previous" and "year" modes (custom dates come from the request)."""
    if compare == "year":
        return start - YEAR_OFFSET, end - YEAR_OFFSET
    length = end - start + timedelta(days=1)
    return start - length, start - timedelta(days=1)


def has_history(db: Session, property_id: int, since: date) -> bool:
    """True if stored data reaches back to `since`. Comparing against a window we only partly
    have would show a misleading change, so callers skip the comparison instead."""
    first = db.scalar(select(func.min(GscDailyMetric.date)).where(GscDailyMetric.property_id == property_id))
    return first is not None and first <= since


class Totals(BaseModel):
    clicks: int
    impressions: int
    ctr: float
    position: float


class DailyPoint(Totals):
    date: date


class SummaryOut(BaseModel):
    site_url: str
    start_date: date
    end_date: date
    compare: Compare
    compare_start: date | None  # null when compare=none
    compare_end: date | None
    totals: Totals
    previous_totals: Totals | None  # totals for the comparison window
    daily: list[DailyPoint]
    previous_daily: list[DailyPoint]  # comparison window, for the chart overlay


class DimensionRow(Totals):
    key: str
    brand: bool | None = None  # set for queries
    expected_ctr: float | None = None  # pages: site's typical page CTR at this position
    low_ctr: bool | None = None  # pages: CTR under half of that typical CTR


# ---------- helpers ----------


def _get_property(db: Session, property_id: int) -> GscProperty:
    prop = db.get(GscProperty, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    return prop


def _latest_run(db: Session, property_id: int) -> GscSyncRun | None:
    return db.scalars(
        select(GscSyncRun)
        .where(GscSyncRun.property_id == property_id)
        .order_by(desc(GscSyncRun.started_at))
        .limit(1)
    ).first()


def _property_out(db: Session, prop: GscProperty) -> PropertyOut:
    run = _latest_run(db, prop.id)
    data_start, data_end = db.execute(
        select(func.min(GscDailyMetric.date), func.max(GscDailyMetric.date)).where(
            GscDailyMetric.property_id == prop.id
        )
    ).one()
    pages_inspected, last_inspected_at = db.execute(
        select(func.count(GscUrlInspection.inspected_at), func.max(GscUrlInspection.inspected_at)).where(
            GscUrlInspection.property_id == prop.id
        )
    ).one()
    export_uploaded_at = db.scalar(
        select(func.max(GscIndexingExport.uploaded_at)).where(
            GscIndexingExport.property_id == prop.id, GscIndexingExport.kind == "overview"
        )
    )
    return PropertyOut(
        id=prop.id,
        site_url=prop.site_url,
        permission_level=prop.permission_level,
        last_synced_at=prop.last_synced_at,
        latest_run=SyncRunOut.model_validate(run, from_attributes=True) if run else None,
        data_start=data_start,
        data_end=data_end,
        pages_inspected=pages_inspected,
        last_inspected_at=last_inspected_at,
        export_uploaded_at=export_uploaded_at,
    )


@dataclass
class Period:
    """The date range every report uses, plus the window it's compared with (none when compare="none")."""

    start: date
    end: date
    compare: Compare
    compare_start: date | None
    compare_end: date | None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def period_params(
    property_id: int,
    db: Session = Depends(get_db),
    days: int = Query(28, ge=1, le=sync.MAX_HISTORY_DAYS, description="Last N days, ending at the latest synced day"),
    start: date | None = Query(None, description="Custom range start (with `end`; overrides `days`)"),
    end: date | None = Query(None, description="Custom range end"),
    compare: Compare = "previous",
    compare_start: date | None = Query(None, description="With compare=custom"),
    compare_end: date | None = Query(None, description="With compare=custom"),
) -> Period:
    if (start is None) != (end is None):
        raise HTTPException(422, "Give both a start and an end date for a custom range")
    if start is not None and end is not None:
        if start > end:
            raise HTTPException(422, "The start date must be on or before the end date")
        if (end - start).days + 1 > sync.MAX_HISTORY_DAYS:
            raise HTTPException(422, f"A range can be at most {sync.MAX_HISTORY_DAYS} days (Google keeps 16 months)")
    else:
        start, end = _window(db, property_id, days)

    if compare == "none":
        return Period(start, end, compare, None, None)
    if compare == "custom":
        if compare_start is None or compare_end is None:
            raise HTTPException(422, "Give both comparison dates to compare with a custom range")
        if compare_start > compare_end:
            raise HTTPException(422, "The comparison start date must be on or before its end date")
        return Period(start, end, compare, compare_start, compare_end)
    return Period(start, end, compare, *comparison_window(start, end, compare))


PeriodDep = Annotated[Period, Depends(period_params)]


def _window(db: Session, property_id: int, days: int) -> tuple[date, date]:
    """Range ending at the latest synced day, so the window isn't padded with empty days."""
    latest = db.scalar(
        select(func.max(GscDailyMetric.date)).where(GscDailyMetric.property_id == property_id)
    )
    end = latest or (date.today() - timedelta(days=sync.DATA_LAG_DAYS))
    return end - timedelta(days=days - 1), end


def _totals(db: Session, property_id: int, start: date, end: date) -> Totals | None:
    clicks, impressions, weighted_pos = db.execute(
        select(
            func.sum(GscDailyMetric.clicks),
            func.sum(GscDailyMetric.impressions),
            func.sum(GscDailyMetric.position * GscDailyMetric.impressions),
        ).where(
            GscDailyMetric.property_id == property_id,
            GscDailyMetric.date >= start,
            GscDailyMetric.date <= end,
        )
    ).one()
    if impressions is None:
        return None
    return Totals(
        clicks=clicks,
        impressions=impressions,
        ctr=clicks / impressions if impressions else 0.0,
        position=weighted_pos / impressions if impressions else 0.0,
    )


def _top(
    db: Session, model, key_col, property_id: int, start: date, end: date, limit: int, *extra_where
) -> list[DimensionRow]:
    clicks = func.sum(model.clicks)
    impressions = func.sum(model.impressions)
    rows = db.execute(
        select(
            key_col,
            clicks,
            impressions,
            func.sum(model.position * model.impressions),
        )
        .where(model.property_id == property_id, model.date >= start, model.date <= end, *extra_where)
        .group_by(key_col)
        .order_by(desc(clicks), desc(impressions))
        .limit(limit)
    ).all()
    return [
        DimensionRow(
            key=key,
            clicks=c,
            impressions=i,
            ctr=c / i if i else 0.0,
            position=wp / i if i else 0.0,
        )
        for key, c, i, wp in rows
    ]


# ---------- connection / OAuth ----------


@router.get("/status", response_model=StatusOut)
def status(db: Session = Depends(get_db)):
    conns = db.scalars(select(GoogleConnection).order_by(GoogleConnection.created_at)).all()
    return StatusOut(
        configured=get_settings().google_configured,
        connections=[
            ConnectionOut(
                id=c.id,
                email=c.email,
                created_at=c.created_at,
                properties=[
                    _property_out(db, p) for p in sorted(c.properties, key=lambda p: p.site_url)
                ],
            )
            for c in conns
        ],
    )


@router.get("/oauth/start")
def oauth_start(db: Session = Depends(get_db)):
    if not get_settings().google_configured:
        raise HTTPException(400, "Google OAuth client is not configured. See docs/gsc-setup.md.")
    db.execute(delete(OAuthState).where(OAuthState.created_at < datetime.now(UTC) - STATE_TTL))
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(state=state))
    db.commit()
    return RedirectResponse(google_api.build_auth_url(state))


@router.get("/oauth/callback")
def oauth_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    frontend = f"{get_settings().frontend_url}/integrations"

    def back(**params) -> RedirectResponse:
        return RedirectResponse(f"{frontend}?{urlencode(params)}")

    saved = db.get(OAuthState, state)
    if not saved or saved.created_at < datetime.now(UTC) - STATE_TTL:
        return back(gsc="error", reason="Login session expired, please try again.")
    db.delete(saved)
    db.commit()

    if error or not code:
        return back(gsc="error", reason=error or "No authorization code returned.")

    try:
        tokens = google_api.exchange_code(code)
        if "webmasters" not in tokens.get("scope", ""):
            return back(gsc="error", reason="Search Console access was not granted.")
        email = google_api.fetch_email(tokens["access_token"])

        conn = db.scalars(select(GoogleConnection).where(GoogleConnection.email == email)).first()
        if not conn:
            conn = GoogleConnection(email=email)
            db.add(conn)
        conn.scopes = tokens.get("scope", "")
        if tokens.get("refresh_token"):
            conn.refresh_token_enc = encrypt(tokens["refresh_token"])
        elif not conn.refresh_token_enc:
            return back(gsc="error", reason="Google did not return a refresh token.")
        conn.access_token_enc = encrypt(tokens["access_token"])
        conn.access_token_expires_at = datetime.now(UTC) + timedelta(
            seconds=tokens.get("expires_in", 3600)
        )
        db.commit()
        db.refresh(conn)

        props = sync.refresh_properties(db, conn)
    except google_api.GoogleAPIError as exc:
        return back(gsc="error", reason=str(exc)[:200])

    return back(gsc="connected", email=email, properties=len(props))


@router.delete("/connections/{connection_id}", status_code=204)
def disconnect(connection_id: int, db: Session = Depends(get_db)):
    conn = db.get(GoogleConnection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    try:
        google_api.revoke(decrypt(conn.refresh_token_enc))
    except Exception:
        pass
    db.delete(conn)
    db.commit()


@router.post("/connections/{connection_id}/refresh-properties", response_model=list[PropertyOut])
def refresh_properties(connection_id: int, db: Session = Depends(get_db)):
    conn = db.get(GoogleConnection, connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    try:
        props = sync.refresh_properties(db, conn)
    except google_api.GoogleAPIError as exc:
        raise HTTPException(502, str(exc))
    return [_property_out(db, p) for p in props]


# ---------- sync ----------


@router.post("/properties/{property_id}/sync", response_model=SyncRunOut, status_code=202)
def start_sync(
    property_id: int,
    background: BackgroundTasks,
    body: SyncIn | None = None,
    db: Session = Depends(get_db),
):
    prop = _get_property(db, property_id)
    running = _latest_run(db, prop.id)
    if running and running.status == "running":
        # A run older than an hour was orphaned (e.g. the server restarted mid-sync).
        if running.started_at > datetime.now(UTC) - timedelta(hours=1):
            raise HTTPException(409, "A sync is already running for this property")
        running.status = "failed"
        running.error = "Interrupted"
        running.finished_at = datetime.now(UTC)

    body = body or SyncIn()
    if body.mode == "latest":
        window = sync.latest_range(db, prop.id)
        if window is None:
            raise HTTPException(400, "Nothing synced yet — run a full sync first")
        start, end = window
    else:
        start, end = sync.default_range(body.days)
    run = GscSyncRun(property_id=prop.id, status="running", start_date=start, end_date=end)
    db.add(run)
    db.commit()
    db.refresh(run)
    background.add_task(sync.run_sync, run.id)
    return SyncRunOut.model_validate(run, from_attributes=True)


@router.get("/properties/{property_id}", response_model=PropertyOut)
def get_property(property_id: int, db: Session = Depends(get_db)):
    return _property_out(db, _get_property(db, property_id))


# ---------- reporting ----------


@router.get("/properties/{property_id}/summary", response_model=SummaryOut)
def summary(
    property_id: int,
    period: PeriodDep,
    db: Session = Depends(get_db),
):
    prop = _get_property(db, property_id)
    p = period
    totals = _totals(db, prop.id, p.start, p.end) or Totals(clicks=0, impressions=0, ctr=0, position=0)
    comparable = p.compare_start is not None and has_history(db, prop.id, p.compare_start)
    previous = _totals(db, prop.id, p.compare_start, p.compare_end) if comparable else None
    return SummaryOut(
        site_url=prop.site_url,
        start_date=p.start,
        end_date=p.end,
        compare=p.compare,
        compare_start=p.compare_start,
        compare_end=p.compare_end,
        totals=totals,
        previous_totals=previous,
        daily=_daily(db, prop.id, p.start, p.end),
        previous_daily=_daily(db, prop.id, p.compare_start, p.compare_end) if comparable else [],
    )


def _daily(db: Session, property_id: int, start: date, end: date) -> list[DailyPoint]:
    rows = db.scalars(
        select(GscDailyMetric)
        .where(
            GscDailyMetric.property_id == property_id,
            GscDailyMetric.date >= start,
            GscDailyMetric.date <= end,
        )
        .order_by(GscDailyMetric.date)
    ).all()
    return [DailyPoint.model_validate(d, from_attributes=True) for d in rows]


@router.get("/properties/{property_id}/queries", response_model=list[DimensionRow])
def top_queries(
    property_id: int,
    period: PeriodDep,
    limit: int = Query(50, ge=1, le=1000),
    segment: Literal["all", "brand", "non_brand"] = "all",
    db: Session = Depends(get_db),
):
    prop = _get_property(db, property_id)
    terms = brand.effective_terms(prop.brand_terms, prop.site_url)
    is_brand = brand.brand_condition(GscQueryMetric.query_norm, terms)
    extra = {"all": [], "brand": [is_brand], "non_brand": [~is_brand]}[segment]
    rows = _top(db, GscQueryMetric, GscQueryMetric.query, property_id, period.start, period.end, limit, *extra)
    for row in rows:
        row.brand = brand.is_brand(row.key, terms)
    return rows


@router.get("/properties/{property_id}/pages", response_model=list[DimensionRow])
def top_pages(
    property_id: int,
    period: PeriodDep,
    limit: int = Query(50, ge=1, le=1000),
    filter: Literal["all", "low_ctr"] = "all",
    db: Session = Depends(get_db),
):
    """Top pages, each flagged when its CTR is under half of the site's typical page CTR at its
    position (same rule as low-CTR keywords; pages have no brand split). `filter=low_ctr` lists
    only those, biggest click shortfall (impressions × (typical − actual CTR)) first."""
    _get_property(db, property_id)
    win = keywords.window_for(period.start, period.end, None, None, None)
    rows = [r for r in pages.page_rows(db, property_id, win, period.days) if r["impressions"]]
    if filter == "low_ctr":
        rows = sorted(
            (r for r in rows if "low_ctr" in r["flags"]),
            key=lambda r: (-r["impressions"] * (r["expected_ctr"] - r["ctr"]), r["page"]),
        )
    else:
        rows.sort(key=lambda r: (-r["clicks"], -r["impressions"], r["page"]))
    return [
        DimensionRow(
            key=r["page"],
            clicks=r["clicks"],
            impressions=r["impressions"],
            ctr=r["ctr"],
            position=r["position"] or 0,
            expected_ctr=r["expected_ctr"],
            low_ctr="low_ctr" in r["flags"],
        )
        for r in rows[:limit]
    ]
