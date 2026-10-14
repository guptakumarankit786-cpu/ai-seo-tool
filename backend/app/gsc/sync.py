"""Pull Search Console data into Postgres."""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.gsc import google_api
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


def default_range(days: int) -> tuple[date, date]:
    days = max(1, min(days, MAX_HISTORY_DAYS))
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    return end - timedelta(days=days - 1), end


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


def run_sync(run_id: int) -> None:
    """Background job: fetch daily, query and page data for the run's date range."""
    db = SessionLocal()
    try:
        run = db.get(GscSyncRun, run_id)
        prop = db.get(GscProperty, run.property_id)
        token = google_api.access_token_for(db, prop.connection)
        start, end = run.start_date, run.end_date

        daily = google_api.search_analytics(token, prop.site_url, start, end, ["date"])
        queries = google_api.search_analytics(token, prop.site_url, start, end, ["date", "query"])
        pages = google_api.search_analytics(token, prop.site_url, start, end, ["date", "page"])

        daily_rows = _metric_rows(prop.id, daily, ["date"])
        query_rows = _metric_rows(prop.id, queries, ["date", "query"])
        page_rows = _metric_rows(prop.id, pages, ["date", "page"])

        _replace_range(db, GscDailyMetric, prop.id, start, end, daily_rows)
        _replace_range(db, GscQueryMetric, prop.id, start, end, query_rows)
        _replace_range(db, GscPageMetric, prop.id, start, end, page_rows)

        now = datetime.now(UTC)
        run.status = "success"
        run.rows_written = len(daily_rows) + len(query_rows) + len(page_rows)
        run.finished_at = now
        prop.last_synced_at = now
        db.commit()
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
