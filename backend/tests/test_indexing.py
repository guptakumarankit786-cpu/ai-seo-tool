import gzip
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.gsc import google_api, indexing
from app.models import GscInspectionRun, GscPageMetric, GscUrlInspection
from tests.conftest import days_ago

SITEMAP_URLS = {
    "https://example.com/",
    "https://example.com/products/shoe",
    "https://example.com/blog/old-post",
    "https://other-site.com/not-ours",  # outside the property — must be ignored
}

# What the fake URL Inspection API returns per URL.
STATES = {
    "https://example.com/": "Submitted and indexed",
    "https://example.com/products/shoe": "Crawled - currently not indexed",
    "https://example.com/blog/old-post": "Excluded by ‘noindex’ tag",
    "https://example.com/search-only": "Indexed, not submitted in sitemap",
}


@pytest.fixture
def fake_inspection(monkeypatch):
    calls: list[str] = []

    def inspect(token, site_url, url):
        calls.append(url)
        return {
            "coverageState": STATES.get(url, "Discovered - currently not indexed"),
            "verdict": "PASS" if indexing.is_indexed(STATES.get(url)) else "NEUTRAL",
            "googleCanonical": url,
            "lastCrawlTime": "2026-10-01T10:00:00Z",
        }

    monkeypatch.setattr(google_api, "access_token_for", lambda db, conn: "token")
    monkeypatch.setattr(google_api, "list_sitemaps", lambda token, site: [{"path": "https://example.com/sitemap.xml"}])
    monkeypatch.setattr(indexing, "sitemap_urls", lambda paths: set(SITEMAP_URLS))
    monkeypatch.setattr(google_api, "inspect_url", inspect)
    return calls


def add_search_page(db, prop, url):
    db.add(
        GscPageMetric(
            property_id=prop.id, date=days_ago(5), page=url, clicks=1, impressions=10, ctr=0.1, position=3.0
        )
    )
    db.commit()


def start_run(db, prop) -> GscInspectionRun:
    run = GscInspectionRun(property_id=prop.id, status="running")
    db.add(run)
    db.commit()
    indexing.run_inspection(run.id)
    db.refresh(run)
    return run


class TestHelpers:
    @pytest.mark.parametrize(
        "site,url,expected",
        [
            ("sc-domain:example.com", "https://example.com/a", True),
            ("sc-domain:example.com", "https://shop.example.com/a", True),
            ("sc-domain:example.com", "https://notexample.com/a", False),
            ("https://example.com/blog/", "https://example.com/blog/post", True),
            ("https://example.com/blog/", "https://example.com/shop", False),
        ],
    )
    def test_belongs_to_respects_domain_and_prefix_properties(self, site, url, expected):
        assert indexing.belongs_to(site, url) is expected

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://example.com/products/shoe", True),
            ("https://example.com/products/shoe?variant=1&utm_source=google", False),
            ("https://example.com/page#section", False),
        ],
    )
    def test_is_clean_url_rejects_parameters_and_fragments(self, url, expected):
        assert indexing.is_clean_url(url) is expected

    def test_indexed_states_match_search_console(self):
        assert indexing.is_indexed("Submitted and indexed")
        assert indexing.is_indexed("Indexed, not submitted in sitemap")
        assert not indexing.is_indexed("Crawled - currently not indexed")
        assert not indexing.is_indexed(None)


class TestSitemapParsing:
    URLSET = b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc> https://example.com/a </loc></url>
          <url><loc>https://example.com/b</loc></url>
        </urlset>"""
    INDEX = b"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/sitemap-products.xml</loc></sitemap>
        </sitemapindex>"""

    def test_urlset_returns_page_urls(self):
        assert indexing._parse_sitemap(self.URLSET) == (["https://example.com/a", "https://example.com/b"], [])

    def test_sitemap_index_returns_child_sitemaps(self):
        assert indexing._parse_sitemap(self.INDEX) == ([], ["https://example.com/sitemap-products.xml"])

    def test_gzipped_sitemaps_are_decompressed(self):
        pages, _ = indexing._parse_sitemap(gzip.compress(self.URLSET))
        assert len(pages) == 2


