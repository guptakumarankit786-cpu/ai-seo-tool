"""Parse Search Console "Page indexing" exports (Export → Download CSV).

Search Console produces a ZIP of CSVs. File names have changed over time, so files are
recognised by their header row instead:

  Reasons table   Reason, Source, Validation, [Trend], Pages   ("Critical issues.csv", "Non-critical issues.csv", "Table.csv")
  Chart           Date, Not indexed, Indexed, [Impressions]     ("Chart.csv")
  URL list        URL, Last crawled                             ("Table.csv" of a single-issue drill-down)
  Metadata        key, value rows (Property, Issue, ...)        ("Metadata.csv")

A single CSV upload is also accepted.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNZIPPED_BYTES = 100 * 1024 * 1024
MAX_FILES = 20

_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d")


class ExportError(ValueError):
    """The upload isn't a readable Search Console Page indexing export."""


@dataclass
class ParsedReason:
    reason: str
    source: str | None
    validation: str | None
    pages: int
    critical: bool | None


@dataclass
class ParsedUrl:
    url: str
    last_crawled: date | None


@dataclass
class ParsedExport:
    reasons: list[ParsedReason] = field(default_factory=list)
    urls: list[ParsedUrl] = field(default_factory=list)
    chart_date: date | None = None
    indexed: int | None = None
    not_indexed: int | None = None
    site_url: str | None = None
    issue: str | None = None

    @property
    def kind(self) -> str:
        return "issue" if self.urls and not self.reasons else "overview"


def _int(value: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else None


def _date(value: str | None) -> date | None:
    value = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _rows(text: str) -> tuple[list[str], list[dict[str, str]], list[list[str]]]:
    """Return (lower-cased header keys, rows as dicts, raw rows including the header)."""
    raw = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]
    if not raw:
        return [], [], []
    keys = [h.lower() for h in raw[0]]
    rows = [{k: (row[i] if i < len(row) else "") for i, k in enumerate(keys)} for row in raw[1:]]
    return keys, rows, raw


def _apply_csv(result: ParsedExport, name: str, text: str) -> None:
    keys, rows, raw = _rows(text)
    lower_name = name.lower()

    if "reason" in keys and "pages" in keys:
        critical = False if "non-critical" in lower_name else True if "critical" in lower_name else None
        for r in rows:
            pages = _int(r.get("pages"))
            if r.get("reason") and pages is not None:
                result.reasons.append(
                    ParsedReason(r["reason"], r.get("source") or None, r.get("validation") or None, pages, critical)
                )
    elif "url" in keys:
        for r in rows:
            if r.get("url", "").startswith(("http://", "https://")):
                result.urls.append(ParsedUrl(r["url"], _date(r.get("last crawled"))))
    elif "date" in keys and ("indexed" in keys or "not indexed" in keys):
        dated = [(d, r) for r in rows if (d := _date(r.get("date")))]
        if dated:
            result.chart_date, latest = max(dated, key=lambda x: x[0])
            result.indexed = _int(latest.get("indexed"))
            result.not_indexed = _int(latest.get("not indexed"))
    elif "metadata" in lower_name or len(keys) == 2:
        # Key/value rows; the first row may be a header ("Property,Value") or already data.
        for row in raw:
            if len(row) < 2:
                continue
            key, value = row[0].lower(), row[1]
            if key == "property":
                result.site_url = value
            elif key in ("issue", "reason"):
                result.issue = value


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExportError("Couldn't read the file's text encoding.")


def parse_export(filename: str, data: bytes) -> ParsedExport:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExportError("File is larger than 20 MB.")

    result = ParsedExport()
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = [m for m in zf.infolist() if m.filename.lower().endswith(".csv") and not m.is_dir()]
            if not members:
                raise ExportError("The ZIP doesn't contain any CSV files.")
            if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_UNZIPPED_BYTES:
                raise ExportError("The ZIP is too large to be a Search Console export.")
            for m in members:
                _apply_csv(result, m.filename, _decode(zf.read(m)))
    elif filename.lower().endswith(".csv"):
        _apply_csv(result, filename, _decode(data))
    else:
        raise ExportError("Upload the ZIP (or a CSV) from Search Console → Indexing → Pages → Export → Download CSV.")

    if not result.reasons and not result.urls:
        raise ExportError(
            "This doesn't look like a Page indexing export — no reasons table or URL list was found."
        )
    if result.kind == "issue" and not result.issue:
        raise ExportError(
            "This URL list doesn't say which reason it belongs to. Upload the full ZIP from the reason's page "
            "(it includes Metadata.csv)."
        )
    return result
