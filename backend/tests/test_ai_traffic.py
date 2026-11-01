"""AI assistant traffic from GA4: classification, totals, comparison, ChatGPT ads apart, pages."""
import pytest

from app.gsc import ga4, google_api
from tests.test_ga4 import ga4_prop


@pytest.mark.parametrize(
    "source, name",
    [("chatgpt.com", "ChatGPT"), ("chat.openai.com", "ChatGPT"), ("gemini.google.com", "Gemini"), ("perplexity", "Perplexity"),
     ("claude.ai", "Claude"), ("copilot.com", "Copilot"), ("cgpt_ads", "ChatGPT ads"), ("someassistant.example", "Other AI")],
)
def test_assistant_names(source, name):
    assert ga4.assistant(source) == name


def ai_row(day, source, path, sessions, orders=0, revenue=0.0, window=None):
    dims = [day, source, "www.example.com", path] + ([window] if window else [])
    return {"dimensionValues": [{"value": v} for v in dims], "metricValues": [{"value": str(v)} for v in (sessions, 0, orders, revenue)]}


@pytest.fixture
def linked(db, connection, prop, fake_google, monkeypatch):
    connection.scopes = f"webmasters.readonly {google_api.ANALYTICS_SCOPE}"
    db.commit()
    fake_google.ga4 = [ga4_prop(1, "https://example.com")]
    ga4.refresh_properties(db, connection)
    calls = []

    def report(token, name, body):
        calls.append(body)
        if "dimensions" not in body:  # all-channel sessions per range
            return {"currency": "INR", "totals": None, "rows": [
                {"dimensionValues": [{"value": "now"}], "metricValues": [{"value": "1000"}]},
                {"dimensionValues": [{"value": "before"}], "metricValues": [{"value": "800"}]},
            ]}
        return {"currency": "INR", "totals": None, "rows": [
            ai_row("20261001", "chatgpt.com", "/products/a", 30, 2, 500.0, "now"),
            ai_row("20261002", "chatgpt.com", "/", 10, 0, 0, "now"),
            ai_row("20261002", "gemini.google.com", "/products/a", 5, 0, 0, "now"),
            ai_row("20261002", "cgpt_ads", "/", 50, 1, 100.0, "now"),
            ai_row("20260901", "chatgpt.com", "/products/a", 20, 0, 0, "before"),
            ai_row("20260901", "cgpt_ads", "/", 5, 0, 0, "before"),
        ]}

    monkeypatch.setattr(google_api, "ga4_run_report", report)
    return calls


def test_ai_traffic_report(client, prop, linked):
    body = client.get(f"/api/gsc/properties/{prop.id}/ai-traffic", params={"days": 28}).json()
    assert body["linked"] and body["error"] is None
    assert body["totals"] == {"sessions": 45, "key_events": 0, "orders": 2, "revenue": 500.0}  # ads not included
    assert body["previous"]["sessions"] == 20
    assert (body["all_sessions"], body["previous_all_sessions"]) == (1000, 800)
    assert [(a["assistant"], a["sessions"], a["previous"]["sessions"]) for a in body["assistants"]] == [("ChatGPT", 40, 20), ("Gemini", 5, 0)]
    assert (body["ads"]["sessions"], body["ads"]["previous"]["sessions"]) == (50, 5)
    assert [(d["date"], d["sessions"]) for d in body["daily"]] == [("2026-10-01", 30), ("2026-10-02", 15)]
    top = body["pages"][0]
    assert (top["url"], top["assistant"], top["sessions"], top["previous_sessions"]) == ("https://example.com/products/a", "ChatGPT", 35, 20)
    assert linked[0]["dimensionFilter"] == ga4.AI_FILTER and len(linked[0]["dateRanges"]) == 2


def test_no_comparison_sends_one_range(client, prop, linked):
    body = client.get(f"/api/gsc/properties/{prop.id}/ai-traffic", params={"days": 28, "compare": "none"}).json()
    assert body["previous"] is None and body["assistants"][0]["previous"] is None
    assert len(linked[0]["dateRanges"]) == 1


