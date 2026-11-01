"""Thin wrappers over Google's OAuth 2.0 and Search Console REST APIs."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.models import GoogleConnection

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GSC_BASE = "https://www.googleapis.com/webmasters/v3"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
GA4_ADMIN = "https://analyticsadmin.googleapis.com/v1beta"
GA4_DATA = "https://analyticsdata.googleapis.com/v1beta"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",  # GA4; optional — Search Console works without it
]
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

# GSC returns at most 25k rows per request; page through with startRow.
ROW_LIMIT = 25_000


class GoogleAPIError(Exception):
    pass


class QuotaExceeded(GoogleAPIError):
    """Google returned 429: the daily/minute URL Inspection quota is used up."""


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        raise QuotaExceeded(f"429 from {resp.request.url.host}: quota exceeded")
    if resp.is_error:
        raise GoogleAPIError(f"{resp.status_code} from {resp.request.url.host}: {resp.text[:500]}")


def build_auth_url(state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # we need a refresh token
        "prompt": "consent",  # always return a refresh token, even on reconnect
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    settings = get_settings()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    _raise_for_status(resp)
    return resp.json()


def fetch_email(access_token: str) -> str:
    resp = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    _raise_for_status(resp)
    return resp.json()["email"]


def revoke(token: str) -> None:
    # Best effort: the connection is removed locally regardless.
    httpx.post(REVOKE_URL, params={"token": token}, timeout=30)


def access_token_for(db: Session, conn: GoogleConnection) -> str:
    """Return a valid access token, refreshing (and persisting) it when near expiry."""
    now = datetime.now(UTC)
    if (
        conn.access_token_enc
        and conn.access_token_expires_at
        and conn.access_token_expires_at - timedelta(minutes=2) > now
    ):
        return decrypt(conn.access_token_enc)

    settings = get_settings()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": decrypt(conn.refresh_token_enc),
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    _raise_for_status(resp)
    payload = resp.json()
    conn.access_token_enc = encrypt(payload["access_token"])
    conn.access_token_expires_at = now + timedelta(seconds=payload.get("expires_in", 3600))
    db.commit()
    return payload["access_token"]


def list_sites(access_token: str) -> list[dict]:
    resp = httpx.get(
        f"{GSC_BASE}/sites", headers={"Authorization": f"Bearer {access_token}"}, timeout=30
    )
    _raise_for_status(resp)
    return resp.json().get("siteEntry", [])


def search_analytics(
    access_token: str, site_url: str, start: date, end: date, dimensions: list[str]
) -> list[dict]:
    """Fetch every row for the given dimensions, paging until exhausted."""
    url = f"{GSC_BASE}/sites/{quote(site_url, safe='')}/searchAnalytics/query"
    rows: list[dict] = []
    start_row = 0
    with httpx.Client(headers={"Authorization": f"Bearer {access_token}"}, timeout=120) as client:
        while True:
            resp = client.post(
                url,
                json={
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "dimensions": dimensions,
                    "type": "web",
                    "rowLimit": ROW_LIMIT,
                    "startRow": start_row,
                },
            )
            _raise_for_status(resp)
            batch = resp.json().get("rows", [])
            rows.extend(batch)
            if len(batch) < ROW_LIMIT:
                return rows
            start_row += ROW_LIMIT


def list_sitemaps(access_token: str, site_url: str) -> list[dict]:
    resp = httpx.get(
        f"{GSC_BASE}/sites/{quote(site_url, safe='')}/sitemaps",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=60,
    )
    _raise_for_status(resp)
    return resp.json().get("sitemap", [])


def inspect_url(access_token: str, site_url: str, url: str) -> dict:
    """Return the indexStatusResult for one URL (coverageState, verdict, canonicals, ...)."""
    resp = httpx.post(
        INSPECT_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"inspectionUrl": url, "siteUrl": site_url},
        timeout=120,
    )
    _raise_for_status(resp)
    return resp.json().get("inspectionResult", {}).get("indexStatusResult", {})


def list_ga4_properties(access_token: str) -> list[dict]:
    """Every GA4 property the account can read: {property, name, account, website_url}."""
    headers = {"Authorization": f"Bearer {access_token}"}
    props: list[dict] = []
    params = {"pageSize": 200}
    with httpx.Client(headers=headers, timeout=60) as client:
        while True:
            resp = client.get(f"{GA4_ADMIN}/accountSummaries", params=params)
            _raise_for_status(resp)
            body = resp.json()
            for account in body.get("accountSummaries", []):
                for p in account.get("propertySummaries", []):
                    props.append({"property": p["property"], "name": p.get("displayName", ""), "account": account.get("displayName", "")})
            if not body.get("nextPageToken"):
                break
            params["pageToken"] = body["nextPageToken"]

        def website(prop: dict) -> str | None:
            resp = client.get(f"{GA4_ADMIN}/{prop['property']}/dataStreams")
            _raise_for_status(resp)
            urls = [
                s["webStreamData"].get("defaultUri")
                for s in resp.json().get("dataStreams", [])
                if s.get("type") == "WEB_DATA_STREAM" and s.get("webStreamData", {}).get("defaultUri")
            ]
            return urls[0] if urls else None

        # One stream call per property; dozens of properties take ~20 s one by one.
        with ThreadPoolExecutor(max_workers=8) as pool:
            for prop, url in zip(props, pool.map(website, props)):
                prop["website_url"] = url
    return props


def ga4_sessions(access_token: str, property_name: str, days: int = 28) -> int:
    """All-channel sessions over the last `days` days (used to tell a live property from an old one)."""
    resp = httpx.post(
        f"{GA4_DATA}/{property_name}:runReport",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "yesterday"}], "metrics": [{"name": "sessions"}]},
        timeout=60,
    )
    _raise_for_status(resp)
    rows = resp.json().get("rows", [])
    return int(rows[0]["metricValues"][0]["value"]) if rows else 0


def ga4_run_report(access_token: str, property_name: str, body: dict) -> dict:
    """GA4 runReport: {"rows": [...], "totals": [...] | None, "range_totals": {name: [...]}, "currency": "INR"}.
    Pages through every row unless the body sets its own `limit`. Totals come back only when the body
    asks for metricAggregations=["TOTAL"]; with 2+ date ranges there's one per range, keyed by its name."""
    rows: list[dict] = []
    range_totals: dict[str, list[float]] = {}
    several = len(body.get("dateRanges", [])) > 1
    offset, limit = 0, body.get("limit", 100_000)
    with httpx.Client(headers={"Authorization": f"Bearer {access_token}"}, timeout=120) as client:
        while True:
            resp = client.post(f"{GA4_DATA}/{property_name}:runReport", json={**body, "limit": limit, "offset": offset})
            _raise_for_status(resp)
            data = resp.json()
            rows.extend(data.get("rows", []))
            for t in data.get("totals", []) if not range_totals else []:
                if t.get("metricValues"):
                    name = t["dimensionValues"][-1]["value"] if several else "now"
                    range_totals[name] = [float(m["value"]) for m in t["metricValues"]]
            offset += limit
            if "limit" in body or offset >= data.get("rowCount", 0):
                return {
                    "rows": rows,
                    "totals": next(iter(range_totals.values()), None),
                    "range_totals": range_totals,
                    "currency": data.get("metadata", {}).get("currencyCode"),
                }
