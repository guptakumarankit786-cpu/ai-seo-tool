"""GA4 property discovery and matching to Search Console sites."""
import pytest

from app.gsc import ga4, google_api
from app.models import Ga4Property, GscProperty


def ga4_prop(n, url, name="Site"):
    return {"property": f"properties/{n}", "name": name, "account": "Example", "website_url": url}


@pytest.fixture
def analytics(db, connection, fake_google):
    connection.scopes = f"webmasters.readonly {google_api.ANALYTICS_SCOPE}"
    db.commit()
    return fake_google


def linked(db, prop):
    db.refresh(prop)
    g = db.get(Ga4Property, prop.ga4_property_id) if prop.ga4_property_id else None
    return g and g.property


@pytest.mark.parametrize(
    "url",
    ["sc-domain:example.com", "https://www.example.com/", "http://example.com/blog/", "example.com", "WWW.Example.com"],
)
def test_site_host(url):
    assert ga4.site_host(url) == "example.com"


def test_matches_by_website_ignoring_www_and_scheme(db, connection, prop, analytics):
    analytics.ga4 = [ga4_prop(1, "https://www.example.com"), ga4_prop(2, "https://other.com"), ga4_prop(3, None)]
    ga4.refresh_properties(db, connection)
    assert linked(db, prop) == "properties/1"
    assert db.query(Ga4Property).count() == 3


def test_several_candidates_pick_most_sessions_then_newest(db, connection, prop, analytics):
    analytics.ga4 = [ga4_prop(5, "example.com"), ga4_prop(9, "https://example.com"), ga4_prop(7, "http://www.example.com")]
    analytics.ga4_sessions = {"properties/5": 900, "properties/9": 10}
    ga4.refresh_properties(db, connection)
    assert linked(db, prop) == "properties/5"

    analytics.ga4_sessions = {}
    ga4.match_all(db)
    assert linked(db, prop) == "properties/9"  # all zero: the newest


def test_no_analytics_scope_does_nothing(db, connection, prop, fake_google):
    fake_google.ga4 = [ga4_prop(1, "example.com")]
    ga4.refresh_properties(db, connection)
    assert db.query(Ga4Property).count() == 0


def test_manual_choice_survives_refresh_and_auto_resets(client, db, connection, prop, analytics):
    analytics.ga4 = [ga4_prop(1, "example.com"), ga4_prop(2, "other.com")]
    ga4.refresh_properties(db, connection)
    other = db.query(Ga4Property).filter_by(property="properties/2").one()

    r = client.put(f"/api/gsc/properties/{prop.id}/ga4", json={"ga4_property_id": other.id})
    assert r.status_code == 200 and r.json()["ga4_manual"] is True
    ga4.refresh_properties(db, connection)
    assert linked(db, prop) == "properties/2"

    r = client.put(f"/api/gsc/properties/{prop.id}/ga4", json={"ga4_property_id": None})
    assert r.json()["ga4_property_id"] is None

    r = client.put(f"/api/gsc/properties/{prop.id}/ga4", json={"auto": True})
    assert r.json()["ga4_manual"] is False
    assert linked(db, prop) == "properties/1"


def test_removed_manual_property_falls_back_to_matching(db, connection, prop, analytics):
    analytics.ga4 = [ga4_prop(1, "example.com"), ga4_prop(2, "other.com")]
    ga4.refresh_properties(db, connection)
    prop.ga4_property_id = db.query(Ga4Property).filter_by(property="properties/2").one().id
    prop.ga4_manual = True
    db.commit()

    analytics.ga4 = [ga4_prop(1, "example.com")]
    ga4.refresh_properties(db, connection)
    assert linked(db, prop) == "properties/1"
    assert db.get(GscProperty, prop.id).ga4_manual is False


def test_unknown_ga4_property_is_404(client, prop):
    assert client.put(f"/api/gsc/properties/{prop.id}/ga4", json={"ga4_property_id": 999}).status_code == 404


