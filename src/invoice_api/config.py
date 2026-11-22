"""Settings, read from environment variables (or a local `.env` file)."""

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-secret-change-me-dev-only-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLAlchemy URL. Plain `postgres://` and `postgresql://` URLs, as hosting
    # providers hand them out, are accepted and switched to the psycopg driver.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/invoice_api"

    # "production" makes the checks below strict.
    environment: str = "development"

    # Signs the session tokens. Must be set to a long random value in production.
    secret_key: str = DEV_SECRET
    session_hours: int = 12

    # Origins allowed to call the API from a browser.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "https://knightly95.github.io",
    ]

    @field_validator("database_url")
    @classmethod
    def use_psycopg(cls, url: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @model_validator(mode="after")
    def production_needs_a_real_secret(self) -> "Settings":
        # With the public default key, anyone could sign their own tokens.
        if self.environment == "production" and (
            self.secret_key == DEV_SECRET or len(self.secret_key) < 32
        ):
            raise ValueError("Set SECRET_KEY to a random value of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
