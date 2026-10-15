"""Striking distance and cannibalisation from live query+page data (Google mocked)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.gsc import google_api, opportunities
from app.models import GscDailyMetric, GscProperty, GscQueryPageCacheEntry
from tests.conftest import days_ago

BASE = "/api/gsc/properties/{}/opportunities/{}"


def row(query, page, clicks, impressions, position):
    return {"keys": [query, page], "clicks": clicks, "impressions": impressions,
            "ctr": clicks / impressions, "position": position}


# Typical CTR at position 3: non-brand 5 keywords x (10 / 200) = 5%; only one brand keyword there.
TYPICAL = [row(f"typical {n}", f"https://example.com/t{n}", 10, 200, 3.0) for n in range(5)] + [
    row("example store", "https://example.com/", 50, 200, 3.0)
]

ROWS = TYPICAL + [
    # striking distance: main page = most impressions, ranks 4-20
    row("running shoes", "https://example.com/running", 4, 1000, 8.0),
    row("running shoes", "https://example.com/blog/running", 1, 80, 15.0),  # 7%: not cannibalising
    row("trail shoes", "https://example.com/trail", 0, 320, 18.0),
    row("too deep", "https://example.com/deep", 0, 500, 35.0),  # position > 20
    row("already top", "https://example.com/top", 30, 400, 2.0),  # position < 4
    row("tiny keyword", "https://example.com/tiny", 0, 20, 9.0),  # too few impressions
    row("example sale", "https://example.com/sale", 2, 300, 6.0),  # brand
    # cannibalisation
    row("how to lace shoes", "https://example.com/blog/lacing-guide", 3, 700, 2.2),
    row("how to lace shoes", "https://example.com/blog/lacing-tips", 1, 250, 2.4),
    row("how to lace shoes", "https://example.com/shop", 0, 50, 30.0),  # 5% -> not competing
    row("one page wins", "https://example.com/a", 5, 950, 2.0),
    row("one page wins", "https://example.com/b", 0, 50, 9.0),
    # navigational search: Google shows sitelinks (3 pages, all top 3)
    row("acme store hours", "https://example.com/", 20, 400, 1.0),
    row("acme store hours", "https://example.com/about", 0, 350, 1.1),
    row("acme store hours", "https://example.com/contact", 0, 300, 1.2),
    # a Shopping listing URL with the most impressions must not become the "main page"
    row("trail shoes", "https://example.com/trail?variant=1&utm_source=google", 0, 900, 5.0),
]


@pytest.fixture
def live(db, prop, monkeypatch):
    """Stored history (for the window) + a fake live query+page pull."""
    for i in range(30):
        db.add(GscDailyMetric(property_id=prop.id, date=days_ago(3 + i), clicks=1, impressions=10, ctr=0.1, position=5))
    db.commit()
    calls = []

    def fake(token, site_url, start, end, dims):
        assert dims == ["query", "page"]
        calls.append((start, end))
        return list(ROWS)

    monkeypatch.setattr(google_api, "access_token_for", lambda db, conn: "token")
    monkeypatch.setattr(google_api, "search_analytics", fake)
    return calls


def get(client, prop, view, **params):
    params.setdefault("days", 28)
    resp = client.get(BASE.format(prop.id, view), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestStrikingDistance:
    def test_main_page_in_positions_4_to_20_with_enough_impressions(self, client, prop, live):
        body = get(client, prop, "striking-distance", sort="impressions")
        assert [(r["query"], r["page"]) for r in body["items"]] == [
            ("running shoes", "https://example.com/running"),
            ("trail shoes", "https://example.com/trail"),
            ("example sale", "https://example.com/sale"),
        ]
        running = body["items"][0]
        assert running["other_pages"] == 1
        assert running["position"] == 8.0
        assert body["min_impressions"] == 100

    def test_potential_uses_the_sites_own_ctr_at_position_3(self, client, prop, live):
        body = get(client, prop, "striking-distance", segment="non_brand")
        running = next(r for r in body["items"] if r["query"] == "running shoes")
        assert running["target_ctr"] == pytest.approx(0.05)
        assert running["potential"] == round(1000 * (0.05 - 0.004))  # 46 extra clicks
        assert [r["query"] for r in body["items"]] == ["running shoes", "trail shoes"]  # by potential

    def test_brand_falls_back_to_pooled_ctr_when_too_few_brand_keywords(self, client, prop, live):
        body = get(client, prop, "striking-distance", segment="brand")
        sale = body["items"][0]
        assert sale["query"] == "example sale" and sale["brand"] is True
        assert sale["target_ctr"] == pytest.approx(100 / 1200)  # pooled: (5x10 + 50) / (5x200 + 200)


class TestCannibalisation:
    def test_two_or_more_pages_each_with_10_percent(self, client, prop, live):
        body = get(client, prop, "cannibalisation")
        real = [r for r in body["items"] if not r["sitelinks_likely"]]
        assert [r["query"] for r in real] == ["how to lace shoes"]
        item = real[0]
        assert item["competing_pages"] == 2
        assert item["impressions"] == 1000
        assert [(p["page"], round(p["share"], 2)) for p in item["pages"]] == [
            ("https://example.com/blog/lacing-guide", 0.7),
            ("https://example.com/blog/lacing-tips", 0.25),
        ]

    def test_brand_segment(self, client, prop, live):
        assert get(client, prop, "cannibalisation", segment="brand")["total"] == 0

    def test_sitelinks_are_flagged_and_listed_last(self, client, prop, live):
        body = get(client, prop, "cannibalisation")
        assert [(r["query"], r["sitelinks_likely"]) for r in body["items"]] == [
            ("how to lace shoes", False),
            ("acme store hours", True),
        ]


class TestShoppingUrls:
    def test_shopping_listing_urls_are_ignored(self, client, prop, live):
        body = get(client, prop, "striking-distance", sort="impressions")
        trail = next(r for r in body["items"] if r["query"] == "trail shoes")
        assert trail["page"] == "https://example.com/trail"
        assert trail["other_pages"] == 0


class TestLiveCache:
    def entries(self, db):
        return db.scalar(select(func.count()).select_from(GscQueryPageCacheEntry))

    def test_fetches_once_then_serves_from_cache(self, client, prop, live):
        get(client, prop, "striking-distance")
        get(client, prop, "cannibalisation")
        get(client, prop, "striking-distance", segment="brand")
        assert len(live) == 1

    def test_refetches_after_a_new_sync(self, client, db, prop, live):
        get(client, prop, "striking-distance")
        p = db.get(GscProperty, prop.id)
        p.last_synced_at = datetime.now(UTC) + timedelta(seconds=1)
        db.commit()
        get(client, prop, "striking-distance")
        assert len(live) == 2 and self.entries(db) == 1

    def test_refetches_when_a_day_old(self, client, db, prop, live):
        get(client, prop, "striking-distance")
        entry = db.scalars(select(GscQueryPageCacheEntry)).one()
        entry.built_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()
        get(client, prop, "striking-distance")
        assert len(live) == 2

    def test_keeps_a_few_ranges_per_property(self, client, db, prop, live):
        for days in (7, 14, 28, 60, 90):
            get(client, prop, "striking-distance", days=days)
        assert self.entries(db) == opportunities.CACHE_ENTRIES_PER_PROPERTY


class TestValidation:
    def test_ranges_over_90_days_are_refused(self, client, prop):
        assert client.get(BASE.format(prop.id, "striking-distance"), params={"days": 180}).status_code == 422

    def test_unknown_property(self, client):
        assert client.get(BASE.format(999, "cannibalisation")).status_code == 404

    def test_google_error_is_reported(self, client, db, prop, monkeypatch):
        def boom(*a, **k):
            raise google_api.GoogleAPIError("403 from www.googleapis.com: forbidden")

        monkeypatch.setattr(google_api, "access_token_for", lambda db, conn: "token")
        monkeypatch.setattr(google_api, "search_analytics", boom)
        resp = client.get(BASE.format(prop.id, "striking-distance"))
        assert resp.status_code == 502 and "403" in resp.json()["detail"]
