from datetime import timedelta

import pytest

from app.models import GscDailyMetric, GscQueryMetric
from tests.conftest import days_ago


def add_day(db, prop, day, clicks, impressions, position):
    db.add(
        GscDailyMetric(
            property_id=prop.id,
            date=day,
            clicks=clicks,
            impressions=impressions,
            ctr=clicks / impressions,
            position=position,
        )
    )


class TestSummary:
    def test_totals_use_impression_weighted_position_and_overall_ctr(self, client, db, prop):
        end = days_ago(3)
        add_day(db, prop, end, clicks=10, impressions=100, position=2.0)
        add_day(db, prop, end - timedelta(days=1), clicks=30, impressions=300, position=10.0)
        db.commit()

        totals = client.get(f"/api/gsc/properties/{prop.id}/summary?days=7").json()["totals"]

        assert totals["clicks"] == 40
        assert totals["impressions"] == 400
        assert totals["ctr"] == pytest.approx(0.1)
        # (2*100 + 10*300) / 400 = 8.0 — not the naive average of 6.0
        assert totals["position"] == pytest.approx(8.0)

    def test_window_ends_at_latest_synced_day(self, client, db, prop):
        latest = days_ago(10)
        add_day(db, prop, latest, clicks=1, impressions=10, position=1.0)
        db.commit()

        body = client.get(f"/api/gsc/properties/{prop.id}/summary?days=7").json()

        assert body["end_date"] == latest.isoformat()
        assert body["start_date"] == (latest - timedelta(days=6)).isoformat()
        assert len(body["daily"]) == 1

    def test_previous_period_is_the_equal_length_window_before(self, client, db, prop):
        end = days_ago(3)
        add_day(db, prop, end, clicks=20, impressions=200, position=3.0)
        add_day(db, prop, end - timedelta(days=7), clicks=5, impressions=50, position=6.0)  # previous 7d
        add_day(db, prop, end - timedelta(days=14), clicks=999, impressions=999, position=1.0)  # outside both
        db.commit()

        body = client.get(f"/api/gsc/properties/{prop.id}/summary?days=7").json()

        assert body["totals"]["clicks"] == 20
        assert body["previous_totals"]["clicks"] == 5

    def test_property_without_data_returns_zeros_and_no_previous(self, client, prop):
        body = client.get(f"/api/gsc/properties/{prop.id}/summary?days=28").json()
        assert body["totals"] == {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
        assert body["previous_totals"] is None
        assert body["daily"] == []

    @pytest.mark.parametrize("days", [0, 487])
    def test_rejects_out_of_range_days(self, client, prop, days):
        assert client.get(f"/api/gsc/properties/{prop.id}/summary?days={days}").status_code == 422

    def test_unknown_property_returns_404(self, client):
        assert client.get("/api/gsc/properties/999/summary").status_code == 404


class TestTopQueries:
    def seed(self, db, prop):
        end = days_ago(3)
        add_day(db, prop, end, clicks=1, impressions=1, position=1.0)  # anchors the window
        for offset, (query, clicks, impressions, position) in enumerate(
            [("seo tool", 5, 50, 2.0), ("seo tool", 15, 150, 4.0), ("rank tracker", 8, 40, 1.0), ("audit", 1, 500, 9.0)]
        ):
            db.add(
                GscQueryMetric(
                    property_id=prop.id,
                    date=end - timedelta(days=offset % 2),
                    query=query,
                    clicks=clicks,
                    impressions=impressions,
                    ctr=clicks / impressions,
                    position=position,
                )
            )
        db.commit()

    def test_aggregates_across_days_and_sorts_by_clicks(self, client, db, prop):
        self.seed(db, prop)

        rows = client.get(f"/api/gsc/properties/{prop.id}/queries?days=7").json()

        assert [r["key"] for r in rows] == ["seo tool", "rank tracker", "audit"]
        top = rows[0]
        assert top["clicks"] == 20
        assert top["impressions"] == 200
        assert top["ctr"] == pytest.approx(0.1)
        assert top["position"] == pytest.approx((2.0 * 50 + 4.0 * 150) / 200)

    def test_respects_limit(self, client, db, prop):
        self.seed(db, prop)
        rows = client.get(f"/api/gsc/properties/{prop.id}/queries?days=7&limit=1").json()
        assert len(rows) == 1

    def test_pages_endpoint_returns_empty_list_without_data(self, client, prop):
        assert client.get(f"/api/gsc/properties/{prop.id}/pages?days=7").json() == []
