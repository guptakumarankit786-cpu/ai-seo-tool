from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.gsc import sync
from app.models import GscDailyMetric, GscPageMetric, GscProperty, GscQueryMetric, GscSyncRun


def count(db, model, property_id):
    return db.scalar(select(func.count()).select_from(model).where(model.property_id == property_id))


class TestDefaultRange:
    def test_ends_three_days_ago_to_allow_for_gsc_data_lag(self):
        start, end = sync.default_range(90)
        assert end == date.today() - timedelta(days=3)
        assert (end - start).days + 1 == 90

    def test_clamps_to_at_least_one_day(self):
        start, end = sync.default_range(0)
        assert start == end

    def test_clamps_to_gsc_16_month_limit(self):
        start, end = sync.default_range(10_000)
        assert (end - start).days + 1 == sync.MAX_HISTORY_DAYS


class TestRefreshProperties:
    def test_adds_every_site_the_account_can_see(self, db, connection, fake_google):
        props = sync.refresh_properties(db, connection)
        assert sorted(p.site_url for p in props) == ["https://blog.example.com/", "sc-domain:example.com"]

    def test_removes_sites_no_longer_visible_and_updates_permissions(self, db, connection, fake_google):
        sync.refresh_properties(db, connection)
        fake_google.sites = [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteRestrictedUser"}]

        props = sync.refresh_properties(db, connection)

        assert [(p.site_url, p.permission_level) for p in props] == [
            ("sc-domain:example.com", "siteRestrictedUser")
        ]
        assert db.scalar(select(func.count()).select_from(GscProperty)) == 1


class TestSyncEndpoint:
    def test_sync_stores_daily_query_and_page_rows(self, client, db, prop, fake_google):
        resp = client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})
        assert resp.status_code == 202
        assert resp.json()["status"] == "running"

        run = db.scalars(select(GscSyncRun)).one()
        db.refresh(prop)
        assert run.status == "success"
        assert run.rows_written == 10 + 30 + 30
        assert count(db, GscDailyMetric, prop.id) == 10
        assert count(db, GscQueryMetric, prop.id) == 30
        assert count(db, GscPageMetric, prop.id) == 30
        assert prop.last_synced_at is not None

    def test_requests_date_query_and_page_dimensions(self, client, prop, fake_google):
        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 5})
        assert {c[3] for c in fake_google.calls} == {("date",), ("date", "query"), ("date", "page")}

    def test_resync_replaces_rows_instead_of_duplicating(self, client, db, prop, fake_google):
        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})
        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})
        assert count(db, GscDailyMetric, prop.id) == 10
        assert count(db, GscQueryMetric, prop.id) == 30

    def test_failed_sync_is_recorded_and_writes_nothing(self, client, db, prop, fake_google):
        fake_google.fail_on = "page"

        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})

        run = db.scalars(select(GscSyncRun)).one()
        assert run.status == "failed"
        assert "403" in run.error
        assert run.finished_at is not None
        assert count(db, GscDailyMetric, prop.id) == 0
        assert count(db, GscQueryMetric, prop.id) == 0

    def test_rejects_second_sync_while_one_is_running(self, client, db, prop):
        start, end = sync.default_range(10)
        db.add(GscSyncRun(property_id=prop.id, status="running", start_date=start, end_date=end))
        db.commit()

        resp = client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})
        assert resp.status_code == 409

    def test_orphaned_running_sync_older_than_an_hour_is_replaced(self, client, db, prop, fake_google):
        start, end = sync.default_range(10)
        stale = GscSyncRun(
            property_id=prop.id,
            status="running",
            start_date=start,
            end_date=end,
            started_at=datetime.now(UTC) - timedelta(hours=2),
        )
        db.add(stale)
        db.commit()

        resp = client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})

        assert resp.status_code == 202
        db.refresh(stale)
        assert stale.status == "failed"
        assert stale.error == "Interrupted"

    def test_unknown_property_returns_404(self, client):
        assert client.post("/api/gsc/properties/999/sync", json={"days": 10}).status_code == 404
