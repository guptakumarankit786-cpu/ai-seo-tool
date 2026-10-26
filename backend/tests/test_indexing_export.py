import io
import zipfile

import pytest

from app.gsc import advice
from app.gsc.export_parser import ExportError, parse_export


def make_zip(files: dict[str, str], bom: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, ("﻿" if bom else "") + text)  # older Search Console CSVs carry a UTF-8 BOM
    return buf.getvalue()


OVERVIEW = {
    "Critical issues.csv": (
        "Reason,Source,Validation,Trend,Pages\n"
        "Crawled - currently not indexed,Google systems,Not Started,,\"1,204\"\n"
        "Page with redirect,Website,Not Started,,310\n"
        "Excluded by ‘noindex’ tag,Website,Passed,,12\n"
    ),
    "Non-critical issues.csv": "Reason,Source,Validation,Trend,Pages\n",
    "Chart.csv": (
        "Date,Not indexed,Indexed,Impressions\n"
        "2026-10-10,1500,8000,120000\n"
        "2026-10-12,1526,8100,121000\n"
        "2026-10-11,1510,8050,119000\n"
    ),
    "Metadata.csv": "Property,sc-domain:example.com\nLast updated,2026-10-12\n",
}

DRILLDOWN = {
    "Table.csv": (
        "URL,Last crawled\n"
        "https://example.com/products/a,2026-09-30\n"
        "https://example.com/products/b,\n"
    ),
    "Chart.csv": "Date,Affected pages\n2026-10-12,1204\n",
    "Metadata.csv": "Issue,Crawled - currently not indexed\nProperty,sc-domain:example.com\n",
}

# Anonymised copies of real exports downloaded 2026-10-26: same files, headers, layout and wording
# (no BOM, "Property,Value" header, no site in Metadata, blank early chart rows); site and numbers made up.
REAL_OVERVIEW = {
    "Chart.csv": (
        "Date,Not indexed,Indexed,Impressions\n"
        "2026-07-28,,,5919\n"
        "2026-07-29,,,6031\n"
        "2026-10-22,443,103,5775\n"
        "2026-10-23,443,103,6011\n"
    ),
    "Critical issues.csv": (
        "Reason,Source,Validation,Pages\n"
        "Alternative page with proper canonical tag,Website,Not Started,244\n"
        "Not found (404),Website,Not Started,50\n"
        "Excluded by ‘noindex’ tag,Website,Not Started,43\n"
        "Blocked due to unauthorised request (401),Website,Not Started,1\n"
        "Crawled - currently not indexed,Google systems,Not Started,26\n"
        "Discovered – currently not indexed,Google systems,Not Started,3\n"
        '"Duplicate, Google chose different canonical than user",Google systems,Not Started,76\n'
    ),
    "Non-critical issues.csv": 'Reason,Source,Validation,Pages\n"Indexed, though blocked by robots.txt",Website,Not Started,2',
    "Metadata.csv": "Property,Value\nSitemap,All known pages",
}
REAL_OVERVIEW_NAME = "example.com-Coverage-2026-10-26.zip"

REAL_DRILLDOWN = {
    "Chart.csv": "Date,Affected pages\n2026-08-05,58\n2026-10-23,50\n",
    "Table.csv": (
        "URL,Last crawled\n"
        "https://www.example.com/collections/test-sale?page=4,2026-10-24\n"
        "https://www.example.com/products/test-1,2026-10-20\n"
    ),
    "Metadata.csv": "Property,Value\nSitemap,All known pages\nIssue,Not found (404)",
}


class TestAdvice:
    @pytest.mark.parametrize(
        "reason,verdict",
        [
            ("Server error (5xx)", "fix"),
            ("Crawled - currently not indexed", "fix"),
            ("Crawled – currently not indexed", "fix"),  # en dash variant
            ("Soft 404", "fix"),
            ("Discovered - currently not indexed", "review"),
            ("Excluded by ‘noindex’ tag", "review"),  # curly quotes, as Search Console writes it
            ("Not found (404)", "review"),
            ("Page with redirect", "ignore"),
            ("Alternate page with proper canonical tag", "ignore"),
            ("Alternative page with proper canonical tag", "ignore"),  # UK/Indian-English accounts
            ("Blocked due to unauthorised request (401)", "ignore"),
            ("Some brand-new reason Google adds later", "review"),
        ],
    )
    def test_verdicts(self, reason, verdict):
        assert advice.advice_for(reason).verdict == verdict

    def test_every_rule_has_an_action(self):
        for rule in advice._RULES.values():
            assert rule.summary and rule.action


