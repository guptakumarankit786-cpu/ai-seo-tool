import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.gsc import brand, google_api, sync
from app.models import (
    GoogleConnection,
    GscDailyMetric,
    GscPageMetric,
    GscProperty,
    GscQueryMetric,
    GscSyncRun,
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
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class PropertyOut(BaseModel):
    id: int
    site_url: str
    permission_level: str
    last_synced_at: datetime | None
    latest_run: SyncRunOut | None


class ConnectionOut(BaseModel):
    id: int
    email: str
    created_at: datetime
    properties: list[PropertyOut]


class StatusOut(BaseModel):
    configured: bool
    connections: list[ConnectionOut]


class SyncIn(BaseModel):
    days: int = 90


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
    totals: Totals
    previous_totals: Totals | None
    daily: list[DailyPoint]


class DimensionRow(Totals):
    key: str
    brand: bool | None = None  # set for queries


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
    return PropertyOut(
        id=prop.id,
        site_url=prop.site_url,
        permission_level=prop.permission_level,
        last_synced_at=prop.last_synced_at,
        latest_run=SyncRunOut.model_validate(run, from_attributes=True) if run else None,
    )


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
    db: Session, model, key_col, property_id: int, days: int, limit: int, *extra_where
) -> list[DimensionRow]:
    start, end = _window(db, property_id, days)
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

    start, end = sync.default_range((body or SyncIn()).days)
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
    property_id: int, days: int = Query(28, ge=1, le=sync.MAX_HISTORY_DAYS), db: Session = Depends(get_db)
):
    prop = _get_property(db, property_id)
    start, end = _window(db, prop.id, days)
    totals = _totals(db, prop.id, start, end) or Totals(clicks=0, impressions=0, ctr=0, position=0)
    previous = _totals(db, prop.id, start - timedelta(days=days), start - timedelta(days=1))
    daily = db.scalars(
        select(GscDailyMetric)
        .where(
            GscDailyMetric.property_id == prop.id,
            GscDailyMetric.date >= start,
            GscDailyMetric.date <= end,
        )
        .order_by(GscDailyMetric.date)
    ).all()
    return SummaryOut(
        site_url=prop.site_url,
        start_date=start,
        end_date=end,
        totals=totals,
        previous_totals=previous,
        daily=[DailyPoint.model_validate(d, from_attributes=True) for d in daily],
    )


@router.get("/properties/{property_id}/queries", response_model=list[DimensionRow])
def top_queries(
    property_id: int,
    days: int = Query(28, ge=1, le=sync.MAX_HISTORY_DAYS),
    limit: int = Query(50, ge=1, le=1000),
    segment: Literal["all", "brand", "non_brand"] = "all",
    db: Session = Depends(get_db),
):
    prop = _get_property(db, property_id)
    terms = brand.effective_terms(prop.brand_terms, prop.site_url)
    is_brand = brand.brand_condition(GscQueryMetric.query, terms)
    extra = {"all": [], "brand": [is_brand], "non_brand": [~is_brand]}[segment]
    rows = _top(db, GscQueryMetric, GscQueryMetric.query, property_id, days, limit, *extra)
    for row in rows:
        row.brand = brand.is_brand(row.key, terms)
    return rows


@router.get("/properties/{property_id}/pages", response_model=list[DimensionRow])
def top_pages(
    property_id: int,
    days: int = Query(28, ge=1, le=sync.MAX_HISTORY_DAYS),
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    _get_property(db, property_id)
    return _top(db, GscPageMetric, GscPageMetric.page, property_id, days, limit)
