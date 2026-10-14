"""Thin wrappers over Google's OAuth 2.0 and Search Console REST APIs."""

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

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/webmasters.readonly",
]

# GSC returns at most 25k rows per request; page through with startRow.
ROW_LIMIT = 25_000


class GoogleAPIError(Exception):
    pass


def _raise_for_status(resp: httpx.Response) -> None:
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
