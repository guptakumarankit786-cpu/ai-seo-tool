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