def test_status_lists_ga4_properties_and_links(client, db, connection, prop, analytics):
    analytics.ga4 = [ga4_prop(1, "example.com", name="Example GA4")]
    ga4.refresh_properties(db, connection)
    body = client.get("/api/gsc/status").json()
    assert [g["display_name"] for g in body["ga4_properties"]] == ["Example GA4"]
    assert body["connections"][0]["properties"][0]["ga4_property_id"] == body["ga4_properties"][0]["id"]


def test_falls_back_to_ga4_named_after_the_domain_then_the_brand(db, connection, analytics):
    a = GscProperty(connection_id=connection.id, site_url="sc-domain:acme.ai", permission_level="siteOwner")
    b = GscProperty(connection_id=connection.id, site_url="https://www.shopbrand.com/", permission_level="siteOwner")
    c = GscProperty(connection_id=connection.id, site_url="https://nomatch.com/", permission_level="siteOwner")
    db.add_all([a, b, c])
    db.commit()
    analytics.ga4 = [
        ga4_prop(1, "https://acme-clinic.in", name="acme.ai - GA4"),  # tracks another domain, named after this one
        ga4_prop(2, None, name="Shop Brand Store"),  # no website, brand in the name
        ga4_prop(3, "https://acmeai.example.org", name="Other"),
    ]
    ga4.refresh_properties(db, connection)
    assert linked(db, a) == "properties/1"
    assert linked(db, b) == "properties/2"
    assert linked(db, c) is None


def test_website_match_beats_a_name_match(db, connection, prop, analytics):
    analytics.ga4 = [ga4_prop(1, "https://other.com", name="example.com old"), ga4_prop(2, "example.com", name="Site")]
    ga4.refresh_properties(db, connection)
    assert linked(db, prop) == "properties/2"


# ---------- organic landing pages next to Search Console pages ----------

from datetime import timedelta  # noqa: E402

from app.models import GscDailyMetric, GscPageMetric  # noqa: E402
from tests.conftest import days_ago  # noqa: E402


def ga_row(host, path, sessions, key_events=0, orders=0, revenue=0.0):
    return {"dimensionValues": [{"value": host}, {"value": path}],
            "metricValues": [{"value": str(v)} for v in (sessions, key_events, orders, revenue)]}


@pytest.fixture
def linked_site(db, connection, prop, analytics):
    end = days_ago(3)
    for i in range(14):
        db.add(GscDailyMetric(property_id=prop.id, date=end - timedelta(days=i), clicks=1, impressions=10, ctr=0.1, position=5))
    for path, clicks in [("/", 50), ("/products/a", 20), ("/products/a?variant=1", 2), ("/blogs/news/%C3%A9t%C3%A9", 5), ("/pages/x", 1)]:
        db.add(GscPageMetric(property_id=prop.id, date=end, page="https://example.com" + path, clicks=clicks, impressions=100, ctr=0.1, position=3))
    db.commit()
    analytics.ga4 = [ga4_prop(1, "https://example.com")]
    ga4.refresh_properties(db, connection)
    analytics.ga4_report = {"currency": "INR", "totals": [117, 4, 4, 2599.5], "rows": [
        ga_row("www.example.com", "/", 60, 3, 2, 1500.5),
        ga_row("example.com", "/products/a/", 25, 1, 1, 999.0),  # trailing slash
        ga_row("example.com", "/blogs/news/été", 4),  # decoded path
        ga_row("example.com", "/web-pixels@abc/sandbox/modern", 30, 0, 1, 100.0),  # not a real page
    ]}
    return prop


