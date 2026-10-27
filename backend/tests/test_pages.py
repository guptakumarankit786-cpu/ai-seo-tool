"""Page explorer: page types, filter flags, type totals and comparisons."""
from datetime import timedelta

import pytest

from app.gsc import pages
from app.models import GscDailyMetric, GscPageMetric
from tests.conftest import days_ago

END = days_ago(3)
PREV = END - timedelta(days=7)  # inside the previous 7-day window
SEEN = END - timedelta(days=30)  # inside the 90-day "new" look-back
URL = "/api/gsc/properties/{}/page-report"
SITE = "https://example.com"


def add_page(db, prop, path, clicks, impressions, position, day=END):
    db.add(
        GscPageMetric(
            property_id=prop.id, date=day, page=SITE + path, clicks=clicks, impressions=impressions,
            ctr=clicks / impressions if impressions else 0, position=position,
        )
    )


def get(client, prop, **params):
    params.setdefault("days", 7)
    resp = client.get(URL.format(prop.id), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_page(body):
    return {r["page"].removeprefix(SITE): r for r in body["items"]}


@pytest.fixture
def seeded(db, prop):
    for i in range(120):  # daily totals so the comparison and look-back windows are covered
        db.add(GscDailyMetric(property_id=prop.id, date=END - timedelta(days=i), clicks=1, impressions=10, ctr=0.1, position=5))
    current = [
        # path, clicks, impressions, position
        ("/", 100, 1000, 1.5),
        ("/collections/sale", 20, 2000, 2.0),  # declining (40 before)
        ("/collections/new", 1, 400, 3.0),  # low CTR at position 3; new (not seen before)
        *[(f"/products/p{i}", 10, 100, 3.0) for i in range(1, 6)],  # teach the typical CTR at position 3
        ("/blogs/news/how-to", 0, 300, 12.0),  # zero clicks + striking distance
        ("/pages/about", 3, 30, 1.0),
        ("/products/p1?variant=7&utm_source=google", 0, 500, 3.0),  # Shopping listing
    ]
    for path, clicks, impressions, position in current:
        add_page(db, prop, path, clicks, impressions, position)
        if path != "/collections/new":
            add_page(db, prop, path, 1, 10, position, day=SEEN)
    add_page(db, prop, "/collections/sale", 40, 2000, 2.0, day=PREV)
    add_page(db, prop, "/products/p1", 2, 100, 3.0, day=PREV)  # 2 → 10: rising
    add_page(db, prop, "/blogs/news/old-post", 5, 50, 6.0, day=PREV)  # lost
    db.commit()
    return prop


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://example.com/", "home"),
        ("https://example.com", "home"),
        ("https://example.com/products/a", "products"),
        ("https://example.com/collections/sale/products/a", "products"),
        ("https://example.com/collections/sale", "collections"),
        ("https://example.com/blogs/news/how-to", "blogs"),
        ("https://example.com/blog/how-to", "blogs"),
        ("https://example.com/pages/about", "pages"),
        ("https://example.com/cart", "other"),
        ("https://example.com/products/a?variant=1", "shopping"),
    ],
)
def test_page_type(url, kind):
    assert pages.page_type(url) == kind


class TestFlags:
    def test_each_rule(self, client, seeded):
        rows = by_page(get(client, seeded, limit=500))

        assert "low_ctr" in rows["/collections/new"]["flags"]
        assert "new" in rows["/collections/new"]["flags"]
        assert {"zero_clicks", "striking"} <= set(rows["/blogs/news/how-to"]["flags"])
        assert "rising" in rows["/products/p1"]["flags"]
        assert "declining" in rows["/collections/sale"]["flags"]
        assert rows["/blogs/news/old-post"]["flags"] == ["lost", "declining"]  # as for keywords
        assert rows["/blogs/news/old-post"]["position"] is None
        assert {"high_performance"} <= set(rows["/"]["flags"]) and "new" not in rows["/"]["flags"]
        assert "high_performance" not in rows["/pages/about"]["flags"]

    def test_new_needs_real_visibility_and_skips_shopping(self, client, db, seeded):
        add_page(db, seeded, "/blogs/news/one-off", 0, 2, 9.0)  # 2 impressions: noise, not a new page
        add_page(db, seeded, "/products/p9?variant=1", 0, 300, 3.0)  # Shopping URLs churn
        add_page(db, seeded, "/products/p2?variant=3", 3, 30, 3.0, day=PREV)
        db.commit()
        rows = by_page(get(client, seeded, limit=500))

        assert "new" not in rows["/blogs/news/one-off"]["flags"]
        assert "new" not in rows["/products/p9?variant=1"]["flags"]
        assert "lost" not in rows["/products/p2?variant=3"]["flags"]

    def test_home_is_never_striking_distance(self, client, db, prop):
        add_page(db, prop, "/", 50, 5000, 12.0)  # average over thousands of searches
        db.commit()
        assert "striking" not in by_page(get(client, prop))["/"]["flags"]

    def test_shopping_listings_are_never_low_ctr_or_striking(self, client, seeded):
        row = by_page(get(client, seeded, limit=500))["/products/p1?variant=7&utm_source=google"]
        assert row["type"] == "shopping"
        assert row["flags"] == ["zero_clicks"]

    def test_typical_ctr_is_learned_from_pages(self, client, seeded):
        # position 3: five product pages 10/100 + /collections/new 1/400 (the Shopping URL is left out)
        row = by_page(get(client, seeded, limit=500))["/collections/new"]
        assert row["expected_ctr"] == pytest.approx(51 / 900)

    def test_no_history_means_no_movers_or_new(self, client, db, prop):
        add_page(db, prop, "/collections/sale", 20, 2000, 2.0)
        add_page(db, prop, "/collections/sale", 40, 2000, 2.0, day=PREV)
        db.commit()

        body = get(client, prop)

        assert (body["compare_available"], body["new_available"]) == (False, False)
        assert by_page(body)["/collections/sale"]["flags"] == ["high_performance"]
        assert body["groups"][0]["prev_clicks"] is None


class TestGroupsAndFilters:
    def test_type_totals_with_comparison(self, client, seeded):
        groups = {g["type"]: g for g in get(client, seeded)["groups"]}

        assert list(groups) == ["home", "collections", "products", "blogs", "pages", "shopping"]
        assert (groups["collections"]["clicks"], groups["collections"]["prev_clicks"]) == (21, 40)
        assert groups["collections"]["pages"] == 2
        assert groups["collections"]["position"] == pytest.approx((2.0 * 2000 + 3.0 * 400) / 2400)
        assert (groups["blogs"]["pages"], groups["blogs"]["prev_clicks"]) == (1, 5)  # the lost post counts before

    def test_type_and_filters_combine(self, client, seeded):
        body = get(client, seeded, type="blogs", filter="zero_clicks")

        assert list(by_page(body)) == ["/blogs/news/how-to"]
        assert body["counts"]["all"] == 2  # both blog pages, before chip filters
        assert body["counts"]["striking"] == 1

    def test_several_types(self, client, seeded):
        body = get(client, seeded, type=["home", "pages"], limit=500)
        assert set(by_page(body)) == {"/", "/pages/about"}

    def test_search_sort_and_paging(self, client, seeded):
        body = get(client, seeded, search="PRODUCTS/P", sort="page", order="asc", limit=2, offset=1)

        assert body["total"] == 6
        assert list(by_page(body)) == ["/products/p1?variant=7&utm_source=google", "/products/p2"]

    def test_unknown_property_returns_404(self, client):
        assert client.get(URL.format(999)).status_code == 404
