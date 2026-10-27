"""16-month history: chunked sync, "sync latest", data range and year-over-year comparison."""
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.gsc import google_api, sync
from app.models import GscDailyMetric, GscIndexingExport, GscQueryMetric, GscSyncRun, GscUrlInspection
from tests.conftest import days_ago


def count(db, model, property_id):
    return db.scalar(select(func.count()).select_from(model).where(model.property_id == property_id))


def add_day(db, prop, day: date, clicks: int, impressions: int = 100):
    db.add(
        GscDailyMetric(
            property_id=prop.id, date=day, clicks=clicks, impressions=impressions, ctr=clicks / impressions, position=5.0
        )
    )


class TestChunks:
    def test_full_history_is_split_into_monthly_chunks_newest_first(self):
        start, end = sync.default_range(sync.MAX_HISTORY_DAYS)
        parts = sync.chunks(start, end)

        assert len(parts) == 17  # 486 days / 30
        assert parts[0][1] == end
        assert parts[-1][0] == start
        assert all(a[0] > b[1] for a, b in zip(parts, parts[1:]))  # newest first, no overlap
        assert sum((e - s).days + 1 for s, e in parts) == sync.MAX_HISTORY_DAYS

    def test_short_range_is_one_chunk(self):
        start, end = sync.default_range(7)
        assert sync.chunks(start, end) == [(start, end)]


class TestChunkedSync:
    def test_long_sync_reports_progress_and_stores_every_day(self, client, db, prop, fake_google):
        resp = client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 75})
        assert resp.status_code == 202

        run = db.scalars(select(GscSyncRun)).one()
        assert run.status == "success"
        assert (run.chunks_total, run.chunks_done) == (3, 3)
        assert count(db, GscDailyMetric, prop.id) == 75
        assert count(db, GscQueryMetric, prop.id) == 75 * 3
        assert run.rows_written == 75 + 75 * 3 * 2
        # Google is asked per chunk: 3 chunks x 3 dimension sets.
        assert len(fake_google.calls) == 9

    def test_failed_chunk_keeps_the_months_already_synced(self, client, db, prop, fake_google, monkeypatch):
        real = fake_google.search_analytics

        def fail_on_older_months(token, site, start, end, dims):
            if end < days_ago(20):  # every chunk except the newest
                raise google_api.GoogleAPIError("500 from www.googleapis.com: boom")
            return real(token, site, start, end, dims)

        monkeypatch.setattr(google_api, "search_analytics", fail_on_older_months)

        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 75})

        run = db.scalars(select(GscSyncRun)).one()
        assert run.status == "failed" and "500" in run.error
        assert run.chunks_done == 1
        assert count(db, GscDailyMetric, prop.id) == 30  # newest month survived


class TestSyncLatest:
    def test_needs_a_full_sync_first(self, client, prop):
        resp = client.post(f"/api/gsc/properties/{prop.id}/sync", json={"mode": "latest"})
        assert resp.status_code == 400

    def test_fetches_only_new_days_plus_a_small_overlap(self, client, db, prop, fake_google):
        newest = days_ago(10)
        add_day(db, prop, newest, clicks=1)
        db.commit()

        body = client.post(f"/api/gsc/properties/{prop.id}/sync", json={"mode": "latest"}).json()

        assert body["start_date"] == (newest - timedelta(days=sync.LATEST_OVERLAP_DAYS)).isoformat()
        assert body["end_date"] == sync.default_range(1)[1].isoformat()

    def test_latest_keeps_older_history(self, client, db, prop, fake_google):
        old = days_ago(200)
        add_day(db, prop, old, clicks=7)
        add_day(db, prop, days_ago(10), clicks=1)
        db.commit()

        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"mode": "latest"})

        assert db.scalar(select(GscDailyMetric.clicks).where(GscDailyMetric.date == old)) == 7


class TestPropertyDataRange:
    def test_reports_first_and_last_synced_day(self, client, db, prop):
        assert client.get(f"/api/gsc/properties/{prop.id}").json()["data_start"] is None
        add_day(db, prop, days_ago(400), clicks=1)
        add_day(db, prop, days_ago(3), clicks=1)
        db.commit()

        body = client.get(f"/api/gsc/properties/{prop.id}").json()

        assert body["data_start"] == days_ago(400).isoformat()
        assert body["data_end"] == days_ago(3).isoformat()


