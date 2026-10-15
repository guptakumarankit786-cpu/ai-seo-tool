"""Pull Search Console data into Postgres."""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.gsc import google_api, keywords
from app.models import (
    GoogleConnection,
    GscDailyMetric,
    GscPageMetric,
    GscProperty,
    GscQueryMetric,
    GscSyncRun,
)

log = logging.getLogger(__name__)

# GSC data is typically finalised ~2-3 days after the fact.
DATA_LAG_DAYS = 3
# GSC keeps 16 months of history.
MAX_HISTORY_DAYS = 486
INSERT_BATCH = 5_000
# Long ranges are fetched and written a month at a time: bounded memory, visible progress,
# and recent months land first.
CHUNK_DAYS = 30
# "Sync latest" re-fetches the last few stored days too, since Google can still revise them.
LATEST_OVERLAP_DAYS = 3


def default_range(days: int) -> tuple[date, date]:
    days = max(1, min(days, MAX_HISTORY_DAYS))
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    return end - timedelta(days=days - 1), end


def latest_range(db: Session, property_id: int) -> tuple[date, date] | None:
    """Range for "Sync latest": from just before the newest stored day up to today's data.

    None if nothing has been synced yet (a full sync is needed first).
    """
    newest = db.scalar(select(func.max(GscDailyMetric.date)).where(GscDailyMetric.property_id == property_id))
    if newest is None:
        return None
    _, end = default_range(1)
    return min(newest - timedelta(days=LATEST_OVERLAP_DAYS), end), end


def chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into CHUNK_DAYS pieces, newest first."""
    out = []
    chunk_end = end
    while chunk_end >= start:
        chunk_start = max(start, chunk_end - timedelta(days=CHUNK_DAYS - 1))
        out.append((chunk_start, chunk_end))
        chunk_end = chunk_start - timedelta(days=1)
    return out


def refresh_properties(db: Session, conn: GoogleConnection) -> list[GscProperty]:
    """Mirror the account's GSC site list: add new properties, drop ones no longer visible."""
    token = google_api.access_token_for(db, conn)
    sites = {s["siteUrl"]: s["permissionLevel"] for s in google_api.list_sites(token)}

    existing = {p.site_url: p for p in conn.properties}
    for site_url, prop in existing.items():
        if site_url not in sites:
            db.delete(prop)
    for site_url, permission in sites.items():
        if site_url in existing:
            existing[site_url].permission_level = permission
        else:
            db.add(GscProperty(connection_id=conn.id, site_url=site_url, permission_level=permission))
    db.commit()
    db.refresh(conn)
    return conn.properties


def _metric_rows(property_id: int, rows: list[dict], key_names: list[str]) -> list[dict]:
    out = []
    for r in rows:
        item = {
            "property_id": property_id,
            "clicks": int(r["clicks"]),
            "impressions": int(r["impressions"]),
            "ctr": r["ctr"],
            "position": r["position"],
        }
        for name, value in zip(key_names, r["keys"]):
            item[name] = date.fromisoformat(value) if name == "date" else value
        out.append(item)
    return out


def _replace_range(db: Session, model, property_id: int, start: date, end: date, rows: list[dict]) -> None:
    db.execute(
        delete(model).where(
            model.property_id == property_id, model.date >= start, model.date <= end
        )
    )
    for i in range(0, len(rows), INSERT_BATCH):
        db.execute(insert(model), rows[i : i + INSERT_BATCH])


def _sync_chunk(db: Session, prop: GscProperty, start: date, end: date) -> int:
    """Fetch and replace one date range. Returns rows written. Caller commits."""
    token = google_api.access_token_for(db, prop.connection)  # refreshes during long runs
    written = 0
    for model, keys in (
        (GscDailyMetric, ["date"]),
        (GscQueryMetric, ["date", "query"]),
        (GscPageMetric, ["date", "page"]),
    ):
        rows = _metric_rows(prop.id, google_api.search_analytics(token, prop.site_url, start, end, keys), keys)
        _replace_range(db, model, prop.id, start, end, rows)
        written += len(rows)
    return written


def run_sync(run_id: int) -> None:
    """Background job: fetch daily, query and page data for the run's range, a month at a time.

    Each month is committed on its own, so an interrupted run keeps what it finished and a
    re-run simply replaces those months again.
    """
    db = SessionLocal()
    try:
        run = db.get(GscSyncRun, run_id)
        prop = db.get(GscProperty, run.property_id)
        parts = chunks(run.start_date, run.end_date)
        run.chunks_total = len(parts)
        db.commit()

        for chunk_start, chunk_end in parts:
            run.rows_written += _sync_chunk(db, prop, chunk_start, chunk_end)
            run.chunks_done += 1
            prop.last_synced_at = datetime.now(UTC)
            db.commit()

        run.status = "success"
        run.finished_at = datetime.now(UTC)
        db.commit()

        # Make the Keywords tab's default view instant. A failure here must not fail the sync.
        try:
            keywords.warm_default_cache(db, prop)
        except Exception:
            log.exception("Warming keyword cache after sync %s failed", run_id)
            db.rollback()
    except Exception as exc:
        log.exception("GSC sync %s failed", run_id)
        db.rollback()
        run = db.get(GscSyncRun, run_id)
        if run:
            run.status = "failed"
            run.error = str(exc)[:2000]
            run.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()
