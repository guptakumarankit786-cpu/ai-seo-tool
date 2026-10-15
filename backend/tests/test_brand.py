from datetime import timedelta

import pytest

from app.gsc import brand
from app.models import GscDailyMetric, GscQueryMetric
from tests.conftest import days_ago

END = days_ago(3)


def add_query(db, prop, query, clicks, impressions, position, day=END):
    db.add(
        GscQueryMetric(
            property_id=prop.id,
            date=day,
            query=query,
            clicks=clicks,
            impressions=impressions,
            ctr=clicks / impressions,
            position=position,
        )
    )


def add_day(db, prop, clicks, impressions, day=END):
    db.add(
        GscDailyMetric(
            property_id=prop.id, date=day, clicks=clicks, impressions=impressions, ctr=clicks / impressions, position=5.0
        )
    )


@pytest.fixture
def seeded(db, prop):
    add_day(db, prop, clicks=100, impressions=2000)
    add_query(db, prop, "example shoes", 30, 100, 1.0)
    add_query(db, prop, "Ex-Ample store", 10, 100, 3.0)  # punctuation/case shouldn't matter
    add_query(db, prop, "running shoes", 20, 500, 8.0)
    add_query(db, prop, "best trainers", 5, 300, 12.0)
    # previous period
    add_day(db, prop, clicks=20, impressions=400, day=END - timedelta(days=13))  # history covers the whole previous week
    add_query(db, prop, "example", 8, 40, 1.0, day=END - timedelta(days=7))
    add_query(db, prop, "running shoes", 4, 200, 9.0, day=END - timedelta(days=7))
    db.commit()
    return prop


class TestMatching:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("acme co store", True),
            ("AcmeCo", True),
            ("acme-co shoes", True),
            ("co acme", False),
            ("running shoes", False),
        ],
    )
    def test_ignores_case_spaces_and_punctuation(self, query, expected):
        assert brand.is_brand(query, ["Acme Co"]) is expected

    def test_no_terms_means_nothing_is_brand(self):
        assert brand.is_brand("anything", []) is False

    @pytest.mark.parametrize(
        "site,expected",
        [
            ("sc-domain:example.com", ["example"]),
            ("https://www.my-brand.co.in/", ["my-brand"]),
            ("https://shop.acme.com/", ["acme"]),
        ],
    )
    def test_suggests_brand_from_domain(self, site, expected):
        assert brand.suggest_terms(site) == expected

    def test_clean_terms_dedupes_by_normalised_form(self):
        assert brand.clean_terms([" Acme Co ", "acmeco", "", "Zoom"]) == ["Acme Co", "Zoom"]


class TestBrandTermsEndpoint:
    def test_defaults_to_domain_suggestion(self, client, prop):
        body = client.get(f"/api/gsc/properties/{prop.id}/brand-terms").json()
        assert body == {"terms": ["example"], "suggested": ["example"], "is_default": True}

    def test_save_custom_terms(self, client, prop):
        body = client.put(
            f"/api/gsc/properties/{prop.id}/brand-terms", json={"terms": ["Example", "zoom", "example "]}
        ).json()
        assert body["terms"] == ["Example", "zoom"]
        assert body["is_default"] is False

    def test_empty_list_means_no_brand_terms(self, client, prop):
        body = client.put(f"/api/gsc/properties/{prop.id}/brand-terms", json={"terms": []}).json()
        assert body["terms"] == [] and body["is_default"] is False

    def test_null_resets_to_suggestion(self, client, prop):
        client.put(f"/api/gsc/properties/{prop.id}/brand-terms", json={"terms": ["x"]})
        body = client.put(f"/api/gsc/properties/{prop.id}/brand-terms", json={"terms": None}).json()
        assert body["is_default"] is True and body["terms"] == ["example"]


class TestSegments:
    def test_splits_brand_and_non_brand_with_hidden_remainder(self, client, seeded):
        body = client.get(f"/api/gsc/properties/{seeded.id}/segments?days=7").json()

        b, nb = body["brand"]["totals"], body["non_brand"]["totals"]
        assert (b["clicks"], b["impressions"]) == (40, 200)
        assert b["position"] == pytest.approx(2.0)  # (1*100 + 3*100) / 200
        assert (nb["clicks"], nb["impressions"]) == (25, 800)
        assert body["brand"]["click_share"] == pytest.approx(40 / 65)
        # Site total 100 clicks, 65 visible at query level.
        assert (body["hidden_clicks"], body["hidden_impressions"]) == (35, 1000)

    def test_previous_period(self, client, seeded):
        body = client.get(f"/api/gsc/properties/{seeded.id}/segments?days=7").json()
        assert body["brand"]["previous"]["clicks"] == 8
        assert body["non_brand"]["previous"]["clicks"] == 4

    def test_daily_series(self, client, seeded):
        daily = client.get(f"/api/gsc/properties/{seeded.id}/segments?days=7").json()["daily"]
        assert daily == [
            {
                "date": END.isoformat(),
                "brand_clicks": 40,
                "non_brand_clicks": 25,
                "brand_impressions": 200,
                "non_brand_impressions": 800,
            }
        ]

    def test_custom_terms_change_the_split(self, client, seeded):
        client.put(f"/api/gsc/properties/{seeded.id}/brand-terms", json={"terms": ["example", "running"]})
        body = client.get(f"/api/gsc/properties/{seeded.id}/segments?days=7").json()
        assert body["brand"]["totals"]["clicks"] == 60
        assert body["non_brand"]["totals"]["clicks"] == 5

    def test_no_data(self, client, prop):
        body = client.get(f"/api/gsc/properties/{prop.id}/segments?days=7").json()
        assert body["brand"]["totals"]["clicks"] == 0
        assert body["brand"]["previous"] is None
        assert body["daily"] == []


class TestQuerySegmentFilter:
    def test_brand_filter_and_flags(self, client, seeded):
        url = f"/api/gsc/properties/{seeded.id}/queries?days=7"
        brand_rows = client.get(url + "&segment=brand").json()
        non_brand_rows = client.get(url + "&segment=non_brand").json()
        all_rows = client.get(url).json()

        assert [r["key"] for r in brand_rows] == ["example shoes", "Ex-Ample store"]
        assert [r["key"] for r in non_brand_rows] == ["running shoes", "best trainers"]
        assert {r["key"]: r["brand"] for r in all_rows} == {
            "example shoes": True,
            "running shoes": False,
            "Ex-Ample store": True,
            "best trainers": False,
        }

    def test_rejects_unknown_segment(self, client, prop):
        assert client.get(f"/api/gsc/properties/{prop.id}/queries?segment=other").status_code == 422