def test_page_report_adds_google_organic_ga4_per_page(client, linked_site, analytics):
    body = client.get(f"/api/gsc/properties/{linked_site.id}/page-report", params={"days": 7, "sort": "revenue"}).json()
    rows = {r["page"].removeprefix("https://example.com"): r for r in body["items"]}
    assert (rows["/"]["sessions"], rows["/"]["orders"], rows["/"]["revenue"]) == (60, 2, 1500.5)
    assert rows["/products/a"]["sessions"] == 25
    assert rows["/blogs/news/%C3%A9t%C3%A9"]["sessions"] == 4
    assert rows["/pages/x"]["sessions"] == 0  # GA4 saw no Google organic landing there
    assert rows["/products/a?variant=1"]["sessions"] is None  # Shopping listing
    assert [r["page"] for r in body["items"]][:2] == ["https://example.com/", "https://example.com/products/a"]
    g = body["ga4"]
    # Totals are GA4's own (sessions don't add up exactly across landing pages); unmatched = total − pages.
    assert (g["sessions"], g["orders"], g["unmatched_sessions"], g["revenue_tracked"]) == (117, 4, 28, True)

    assert analytics.ga4_report_body["dimensionFilter"] == ga4.GOOGLE_ORGANIC
    client.get(f"/api/gsc/properties/{linked_site.id}/page-report", params={"days": 7, "filter": "low_ctr"})
    assert analytics.ga4_report_calls == 1  # second request served from the cache


def test_orders_without_revenue_are_not_tracked(client, linked_site, analytics):
    analytics.ga4_report = {"currency": "INR", "totals": None, "rows": [ga_row("example.com", "/", 10, 0, 3, 0)]}
    g = client.get(f"/api/gsc/properties/{linked_site.id}/page-report", params={"days": 28}).json()["ga4"]
    assert g["revenue_tracked"] is False


def test_ga4_failure_keeps_the_search_console_report(client, linked_site, monkeypatch):
    def boom(*a):
        raise google_api.GoogleAPIError("403 from analyticsdata.googleapis.com: denied")
    monkeypatch.setattr(google_api, "ga4_run_report", boom)
    body = client.get(f"/api/gsc/properties/{linked_site.id}/page-report", params={"days": 7}).json()
    assert body["ga4"] is None and "403" in body["ga4_error"] and body["total"] == 5


def test_no_ga4_link_means_no_ga4_numbers(client, db, prop, fake_google):
    db.add(GscPageMetric(property_id=prop.id, date=days_ago(3), page="https://example.com/", clicks=1, impressions=10, ctr=0.1, position=3))
    db.add(GscDailyMetric(property_id=prop.id, date=days_ago(3), clicks=1, impressions=10, ctr=0.1, position=3))
    db.commit()
    body = client.get(f"/api/gsc/properties/{prop.id}/page-report", params={"days": 7}).json()
    assert body["ga4"] is None and body["items"][0]["sessions"] is None and fake_google.ga4_report_calls == 0


def test_page_detail_has_the_page_ga4_numbers(client, linked_site, monkeypatch):
    from app.gsc import opportunities
    monkeypatch.setattr(opportunities, "MAX_DAYS", 0)  # skip the live keyword pull
    body = client.get(f"/api/gsc/properties/{linked_site.id}/page-detail", params={"days": 7, "url": "https://example.com/"}).json()
    assert body["ga4_page"] == {"sessions": 60, "key_events": 3, "orders": 2, "revenue": 1500.5}
    assert body["ga4"]["currency"] == "INR"


@pytest.mark.parametrize(
    "path, clean",
    [
        ("/web-pixels@a1b2c3/custom/web-pixel-123@12/sandbox/modern/pages/sale", "/pages/sale"),
        ("/web-pixels@d4e5f6/custom/web-pixel-123@12/sandbox/modern", "/"),
        ("/products/a", "/products/a"),
        ("(not set)", "(not set)"),
    ],
)
def test_shopify_pixel_sandbox_prefix_is_removed(path, clean):
    assert ga4.clean_path(path) == clean


def test_pixel_sandbox_sessions_count_for_the_real_page(client, linked_site, analytics):
    analytics.ga4_report = {"currency": "INR", "totals": [100, 0, 0, 0], "rows": [
        ga_row("example.com", "/products/a", 60),
        ga_row("example.com", "/web-pixels@abc/custom/web-pixel-1@12/sandbox/modern/products/a", 40),
    ]}
    body = client.get(f"/api/gsc/properties/{linked_site.id}/page-report", params={"days": 7}).json()
    rows = {r["page"].removeprefix("https://example.com"): r for r in body["items"]}
    assert rows["/products/a"]["sessions"] == 100 and body["ga4"]["unmatched_sessions"] == 0
