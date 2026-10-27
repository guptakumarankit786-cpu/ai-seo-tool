"""Shared date range for every report: preset days or custom dates, compare previous / year / custom / none."""
from datetime import timedelta

import pytest

from app.models import GscDailyMetric, GscPageMetric, GscQueryMetric
from tests.conftest import days_ago

END = days_ago(3)


@pytest.fixture
def history(db, prop):
    """120 days: 1 click per day, 10 clicks per day in the last 7 days."""
    for i in range(120):
        day = END - timedelta(days=i)
        clicks = 10 if i < 7 else 1
        db.add(GscDailyMetric(property_id=prop.id, date=day, clicks=clicks, impressions=100, ctr=clicks / 100, position=5))
        db.add(GscQueryMetric(property_id=prop.id, date=day, query="shoes", clicks=clicks, impressions=100, ctr=clicks / 100, position=5))
        db.add(GscPageMetric(property_id=prop.id, date=day, page="https://example.com/shoes", clicks=clicks, impressions=100, ctr=clicks / 100, position=5))
    db.commit()
    return prop


def summary(client, prop, **params):
    resp = client.get(f"/api/gsc/properties/{prop.id}/summary", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestRange:
    def test_preset_days_end_at_latest_synced_day(self, client, history):
        body = summary(client, history, days=7)
        assert (body["start_date"], body["end_date"]) == ((END - timedelta(days=6)).isoformat(), END.isoformat())
        assert body["totals"]["clicks"] == 70

    def test_custom_dates_override_days(self, client, history):
        start, end = END - timedelta(days=29), END - timedelta(days=20)  # 10 days of 1 click
        body = summary(client, history, days=7, start=start.isoformat(), end=end.isoformat())

        assert (body["start_date"], body["end_date"]) == (start.isoformat(), end.isoformat())
        assert body["totals"]["clicks"] == 10
        # previous period = the 10 days before
        assert body["compare_start"] == (start - timedelta(days=10)).isoformat()
        assert body["previous_totals"]["clicks"] == 10

    @pytest.mark.parametrize(
        "params,message",
        [
            ({"start": END.isoformat()}, "both a start and an end"),
            ({"start": END.isoformat(), "end": (END - timedelta(days=1)).isoformat()}, "on or before"),
            ({"start": (END - timedelta(days=500)).isoformat(), "end": END.isoformat()}, "at most 486 days"),
            ({"compare": "custom"}, "both comparison dates"),
        ],
    )
    def test_invalid_ranges(self, client, history, params, message):
        resp = client.get(f"/api/gsc/properties/{history.id}/summary", params=params)
        assert resp.status_code == 422
        assert message in resp.json()["detail"]


class TestCompare:
    def test_custom_comparison_window(self, client, history):
        cstart, cend = END - timedelta(days=60), END - timedelta(days=54)
        body = summary(client, history, days=7, compare="custom", compare_start=cstart.isoformat(), compare_end=cend.isoformat())

        assert (body["compare"], body["compare_start"], body["compare_end"]) == ("custom", cstart.isoformat(), cend.isoformat())
        assert body["previous_totals"]["clicks"] == 7
        assert len(body["previous_daily"]) == 7

    def test_no_comparison(self, client, history):
        body = summary(client, history, days=7, compare="none")
        assert (body["compare_start"], body["previous_totals"], body["previous_daily"]) == (None, None, [])

    def test_no_comparison_reaches_every_report(self, client, history):
        pid = history.id
        kw = client.get(f"/api/gsc/properties/{pid}/keywords", params={"days": 7, "compare": "none"}).json()
        pages = client.get(f"/api/gsc/properties/{pid}/page-report", params={"days": 7, "compare": "none"}).json()
        segments = client.get(f"/api/gsc/properties/{pid}/segments", params={"days": 7, "compare": "none"}).json()

        assert kw["compare_available"] is False and kw["items"][0]["prev_clicks"] is None
        assert pages["compare_available"] is False and pages["groups"][0]["prev_clicks"] is None
        assert segments["brand"]["previous"] is None and segments["non_brand"]["previous"] is None

    def test_custom_comparison_drives_movers(self, client, history):
        # 7 days of 10 clicks vs a quiet week of 1 click a day: "shoes" is rising
        cstart, cend = END - timedelta(days=60), END - timedelta(days=54)
        params = {"days": 7, "compare": "custom", "compare_start": cstart.isoformat(), "compare_end": cend.isoformat()}
        kw = client.get(f"/api/gsc/properties/{history.id}/keywords", params=params).json()
        assert "rising" in kw["items"][0]["types"]


def test_live_views_keep_their_90_day_limit(client, history):
    resp = client.get(
        f"/api/gsc/properties/{history.id}/opportunities/striking-distance",
        params={"start": (END - timedelta(days=100)).isoformat(), "end": END.isoformat()},
    )
    assert resp.status_code == 422
    assert "up to 90 days" in resp.json()["detail"]
