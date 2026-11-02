from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.gsc import google_api
from app.models import GoogleConnection, GscProperty, OAuthState


def query_of(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def start_flow(client) -> str:
    resp = client.get("/api/gsc/oauth/start", follow_redirects=False)
    return query_of(resp.headers["location"])["state"]


def callback(client, **params):
    resp = client.get("/api/gsc/oauth/callback", params=params, follow_redirects=False)
    assert resp.status_code == 307
    return query_of(resp.headers["location"])


class TestStart:
    def test_redirects_to_google_with_offline_readonly_request(self, client, db):
        resp = client.get("/api/gsc/oauth/start", follow_redirects=False)

        assert resp.status_code == 307
        location = resp.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        params = query_of(location)
        assert params["access_type"] == "offline"
        assert params["prompt"] == "consent"
        assert "https://www.googleapis.com/auth/webmasters.readonly" in params["scope"].split()
        assert "https://www.googleapis.com/auth/analytics.readonly" in params["scope"].split()
        assert params["redirect_uri"] == "http://localhost:8000/api/gsc/oauth/callback"
        assert db.get(OAuthState, params["state"]) is not None

    def test_refuses_when_google_client_is_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "google_client_secret", "")
        assert client.get("/api/gsc/oauth/start", follow_redirects=False).status_code == 400


class TestCallback:
    def test_success_stores_encrypted_tokens_and_discovers_properties(self, client, db, fake_google):
        result = callback(client, state=start_flow(client), code="auth-code")

        assert result == {"gsc": "connected", "email": "owner@example.com", "properties": "2"}
        conn = db.scalars(select(GoogleConnection)).one()
        assert conn.refresh_token_enc != "refresh-1"  # never stored in plain text
        assert decrypt(conn.refresh_token_enc) == "refresh-1"
        assert decrypt(conn.access_token_enc) == "access-1"
        assert db.scalar(select(func.count()).select_from(GscProperty)) == 2

    def test_state_is_single_use(self, client, fake_google):
        state = start_flow(client)
        callback(client, state=state, code="auth-code")
        assert callback(client, state=state, code="auth-code")["gsc"] == "error"

    def test_rejects_unknown_state(self, client, db, fake_google):
        assert callback(client, state="forged", code="auth-code")["gsc"] == "error"
        assert db.scalar(select(func.count()).select_from(GoogleConnection)) == 0

    def test_rejects_expired_state(self, client, db, fake_google):
        db.add(OAuthState(state="old", created_at=datetime.now(UTC) - timedelta(minutes=11)))
        db.commit()
        assert callback(client, state="old", code="auth-code")["gsc"] == "error"

    def test_user_denying_consent_is_reported(self, client, db, fake_google):
        result = callback(client, state=start_flow(client), error="access_denied")
        assert result == {"gsc": "error", "reason": "access_denied"}
        assert db.scalar(select(func.count()).select_from(GoogleConnection)) == 0

    def test_rejects_grant_without_search_console_scope(self, client, db, fake_google):
        fake_google.token_response["scope"] = "openid https://www.googleapis.com/auth/userinfo.email"

        result = callback(client, state=start_flow(client), code="auth-code")

        assert result["gsc"] == "error"
        assert db.scalar(select(func.count()).select_from(GoogleConnection)) == 0

    def test_reconnect_without_new_refresh_token_keeps_the_old_one(self, client, db, connection, fake_google):
        del fake_google.token_response["refresh_token"]

        result = callback(client, state=start_flow(client), code="auth-code")

        assert result["gsc"] == "connected"
        db.refresh(connection)
        assert decrypt(connection.refresh_token_enc) == "refresh-0"
        assert db.scalar(select(func.count()).select_from(GoogleConnection)) == 1


class TestDisconnect:
    def test_revokes_token_and_deletes_connection_with_its_properties(self, client, db, prop, fake_google):
        resp = client.delete(f"/api/gsc/connections/{prop.connection_id}")

        assert resp.status_code == 204
        assert fake_google.revoked == ["refresh-0"]
        assert db.scalar(select(func.count()).select_from(GoogleConnection)) == 0
        assert db.scalar(select(func.count()).select_from(GscProperty)) == 0

    def test_unknown_connection_returns_404(self, client):
        assert client.delete("/api/gsc/connections/999").status_code == 404


class TestStatus:
    def test_lists_connections_with_properties(self, client, prop):
        body = client.get("/api/gsc/status").json()
        assert body["configured"] is True
        assert body["connections"][0]["email"] == "owner@example.com"
        assert body["connections"][0]["properties"][0]["site_url"] == "sc-domain:example.com"
        assert body["connections"][0]["analytics"] is False  # connected before GA4: needs to reconnect

    def test_analytics_flag_follows_granted_scopes(self, client, db, prop):
        prop.connection.scopes = "webmasters.readonly https://www.googleapis.com/auth/analytics.readonly"
        db.commit()
        assert client.get("/api/gsc/status").json()["connections"][0]["analytics"] is True


def test_encrypt_round_trips_and_hides_plaintext():
    token = encrypt("secret-value")
    assert token != "secret-value"
    assert decrypt(token) == "secret-value"


class TestAccessToken:
    """Long downloads must not outlive their token (a sync failed with 401 mid-month)."""

    @pytest.fixture
    def refreshes(self, monkeypatch):
        calls = []

        class Resp:
            is_error, status_code = False, 200

            def json(self):
                return {"access_token": f"new-{len(calls)}", "expires_in": 3600}

        monkeypatch.setattr(google_api.httpx, "post", lambda *a, **k: calls.append(1) or Resp())
        return calls

    def _expiring_in(self, db, connection, minutes):
        connection.access_token_enc = encrypt("old")
        connection.access_token_expires_at = datetime.now(UTC) + timedelta(minutes=minutes)
        db.commit()

    def test_token_with_plenty_of_time_is_reused(self, db, connection, refreshes):
        self._expiring_in(db, connection, 30)
        assert google_api.access_token_for(db, connection) == "old" and not refreshes

    def test_token_expiring_within_the_margin_is_renewed(self, db, connection, refreshes):
        self._expiring_in(db, connection, 5)  # a multi-minute download would outlive it
        assert google_api.access_token_for(db, connection) == "new-1"
        assert connection.access_token_expires_at > datetime.now(UTC) + timedelta(minutes=55)
