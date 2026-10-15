"""Keyword explorer: type tagging, filters, comparisons and caching."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.gsc import keywords, sync
from app.models import GscDailyMetric, GscKeywordCacheEntry, GscProperty, GscQueryMetric
from tests.conftest import days_ago

END = days_ago(3)
URL = "/api/gsc/properties/{}/keywords"


def add_query(db, prop, query, clicks, impressions, position=5.0, day=END):
    db.add(
        GscQueryMetric(
            property_id=prop.id, date=day, query=query, clicks=clicks, impressions=impressions,
            ctr=clicks / impressions if impressions else 0, position=position,
        )
    )


def add_history(db, prop, days=120):
    """Daily totals far enough back that comparison and "new" look-back windows are covered."""
    for i in range(days):
        db.add(GscDailyMetric(property_id=prop.id, date=END - timedelta(days=i), clicks=1, impressions=10, ctr=0.1, position=5))


def get(client, prop, **params):
    params.setdefault("days", 7)
    resp = client.get(URL.format(prop.id), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_query(body):
    return {r["query"]: r for r in body["items"]}


@pytest.fixture
def seeded(db, prop):
    add_history(db, prop)
    current = [
        # query, clicks, impressions, position
        ("example shoes", 50, 500, 1.2),  # brand, high performer
        ("how to clean running shoes", 6, 300, 6.0),  # question + long-tail
        ("can i wash trainers", 2, 100, 7.0),  # question (starts with "can")
        ("trainers?", 1, 40, 9.0),  # question ("?")
        ("ways to lace shoes", 1, 30, 8.0),  # question phrase
        ("buy running shoes online", 9, 200, 4.0),  # buying + long-tail
        ("shoe shop near me", 3, 120, 5.0),  # buying phrase
        ("nike vs adidas", 2, 90, 6.0),  # buying ("vs")
        ("topless sandals", 1, 50, 9.0),  # "top" only as part of a word -> not buying
        ("history of sneakers", 4, 200, 1.0),  # not a question; low CTR at position 1
        ("plain sneakers", 0, 400, 15.0),  # zero clicks
        ("brand new keyword", 4, 60, 3.0),  # new (not seen before)
        ("growing keyword", 20, 200, 2.0),  # rising vs previous week
        ("shrinking keyword", 2, 150, 4.0),  # declining vs previous week
    ]
    for q, c, i, p in current:
        add_query(db, prop, q, c, i, p)
    # Keywords at position ~1 with healthy CTR teach the site's "expected" CTR (~30%).
    for n in range(5):
        add_query(db, prop, f"healthy {n}", 60, 200, 1.0)

    prev_day = END - timedelta(days=7)
    for q, c in [("growing keyword", 5), ("shrinking keyword", 15), ("gone keyword", 8), ("example shoes", 48)]:
        add_query(db, prop, q, c, 150, 3.0, day=prev_day)
    # Everything except "brand new keyword" was already seen in the 90-day look-back.
    lookback_day = END - timedelta(days=40)
    for q, *_ in current:
        if q != "brand new keyword":
            add_query(db, prop, q, 1, 10, 5.0, day=lookback_day)
    for n in range(5):
        add_query(db, prop, f"healthy {n}", 1, 10, 1.0, day=lookback_day)
    db.commit()
    return prop


def tagged(body, query):
    return set(by_query(body)[query]["types"])


class TestTypes:
    def test_question_keywords(self, client, seeded):
        body = get(client, seeded, limit=500)
        for q in ("how to clean running shoes", "can i wash trainers", "trainers?", "ways to lace shoes"):
            assert "question" in tagged(body, q), q
        assert "question" not in tagged(body, "history of sneakers")

    def test_buying_intent_keywords(self, client, seeded):
        body = get(client, seeded, limit=500)
        for q in ("buy running shoes online", "shoe shop near me", "nike vs adidas"):
            assert "buying" in tagged(body, q), q
        assert "buying" not in tagged(body, "topless sandals")  # whole words only

    def test_long_tail_is_four_or_more_words(self, client, seeded):
        body = get(client, seeded, limit=500)
        assert "long_tail" in tagged(body, "how to clean running shoes")
        assert "long_tail" in tagged(body, "buy running shoes online")
        assert "long_tail" in tagged(body, "shoe shop near me")  # exactly 4 words
        assert "long_tail" not in tagged(body, "nike vs adidas")

    def test_new_keywords_were_not_seen_in_the_look_back(self, client, seeded):
        body = get(client, seeded, types="new", limit=500)
        assert [r["query"] for r in body["items"]] == ["brand new keyword"]
        assert body["new_available"] is True

    def test_rising_declining_and_lost(self, client, seeded):
        body = get(client, seeded, limit=500)
        assert "rising" in tagged(body, "growing keyword")
        assert "declining" in tagged(body, "shrinking keyword")
        assert "rising" not in tagged(body, "example shoes")  # +2 clicks is below the threshold

        lost = get(client, seeded, types="lost")
        assert [r["query"] for r in lost["items"]] == ["gone keyword"]
        assert lost["items"][0]["clicks"] == 0 and lost["items"][0]["prev_clicks"] == 8

    def test_lost_keywords_are_hidden_unless_selected(self, client, seeded):
        assert "gone keyword" not in by_query(get(client, seeded, limit=500))

    def test_zero_clicks_needs_enough_impressions(self, client, seeded):
        body = get(client, seeded, types="zero_clicks")
        assert [r["query"] for r in body["items"]] == ["plain sneakers"]

    def test_low_ctr_compares_with_the_sites_own_ctr_at_that_position(self, client, seeded):
        body = by_query(get(client, seeded, types="low_ctr", limit=500))
        row = body["history of sneakers"]  # position 1 at 2% CTR
        # Typical non-brand CTR at position 1: all clicks / impressions there = 304 / 1200.
        assert row["expected_ctr"] == pytest.approx(304 / 1200)
        assert row["ctr"] == pytest.approx(0.02)
        assert not any(q.startswith("healthy") for q in body)  # typical CTR -> not flagged
        assert "plain sneakers" not in body  # position 15 is outside the top 10
        # Brand keywords are judged against brand CTR; one brand keyword is too few to judge.
        assert "example shoes" not in body

    def test_high_performance_is_the_keywords_bringing_80_percent_of_clicks(self, client, seeded):
        body = get(client, seeded, types="high_performance", limit=500)
        clicks = [r["clicks"] for r in body["items"]]
        everything = get(client, seeded, limit=500)
        total = sum(r["clicks"] for r in everything["items"])
        assert clicks == sorted(clicks, reverse=True)
        assert sum(clicks[:-1]) < 0.8 * total <= sum(clicks)


class TestFilters:
    def test_counts_per_type(self, client, seeded):
        counts = get(client, seeded)["counts"]
        assert counts["all"] == 19
        assert counts["question"] == 4
        assert counts["buying"] == 3
        assert counts["new"] == 1
        assert counts["lost"] == 1

    def test_types_combine_with_and(self, client, seeded):
        body = client.get(URL.format(seeded.id), params={"days": 7, "types": ["question", "long_tail"]}).json()
        assert set(by_query(body)) == {"how to clean running shoes", "can i wash trainers", "ways to lace shoes"}

    def test_brand_segments(self, client, seeded):
        brand = get(client, seeded, segment="brand")
        assert [r["query"] for r in brand["items"]] == ["example shoes"]
        non_brand = get(client, seeded, segment="non_brand", limit=500)
        assert "example shoes" not in by_query(non_brand)
        assert non_brand["counts"]["all"] == 18

    def test_search_sort_and_paging(self, client, seeded):
        body = get(client, seeded, search="SNEAKERS", sort="impressions", order="desc")
        assert [r["query"] for r in body["items"]] == ["plain sneakers", "history of sneakers"]

        page1 = get(client, seeded, limit=3)
        page2 = get(client, seeded, limit=3, offset=3)
        assert page1["total"] == page2["total"] == 19
        assert not set(by_query(page1)) & set(by_query(page2))
        assert [r["clicks"] for r in page1["items"]] == sorted((r["clicks"] for r in page1["items"]), reverse=True)

    def test_rejects_unknown_type_and_sort(self, client, prop):
        assert client.get(URL.format(prop.id), params={"types": "funny"}).status_code == 422
        assert client.get(URL.format(prop.id), params={"sort": "drop table"}).status_code == 422


class TestAvailability:
    def test_without_history_comparison_types_are_off(self, client, db, prop):
        add_query(db, prop, "example shoes", 5, 50)
        db.add(GscDailyMetric(property_id=prop.id, date=END, clicks=5, impressions=50, ctr=0.1, position=2))
        db.commit()

        body = get(client, prop)

        assert body["compare_available"] is False and body["new_available"] is False
        assert body["counts"]["rising"] == body["counts"]["new"] == 0

    def test_unknown_property(self, client):
        assert client.get(URL.format(999)).status_code == 404


class TestCache:
    def entries(self, db):
        return db.scalar(select(func.count()).select_from(GscKeywordCacheEntry))

    def test_filters_reuse_one_cached_set(self, client, db, seeded):
        get(client, seeded)
        get(client, seeded, types="question")
        get(client, seeded, segment="brand", sort="ctr")
        assert self.entries(db) == 1

    def test_new_sync_rebuilds_the_set(self, client, db, seeded):
        get(client, seeded)
        add_query(db, seeded, "fresh keyword", 3, 30)
        db.commit()
        assert "fresh keyword" not in by_query(get(client, seeded, limit=500))  # served from cache

        prop = db.get(GscProperty, seeded.id)
        prop.last_synced_at = datetime.now(UTC) + timedelta(seconds=1)
        db.commit()

        assert "fresh keyword" in by_query(get(client, seeded, limit=500))
        assert self.entries(db) == 1

    def test_brand_terms_change_uses_a_new_set(self, client, db, seeded):
        get(client, seeded)
        client.put(f"/api/gsc/properties/{seeded.id}/brand-terms", json={"terms": ["example", "nike"]})
        body = get(client, seeded, segment="brand")
        assert set(by_query(body)) == {"example shoes", "nike vs adidas"}

    def test_sync_warms_the_default_view(self, client, db, prop, fake_google):
        client.post(f"/api/gsc/properties/{prop.id}/sync", json={"days": 10})
        assert self.entries(db) == 1

    def test_old_sets_are_pruned(self, client, db, seeded):
        for days in range(1, keywords.CACHE_ENTRIES_PER_PROPERTY + 4):
            get(client, seeded, days=days)
        assert self.entries(db) == keywords.CACHE_ENTRIES_PER_PROPERTY


def test_min_impressions_scales_with_window():
    assert keywords.min_impressions(28) == 100
    assert keywords.min_impressions(7) == 25
    assert keywords.min_impressions(1) == 20
    assert keywords.min_impressions(sync.MAX_HISTORY_DAYS) == round(100 * 486 / 28)
