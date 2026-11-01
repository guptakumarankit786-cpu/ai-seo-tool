"""Nightly "Latest days" sync for every property that already has data.

Runs inside the API process: a loop checks every few minutes whether a property is due, so a
night the computer slept is caught up as soon as it's back on. First (full) syncs stay manual.
"""
import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select

from app.config import get_settings
from app.db import SessionLocal
from app.gsc import sync
from app.models import GscDailyMetric, GscProperty, GscSyncRun

log = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 600


def last_cutoff(now: datetime) -> datetime:
    """The most recent nightly sync time (e.g. 02:00 local) at or before `now`, in UTC."""
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    cutoff = datetime.combine(local.date(), time.fromisoformat(settings.nightly_sync_time), tz)
    if cutoff > local:
        cutoff -= timedelta(days=1)
    return cutoff.astimezone(UTC)


def due_properties(db, now: datetime) -> list[int]:
    """Properties with stored data, nothing running, and no sync started since the last nightly time."""
    since = last_cutoff(now)
    has_data = exists().where(GscDailyMetric.property_id == GscProperty.id)
    running = exists().where(GscSyncRun.property_id == GscProperty.id, GscSyncRun.status == "running")
    started = select(func.max(GscSyncRun.started_at)).where(GscSyncRun.property_id == GscProperty.id).scalar_subquery()
    return list(
        db.scalars(
            select(GscProperty.id)
            .where(has_data, ~running, started.is_(None) | (started < since))
            .order_by(GscProperty.id)
        )
    )


def run_due(now: datetime | None = None) -> int:
    """Sync every due property one after another; returns how many were started."""
    with SessionLocal() as db:
        ids = due_properties(db, now or datetime.now(UTC))
    for pid in ids:
        with SessionLocal() as db:
            window = sync.latest_range(db, pid)
            if window is None:
                continue
            run = GscSyncRun(property_id=pid, status="running", start_date=window[0], end_date=window[1])
            db.add(run)
            db.commit()
            run_id = run.id
        log.info("Nightly sync: property %s", pid)
        sync.run_sync(run_id)  # records its own failure; the next property still runs
    return len(ids)


async def scheduler() -> None:
    while True:
        await asyncio.sleep(CHECK_EVERY_SECONDS)
        try:
            await asyncio.to_thread(run_due)
        except Exception:
            log.exception("Nightly sync check failed")
