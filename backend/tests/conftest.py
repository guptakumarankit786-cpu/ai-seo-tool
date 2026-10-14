import os

# Point the app at the throwaway test database *before* anything imports app.config.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://seo:seo@db:5432/seo_tool_test"
)
os.environ["TOKEN_ENCRYPTION_KEY"] = __import__("cryptography.fernet").fernet.Fernet.generate_key().decode()
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402,F401
from app.crypto import encrypt  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.gsc import google_api  # noqa: E402
from app.main import app  # noqa: E402
from app.models import GoogleConnection, GscProperty  # noqa: E402

assert "seo_tool_test" in str(engine.url), "refusing to run tests against a non-test database"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    return TestClient(app)


class FakeGoogle:
    """In-memory stand-in for the Google OAuth + Search Console APIs."""

    def __init__(self):
        self.sites = [
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://blog.example.com/", "permissionLevel": "siteFullUser"},
        ]
        self.token_response = {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "scope": " ".join(google_api.SCOPES),
        }
        self.email = "owner@example.com"
        self.revoked: list[str] = []
        self.fail_on: str | None = None  # dimension name that should raise
        self.calls: list[tuple] = []

    def search_analytics(self, token, site_url, start, end, dimensions):
        self.calls.append((site_url, start, end, tuple(dimensions)))
        if self.fail_on and self.fail_on in dimensions:
            raise google_api.GoogleAPIError("403 from www.googleapis.com: forbidden")
        rows = []
        day, i = start, 0
        while day <= end:
            i += 1
            if dimensions == ["date"]:
                rows.append(_row([day.isoformat()], clicks=10 + i, impressions=100 + i, position=5.0))
            else:
                for k in range(3):
                    key = f"query {k}" if dimensions[1] == "query" else f"https://example.com/p{k}"
                    rows.append(_row([day.isoformat(), key], clicks=k + 1, impressions=10 * (k + 1), position=k + 1.0))
            day += timedelta(days=1)
        return rows


def _row(keys, clicks, impressions, position):
    return {
        "keys": keys,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions,
        "position": position,
    }


@pytest.fixture
def fake_google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google_api, "access_token_for", lambda db, conn: "access-token")
    monkeypatch.setattr(google_api, "list_sites", lambda token: list(fake.sites))
    monkeypatch.setattr(google_api, "search_analytics", fake.search_analytics)
    monkeypatch.setattr(google_api, "exchange_code", lambda code: dict(fake.token_response))
    monkeypatch.setattr(google_api, "fetch_email", lambda token: fake.email)
    monkeypatch.setattr(google_api, "revoke", lambda token: fake.revoked.append(token))
    return fake


@pytest.fixture
def connection(db):
    conn = GoogleConnection(
        email="owner@example.com", scopes="webmasters.readonly", refresh_token_enc=encrypt("refresh-0")
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


@pytest.fixture
def prop(db, connection):
    p = GscProperty(connection_id=connection.id, site_url="sc-domain:example.com", permission_level="siteOwner")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)
