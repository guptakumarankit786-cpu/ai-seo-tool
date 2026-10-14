from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://seo:seo@db:5432/seo_tool"

    # Public URLs (as seen from the user's browser)
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # Google OAuth client (Web application) from Google Cloud Console
    google_client_id: str = ""
    google_client_secret: str = ""

    # Fernet key used to encrypt OAuth tokens at rest
    token_encryption_key: str = ""

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.backend_url}/api/gsc/oauth/callback"

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