class TestParser:
    def test_real_overview_format(self):
        parsed = parse_export(REAL_OVERVIEW_NAME, make_zip(REAL_OVERVIEW, bom=False))

        assert parsed.kind == "overview"
        assert parsed.site_url == "example.com"  # from Google's file name, not the "Property,Value" header
        assert sum(r.pages for r in parsed.reasons if r.critical) == parsed.not_indexed == 443
        assert (parsed.chart_date.isoformat(), parsed.indexed) == ("2026-10-23", 103)
        assert [r.reason for r in parsed.reasons if r.critical is False] == ["Indexed, though blocked by robots.txt"]

    def test_real_drilldown_format(self):
        parsed = parse_export("export.zip", make_zip(REAL_DRILLDOWN, bom=False))

        assert (parsed.kind, parsed.issue, parsed.site_url) == ("issue", "Not found (404)", "www.example.com")
        assert len(parsed.urls) == 2

    def test_renamed_overview_has_no_site(self):
        assert parse_export("export.zip", make_zip(REAL_OVERVIEW, bom=False)).site_url is None

    def test_overview_zip(self):
        parsed = parse_export("example.com-Coverage-2026-10-12.zip", make_zip(OVERVIEW))

        assert parsed.kind == "overview"
        assert parsed.site_url == "sc-domain:example.com"
        assert [(r.reason, r.pages, r.source, r.critical) for r in parsed.reasons] == [
            ("Crawled - currently not indexed", 1204, "Google systems", True),
            ("Page with redirect", 310, "Website", True),
            ("Excluded by ‘noindex’ tag", 12, "Website", True),
        ]
        # Latest chart row wins, regardless of row order.
        assert (str(parsed.chart_date), parsed.indexed, parsed.not_indexed) == ("2026-10-12", 8100, 1526)

    def test_non_critical_file_marks_reasons_non_critical(self):
        files = dict(OVERVIEW)
        files["Non-critical issues.csv"] = "Reason,Source,Validation,Pages\nPage with redirect,Website,N/A,4\n"
        parsed = parse_export("x.zip", make_zip(files))
        assert [r.critical for r in parsed.reasons if r.pages == 4] == [False]

    def test_drilldown_zip(self):
        parsed = parse_export("drilldown.zip", make_zip(DRILLDOWN))

        assert parsed.kind == "issue"
        assert parsed.issue == "Crawled - currently not indexed"
        assert [(u.url, str(u.last_crawled) if u.last_crawled else None) for u in parsed.urls] == [
            ("https://example.com/products/a", "2026-09-30"),
            ("https://example.com/products/b", None),
        ]

    def test_single_csv_reasons_table(self):
        parsed = parse_export("Table.csv", OVERVIEW["Critical issues.csv"].encode())
        assert len(parsed.reasons) == 3

    def test_url_list_without_metadata_is_rejected(self):
        with pytest.raises(ExportError, match="which reason"):
            parse_export("Table.csv", DRILLDOWN["Table.csv"].encode())

    @pytest.mark.parametrize(
        "name,data",
        [
            ("photo.png", b"\x89PNG..."),
            ("empty.zip", make_zip({"readme.txt": "hi"})),
            ("other.csv", b"Query,Clicks\nseo,10\n"),
        ],
    )
    def test_rejects_files_that_are_not_page_indexing_exports(self, name, data):
        with pytest.raises(ExportError):
            parse_export(name, data)


