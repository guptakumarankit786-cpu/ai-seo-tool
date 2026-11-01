"""Nightly "Latest days" sync: who is due, catch-up after a missed night, one run per night."""
from datetime import UTC, datetime

import pytest

from app.gsc import nightly, sync
from app.models import GscDailyMetric, GscProperty, GscSyncRun
from tests.conftest import days_ago

# 02:00 Asia/Kolkata = 20:30 UTC the day before
NIGHT = datetime(2026, 11, 1, 20, 30, tzinfo=UTC)


def test_last_cutoff_is_the_latest_2am_local():
    assert nightly.last_cutoff(datetime(2026, 11, 2, 3, 0, tzinfo=UTC)) == NIGHT  # 08:30 local
    assert nightly.last_cutoff(datetime(2026, 11, 1, 20, 0, tzinfo=UTC)) == datetime(2026, 10, 31, 20, 30, tzinfo=UTC)  # 01:30 local


@pytest.fixture
def props(db, prop, connection):
    """prop has data; a second property has none."""
    empty = GscProperty(connection_id=connection.id, site_url="https://example.org/", permission_level="siteOwner")
    db.add(empty)
    db.add(GscDailyMetric(property_id=prop.id, date=days_ago(10), clicks=1, impressions=10, ctr=0.1, position=3))
    db.commit()
    return prop, empty


def run(db, prop, started, status="success"):
    db.add(GscSyncRun(property_id=prop.id, status=status, start_date=days_ago(5), end_date=days_ago(3), started_at=started))
    db.commit()


def test_only_properties_with_data_are_due(db, props):
    prop, _ = props
    assert nightly.due_properties(db, NIGHT) == [prop.id]


def test_synced_since_the_cutoff_is_not_due(db, props):
    prop, _ = props
    run(db, prop, datetime(2026, 11, 1, 21, 0, tzinfo=UTC))
    assert nightly.due_properties(db, datetime(2026, 11, 2, 6, 0, tzinfo=UTC)) == []


def test_missed_night_is_caught_up_and_failures_wait_for_the_next_night(db, props):
    prop, _ = props
    run(db, prop, datetime(2026, 10, 31, 21, 0, tzinfo=UTC))  # yesterday's night run
    later = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)  # computer was asleep at 02:00, back on at 09:30
    assert nightly.due_properties(db, later) == [prop.id]

    run(db, prop, datetime(2026, 11, 2, 4, 5, tzinfo=UTC), status="failed")
    assert nightly.due_properties(db, later) == []


def test_running_sync_is_left_alone(db, props):
    prop, _ = props
    run(db, prop, datetime(2026, 10, 30, 21, 0, tzinfo=UTC), status="running")
    assert nightly.due_properties(db, NIGHT) == []


def test_run_due_starts_a_latest_days_sync(db, props, monkeypatch):
    prop, _ = props
    started = []
    monkeypatch.setattr(sync, "run_sync", started.append)

    assert nightly.run_due(datetime.now(UTC)) == 1

    new = db.get(GscSyncRun, started[0])
    assert (new.property_id, new.status) == (prop.id, "running")
    assert (new.start_date, new.end_date) == sync.latest_range(db, prop.id)