def test_not_linked(client, prop, fake_google):
    body = client.get(f"/api/gsc/properties/{prop.id}/ai-traffic").json()
    assert body["linked"] is False and body["totals"]["sessions"] == 0


def test_ga4_error_is_reported(client, prop, linked, monkeypatch):
    def boom(*a):
        raise google_api.GoogleAPIError("403 from analyticsdata.googleapis.com: denied")
    monkeypatch.setattr(google_api, "ga4_run_report", boom)
    body = client.get(f"/api/gsc/properties/{prop.id}/ai-traffic").json()
    assert "403" in body["error"]


# ---------- GA4 overview (all channels) ----------


def ov_row(dims, sessions, users=0, orders=0, revenue=0.0):
    return {"dimensionValues": [{"value": v} for v in dims], "metricValues": [{"value": str(v)} for v in (sessions, users, sessions // 2, 0, orders, revenue)]}


@pytest.fixture
def overview_ga4(db, connection, prop, fake_google, monkeypatch):
    connection.scopes = f"webmasters.readonly {google_api.ANALYTICS_SCOPE}"
    db.commit()
    fake_google.ga4 = [ga4_prop(1, "https://example.com")]
    ga4.refresh_properties(db, connection)

    def report(token, name, body):
        dims = [d["name"] for d in body.get("dimensions", [])]
        if dims == ["date"]:
            return {"currency": "INR", "totals": None, "range_totals": {"now": [100, 70, 50, 3, 2, 900.0], "before": [80, 60, 40, 1, 1, 100.0]}, "rows": [
                ov_row(["20261001", "now"], 90, 60, 1, 500.0),
                ov_row(["20261002", "now"], 10, 10, 1, 400.0),
                ov_row(["20260901", "before"], 80, 60, 1, 100.0),
            ]}
        if dims == ["sessionDefaultChannelGroup"]:
            return {"currency": "INR", "totals": None, "range_totals": {}, "rows": [
                ov_row(["Organic Search", "now"], 70, 50, 2, 900.0),
                ov_row(["Unassigned", "now"], 30, 20),
                ov_row(["Organic Search", "before"], 80, 60, 1, 100.0),
            ]}
        if dims == ["hostName", "landingPage"]:
            assert body["limit"] == ga4.TOP_PAGES
            return {"currency": "INR", "totals": None, "range_totals": {}, "rows": [ov_row(["example.com", "/"], 50, 40)]}
        return {"currency": "INR", "totals": None, "range_totals": {}, "rows": [ov_row(["mobile"], 90, 60), ov_row(["desktop"], 10, 10)]}

    monkeypatch.setattr(google_api, "ga4_run_report", report)


def test_ga4_overview(client, prop, overview_ga4):
    body = client.get(f"/api/gsc/properties/{prop.id}/ga4-overview", params={"days": 28}).json()
    assert body["linked"] and body["error"] is None
    assert (body["totals"]["sessions"], body["totals"]["users"], body["totals"]["revenue"]) == (100, 70, 900.0)  # GA4's own totals
    assert body["previous"]["sessions"] == 80
    organic = body["channels"][0]
    assert (organic["channel"], organic["sessions"], organic["orders"], organic["previous_sessions"]) == ("Organic Search", 70, 2, 80)
    assert [(d["date"], d["sessions"]) for d in body["daily"]] == [("2026-10-01", 90), ("2026-10-02", 10)]
    assert body["pages"][0]["url"] == "https://example.com/"
    assert [d["device"] for d in body["devices"]] == ["mobile", "desktop"]
    assert body["unassigned_share"] == 0.3


def test_ga4_overview_not_linked(client, prop, fake_google):
    assert client.get(f"/api/gsc/properties/{prop.id}/ga4-overview").json()["linked"] is False