class TestUploadEndpoints:
    def upload(self, client, prop, files, name="export.zip"):
        return client.post(
            f"/api/gsc/properties/{prop.id}/indexing/uploads",
            files={"file": (name, make_zip(files), "application/zip")},
        )

    def test_upload_overview_then_read_it_back_sorted_by_advice(self, client, prop):
        resp = self.upload(client, prop, OVERVIEW)
        assert resp.status_code == 201
        assert resp.json() == {"kind": "overview", "filename": "export.zip", "issue": None, "reasons": 3, "urls": 0}

        body = client.get(f"/api/gsc/properties/{prop.id}/indexing/export").json()

        assert (body["indexed"], body["not_indexed"]) == (8100, 1526)
        assert [(r["reason"], r["advice"]["verdict"]) for r in body["reasons"]] == [
            ("Crawled - currently not indexed", "fix"),
            ("Excluded by ‘noindex’ tag", "review"),
            ("Page with redirect", "ignore"),
        ]

    def test_drilldown_urls_attach_to_their_reason(self, client, prop):
        self.upload(client, prop, OVERVIEW)
        assert self.upload(client, prop, DRILLDOWN).json()["kind"] == "issue"

        body = client.get(f"/api/gsc/properties/{prop.id}/indexing/export").json()
        crawled = next(r for r in body["reasons"] if r["reason"].startswith("Crawled"))
        assert crawled["urls_uploaded"] == 2

        pages = client.get(
            f"/api/gsc/properties/{prop.id}/indexing/export/pages",
            params={"reason": "Crawled – currently not indexed"},  # dash style shouldn't matter
        ).json()
        assert pages["total"] == 2
        assert pages["items"][0]["url"] == "https://example.com/products/a"

    def test_newest_overview_upload_wins(self, client, prop):
        self.upload(client, prop, OVERVIEW)
        newer = dict(OVERVIEW)
        newer["Critical issues.csv"] = "Reason,Source,Validation,Pages\nSoft 404,Website,Not Started,9\n"
        self.upload(client, prop, newer)

        body = client.get(f"/api/gsc/properties/{prop.id}/indexing/export").json()
        assert [r["reason"] for r in body["reasons"]] == ["Soft 404"]

    def test_rejects_export_from_a_different_property(self, client, prop):
        files = dict(OVERVIEW)
        files["Metadata.csv"] = "Property,sc-domain:someone-else.com\n"

        resp = self.upload(client, prop, files)

        assert resp.status_code == 422
        assert "someone-else.com" in resp.json()["detail"]

    def test_accepts_real_format_exports(self, client, prop):
        assert self.upload_real(client, prop, REAL_OVERVIEW, REAL_OVERVIEW_NAME).status_code == 201
        assert self.upload_real(client, prop, REAL_DRILLDOWN, "export.zip").status_code == 201

        reasons = client.get(f"/api/gsc/properties/{prop.id}/indexing/export").json()["reasons"]
        by_reason = {r["reason"]: r for r in reasons}
        assert by_reason["Alternative page with proper canonical tag"]["advice"]["verdict"] == "ignore"
        assert by_reason["Not found (404)"]["urls_uploaded"] == 2

    def test_rejects_real_export_from_a_different_site(self, client, prop):
        resp = self.upload_real(client, prop, REAL_OVERVIEW, "someone-else.com-Coverage-2026-10-26.zip")
        assert resp.status_code == 422
        assert "someone-else.com" in resp.json()["detail"]

        drilldown = {**REAL_DRILLDOWN, "Table.csv": "URL,Last crawled\nhttps://someone-else.com/a,2026-10-24\n"}
        assert self.upload_real(client, prop, drilldown, "export.zip").status_code == 422

    def upload_real(self, client, prop, files, name):
        return client.post(
            f"/api/gsc/properties/{prop.id}/indexing/uploads",
            files={"file": (name, make_zip(files, bom=False), "application/zip")},
        )

    def test_rejects_unreadable_upload(self, client, prop):
        resp = client.post(
            f"/api/gsc/properties/{prop.id}/indexing/uploads",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 422

    def test_export_is_null_before_any_upload(self, client, prop):
        assert client.get(f"/api/gsc/properties/{prop.id}/indexing/export").json() is None

    def test_inspection_reasons_include_advice_and_sitemap_counts(self, client, db, prop):
        from datetime import UTC, datetime

        from app.models import GscUrlInspection

        now = datetime.now(UTC)
        db.add_all(
            [
                GscUrlInspection(property_id=prop.id, url="https://example.com/r1", in_sitemap=True, coverage_state="Page with redirect", inspected_at=now),
                GscUrlInspection(property_id=prop.id, url="https://example.com/r2", in_sitemap=False, coverage_state="Page with redirect", inspected_at=now),
                GscUrlInspection(property_id=prop.id, url="https://example.com/s", in_sitemap=True, coverage_state="Soft 404", inspected_at=now),
            ]
        )
        db.commit()

        reasons = client.get(f"/api/gsc/properties/{prop.id}/indexing").json()["reasons"]

        assert [(r["reason"], r["advice"]["verdict"], r["in_sitemap"]) for r in reasons] == [
            ("Soft 404", "fix", 1),
            ("Page with redirect", "ignore", 1),
        ]
        assert reasons[1]["advice"]["sitemap_cleanup"] is True
