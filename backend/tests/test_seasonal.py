"""Seasonal keywords, spikes and competitor terms."""
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.gsc import seasonal
from app.models import GscDailyMetric, GscMonthlyKeywordCache, GscQueryMetric

# 15 full months: Jul 2025 .. Sep 2026 (Jul, Aug, Sep appear twice).
MONTHS = [date(2025 + (6 + i) // 12, (6 + i) % 12 + 1, 1) for i in range(15)]
TODAY_OCT = date(2026, 10, 15)


def series(**by_month):
    """Monthly impressions defaulting to 100; override with e.g. jul25=900."""
    names = ["jul25", "aug25", "sep25", "oct25", "nov25", "dec25", "jan26", "feb26", "mar26", "apr26",
             "may26", "jun26", "jul26", "aug26", "sep26"]
    return [by_month.get(n, 100) for n in names]


class TestHelpers:
    def test_full_month_range_drops_partial_months(self):
        assert seasonal.full_month_range(date(2025, 6, 14), date(2026, 10, 12)) == (date(2025, 7, 1), date(2026, 10, 1))
        assert seasonal.full_month_range(date(2025, 7, 1), date(2025, 7, 31)) == (date(2025, 7, 1), date(2025, 8, 1))
        assert seasonal.full_month_range(date(2025, 7, 3), date(2025, 7, 20)) is None

    def test_repeating_months(self):
        assert seasonal.repeating_months(MONTHS) == [7, 8, 9]

    @pytest.mark.parametrize(
        "peaks,today,expected",
        [([10], TODAY_OCT, "in_season"), ([11], TODAY_OCT, "coming_up"), ([12], TODAY_OCT, "coming_up"),
         ([7], TODAY_OCT, "off_season"), ([1], date(2026, 12, 1), "coming_up")],
    )
    def test_status(self, peaks, today, expected):
        assert seasonal.status_for(peaks, today) == expected


class TestSeasonal:
    def test_peak_repeating_in_both_years_is_seasonal(self):
        hit = seasonal.find_seasonal("festival gifts", MONTHS, series(sep25=900, sep26=1200), TODAY_OCT)
        assert hit and hit.peak_months == [9] and hit.status == "off_season"

    def test_one_year_only_is_not_seasonal(self):
        assert seasonal.find_seasonal("x", MONTHS, series(sep26=2000), TODAY_OCT) is None

    def test_growth_trend_is_not_seasonal(self):
        growing = [50 * (i + 1) for i in range(15)]  # steadily rising every month
        assert seasonal.find_seasonal("x", MONTHS, growing, TODAY_OCT) is None

    def test_slow_decline_is_not_a_peak(self):
        # Real shape: high when history starts, then fading. September 2025 beats the median
        # but not its neighbours, so it isn't a peak even though September 2026 ticks up.
        declining = [2389, 2235, 2159, 1984, 710, 185, 91, 92, 162, 110, 78, 74, 45, 146, 529]
        assert seasonal.find_seasonal("x", MONTHS, declining, TODAY_OCT) is None

    def test_recurring_multi_month_season_counts(self):
        season = series(aug25=900, sep25=900, oct25=900, aug26=900, sep26=900)
        assert seasonal.find_seasonal("x", MONTHS, season, TODAY_OCT).peak_months == [8]

    def test_small_numbers_are_ignored(self):
        tiny = [1] * 15
        tiny[2] = tiny[14] = 50  # 50x the median, but under 100 impressions
        assert seasonal.find_seasonal("x", MONTHS, tiny, TODAY_OCT) is None


class TestSpikes:
    def test_one_month_with_most_impressions(self):
        spike = seasonal.find_spike("casino bonus app", MONTHS, [0] * 14 + [5000])
        assert spike and spike.month == date(2026, 9, 1) and spike.share == 1

    def test_spread_out_keyword_is_not_a_spike(self):
        assert seasonal.find_spike("x", MONTHS, series(may26=600)) is None


@pytest.fixture
def history(db, prop):
    """Daily rows for Jun 14 2025 .. Oct 12 2026 with three keyword shapes."""
    first, last = date(2025, 6, 14), date(2026, 10, 12)
    shapes = {
        "festival gifts": lambda d: 60 if d.month == 9 else 2,  # September both years
        "casino bonus app": lambda d: 300 if (d.year, d.month) == (2026, 5) else 0,  # one-off spike
        "steady keyword": lambda d: 5,
        "acme vs example": lambda d: 40 if d.month == 9 else 1,  # competitor + seasonal
    }
    d = first
    while d <= last:
        db.add(GscDailyMetric(property_id=prop.id, date=d, clicks=1, impressions=100, ctr=0.01, position=5))
        for q, f in shapes.items():
            if f(d):
                db.add(GscQueryMetric(property_id=prop.id, date=d, query=q, clicks=0, impressions=f(d), ctr=0, position=5))
        d += timedelta(days=1)
    db.commit()
    return prop


class TestEndpoints:
    def test_seasonal_endpoint(self, client, history):
        body = client.get(f"/api/gsc/properties/{history.id}/keywords/seasonal").json()
        assert body["repeating_months"] == ["Jul", "Aug", "Sep"]
        assert {r["query"]: r["peak_months"] for r in body["items"]} == {"festival gifts": [9], "acme vs example": [9]}
        assert len(body["months"]) == 15 and len(body["items"][0]["impressions"]) == 15
        assert sum(body["counts"].values()) == body["total"] == 2

    def test_spikes_endpoint(self, client, history):
        body = client.get(f"/api/gsc/properties/{history.id}/keywords/spikes").json()
        assert [(r["query"], r["spike_month"]) for r in body["items"]] == [("casino bonus app", "2026-05-01")]

    def test_brand_segment(self, client, history):
        body = client.get(f"/api/gsc/properties/{history.id}/keywords/seasonal", params={"segment": "brand"}).json()
        assert [r["query"] for r in body["items"]] == ["acme vs example"]  # contains the brand "example"

    def test_monthly_data_is_cached_until_next_sync(self, client, db, history):
        client.get(f"/api/gsc/properties/{history.id}/keywords/seasonal")
        built = db.get(GscMonthlyKeywordCache, history.id).built_at
        client.get(f"/api/gsc/properties/{history.id}/keywords/spikes")
        db.expire_all()
        assert db.get(GscMonthlyKeywordCache, history.id).built_at == built

    def test_no_history(self, client, prop):
        body = client.get(f"/api/gsc/properties/{prop.id}/keywords/seasonal").json()
        assert body["available"] is False and body["items"] == []

    def test_sync_builds_monthly_cache(self, client, db, prop, fake_google):
        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 70})
        assert db.scalar(select(func.count()).select_from(GscMonthlyKeywordCache)) == 1


class TestCompetitors:
    def test_save_and_read_competitor_terms(self, client, prop):
        url = f"/api/gsc/properties/{prop.id}/competitor-terms"
        assert client.get(url).json() == {"terms": []}
        assert client.put(url, json={"terms": [" Acme ", "acme", "Globex"]}).json() == {"terms": ["Acme", "Globex"]}
        assert client.get(url).json() == {"terms": ["Acme", "Globex"]}

    def test_competitor_keywords_are_tagged(self, client, db, history):
        client.put(f"/api/gsc/properties/{history.id}/competitor-terms", json={"terms": ["acme"]})
        body = client.get(f"/api/gsc/properties/{history.id}/keywords", params={"days": 28, "types": "competitor"}).json()
        assert [r["query"] for r in body["items"]] == ["acme vs example"]
        assert body["counts"]["competitor"] == 1

    def test_no_competitors_means_no_competitor_keywords(self, client, history):
        body = client.get(f"/api/gsc/properties/{history.id}/keywords", params={"days": 28}).json()
        assert body["counts"]["competitor"] == 0