class TestRunInspection:
    def test_discovers_sitemap_and_clean_search_urls_only(self, db, prop, fake_inspection):
        add_search_page(db, prop, "https://example.com/search-only")
        add_search_page(db, prop, "https://example.com/products/shoe?variant=9&utm_source=google")

        run = start_run(db, prop)

        urls = set(db.scalars(select(GscUrlInspection.url)))
        assert urls == {
            "https://example.com/",
            "https://example.com/products/shoe",
            "https://example.com/blog/old-post",
            "https://example.com/search-only",
        }
        assert run.status == "success"
        assert run.urls_known == run.urls_queued == run.urls_inspected == 4

    def test_inspects_sitemap_urls_before_search_only_urls(self, db, prop, fake_inspection, monkeypatch):
        add_search_page(db, prop, "https://example.com/search-only")
        monkeypatch.setattr(indexing, "WORKERS", 1)  # deterministic order

        start_run(db, prop)

        assert fake_inspection[-1] == "https://example.com/search-only"

    def test_stores_inspection_details(self, db, prop, fake_inspection):
        start_run(db, prop)

        row = db.scalars(select(GscUrlInspection).where(GscUrlInspection.url == "https://example.com/products/shoe")).one()
        assert row.coverage_state == "Crawled - currently not indexed"
        assert row.google_canonical == "https://example.com/products/shoe"
        assert row.last_crawl_time == datetime(2026, 10, 1, 10, tzinfo=UTC)
        assert row.in_sitemap and not row.in_search

    def test_respects_remaining_daily_quota(self, db, prop, fake_inspection):
        db.add(GscInspectionRun(property_id=prop.id, status="partial", urls_inspected=indexing.DAILY_INSPECTION_LIMIT - 2))
        db.commit()

        run = start_run(db, prop)

        assert run.urls_queued == 2
        assert run.status == "partial"  # one URL still pending

    def test_quota_error_from_google_stops_run_as_partial(self, db, prop, fake_inspection, monkeypatch):
        def quota(token, site, url):
            raise google_api.QuotaExceeded("429")

        monkeypatch.setattr(google_api, "inspect_url", quota)

        run = start_run(db, prop)

        assert run.status == "partial"
        assert run.quota_exhausted is True
        assert run.urls_inspected == 0

    def test_single_url_failure_does_not_stop_the_run(self, db, prop, fake_inspection, monkeypatch):
        real = google_api.inspect_url

        def flaky(token, site, url):
            if url.endswith("old-post"):
                raise google_api.GoogleAPIError("500 from searchconsole.googleapis.com: boom")
            return real(token, site, url)

        monkeypatch.setattr(google_api, "inspect_url", flaky)

        run = start_run(db, prop)

        assert run.urls_inspected == 2
        assert run.urls_failed == 1
        failed = db.scalars(select(GscUrlInspection).where(GscUrlInspection.url.endswith("old-post"))).one()
        assert "500" in failed.error and failed.inspected_at is None

    def test_skips_recently_inspected_urls_but_rechecks_old_ones(self, db, prop, fake_inspection):
        start_run(db, prop)
        old = db.scalars(select(GscUrlInspection).where(GscUrlInspection.url == "https://example.com/")).one()
        old.inspected_at = datetime.now(UTC) - timedelta(days=8)
        db.commit()
        fake_inspection.clear()

        run = start_run(db, prop)

        assert fake_inspection == ["https://example.com/"]
        assert run.urls_queued == 1 and run.status == "success"

    def test_rediscovery_drops_urls_that_left_the_sitemap(self, db, prop, fake_inspection, monkeypatch):
        start_run(db, prop)
        monkeypatch.setattr(indexing, "sitemap_urls", lambda paths: {"https://example.com/"})

        start_run(db, prop)

        assert set(db.scalars(select(GscUrlInspection.url))) == {"https://example.com/"}


class TestEndpoints:
    def test_summary_groups_not_indexed_reasons(self, client, db, prop, fake_inspection):
        start_run(db, prop)

        body = client.get(f"/api/gsc/properties/{prop.id}/indexing").json()

        assert body["known"] == 3
        assert body["indexed"] == 1
        assert body["not_indexed"] == 2
        assert {r["reason"]: r["pages"] for r in body["reasons"]} == {
            "Crawled - currently not indexed": 1,
            "Excluded by ‘noindex’ tag": 1,
        }
        assert body["used_last_24h"] == 3
        assert body["latest_run"]["status"] == "success"

    def test_pages_endpoint_filters_by_reason(self, client, db, prop, fake_inspection):
        start_run(db, prop)

        body = client.get(
            f"/api/gsc/properties/{prop.id}/indexing/pages",
            params={"reason": "Crawled - currently not indexed"},
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["url"] == "https://example.com/products/shoe"

    def test_start_returns_202_and_runs_in_background(self, client, db, prop, fake_inspection):
        resp = client.post(f"/api/gsc/properties/{prop.id}/indexing")

        assert resp.status_code == 202
        run = db.scalars(select(GscInspectionRun)).one()
        assert run.status == "success"

    def test_start_rejects_concurrent_run(self, client, db, prop):
        db.add(GscInspectionRun(property_id=prop.id, status="running"))
        db.commit()
        assert client.post(f"/api/gsc/properties/{prop.id}/indexing").status_code == 409

    def test_start_replaces_orphaned_run(self, client, db, prop, fake_inspection):
        old = GscInspectionRun(property_id=prop.id, status="running", started_at=datetime.now(UTC) - timedelta(hours=3))
        db.add(old)
        db.commit()

        assert client.post(f"/api/gsc/properties/{prop.id}/indexing").status_code == 202
        db.refresh(old)
        assert old.status == "failed"

    def test_start_refuses_when_daily_quota_is_used(self, client, db, prop):
        db.add(GscInspectionRun(property_id=prop.id, status="success", urls_inspected=indexing.DAILY_INSPECTION_LIMIT))
        db.commit()
        assert client.post(f"/api/gsc/properties/{prop.id}/indexing").status_code == 429

    def test_quota_window_is_rolling_24_hours(self, client, db, prop, fake_inspection):
        db.add(
            GscInspectionRun(
                property_id=prop.id,
                status="success",
                urls_inspected=indexing.DAILY_INSPECTION_LIMIT,
                started_at=datetime.now(UTC) - timedelta(hours=25),
            )
        )
        db.commit()
        assert client.post(f"/api/gsc/properties/{prop.id}/indexing").status_code == 202

    def test_unknown_property_returns_404(self, client):
        assert client.get("/api/gsc/properties/999/indexing").status_code == 404
        assert client.post("/api/gsc/properties/999/indexing").status_code == 404