class TestPropertyIndexingStatus:
    def test_counts_inspected_pages_and_latest_overview_export(self, client, db, prop):
        body = client.get(f"/api/gsc/properties/{prop.id}").json()
        assert (body["pages_inspected"], body["last_inspected_at"], body["export_uploaded_at"]) == (0, None, None)

        now = datetime.now(UTC)
        db.add_all(
            [
                GscUrlInspection(property_id=prop.id, url="https://example.com/a", inspected_at=now),
                GscUrlInspection(property_id=prop.id, url="https://example.com/b", inspected_at=now - timedelta(days=1)),
                GscUrlInspection(property_id=prop.id, url="https://example.com/c"),  # waiting, not inspected
                GscIndexingExport(property_id=prop.id, kind="issue", filename="404.zip", issue="Not found (404)"),
            ]
        )
        db.commit()

        body = client.get(f"/api/gsc/properties/{prop.id}").json()
        assert body["pages_inspected"] == 2
        assert body["last_inspected_at"] is not None
        assert body["export_uploaded_at"] is None  # a single reason's export isn't the overview

        db.add(GscIndexingExport(property_id=prop.id, kind="overview", filename="example.com-Coverage.zip"))
        db.commit()
        assert client.get("/api/gsc/status").json()["connections"][0]["properties"][0]["export_uploaded_at"]


class TestYearOverYear:
    @pytest.fixture
    def two_years(self, db, prop):
        end = days_ago(3)
        for i in range(7):
            add_day(db, prop, end - timedelta(days=i), clicks=20)  # this week
            add_day(db, prop, end - timedelta(days=7 + i), clicks=10)  # previous week
            add_day(db, prop, end - timedelta(days=364 + i), clicks=5)  # same week last year
        db.commit()
        return prop

    def test_default_compares_with_previous_period(self, client, two_years):
        body = client.get(f"/api/gsc/properties/{two_years.id}/summary?days=7").json()
        assert body["compare"] == "previous"
        assert body["totals"]["clicks"] == 140
        assert body["previous_totals"]["clicks"] == 70
        assert len(body["previous_daily"]) == 7

    def test_year_compares_with_same_weekdays_last_year(self, client, two_years):
        body = client.get(f"/api/gsc/properties/{two_years.id}/summary?days=7&compare=year").json()

        assert body["previous_totals"]["clicks"] == 35
        end = days_ago(3)
        assert body["compare_end"] == (end - timedelta(days=364)).isoformat()
        assert date.fromisoformat(body["compare_end"]).weekday() == end.weekday()

    def test_no_comparison_data_gives_null_totals(self, client, db, prop):
        add_day(db, prop, days_ago(3), clicks=1)
        db.commit()
        body = client.get(f"/api/gsc/properties/{prop.id}/summary?days=7&compare=year").json()
        assert body["previous_totals"] is None and body["previous_daily"] == []

    def test_partial_history_gives_no_comparison(self, client, db, prop):
        # 10 days stored; a 7-day window's previous period needs 14 days -> only partly covered.
        end = days_ago(3)
        for i in range(10):
            add_day(db, prop, end - timedelta(days=i), clicks=10)
        db.commit()

        body = client.get(f"/api/gsc/properties/{prop.id}/summary?days=7").json()

        assert body["totals"]["clicks"] == 70
        assert body["previous_totals"] is None and body["previous_daily"] == []

    def test_rejects_unknown_compare(self, client, prop):
        assert client.get(f"/api/gsc/properties/{prop.id}/summary?compare=decade").status_code == 422

    def test_segments_support_year_over_year(self, client, db, prop):
        end = days_ago(3)
        for day, clicks in ((end, 30), (end - timedelta(days=364), 12)):
            db.add(
                GscQueryMetric(
                    property_id=prop.id, date=day, query="example shoes", clicks=clicks, impressions=100, ctr=0.1, position=2.0
                )
            )
        add_day(db, prop, end, clicks=30)
        add_day(db, prop, end - timedelta(days=370), clicks=12)  # history reaches back far enough
        db.commit()

        body = client.get(f"/api/gsc/properties/{prop.id}/segments?days=7&compare=year").json()

        assert body["brand"]["totals"]["clicks"] == 30
        assert body["brand"]["previous"]["clicks"] == 12
