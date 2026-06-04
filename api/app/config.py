"""Application settings.

Reads from environment (and a local .env if present). The SQLite default is the
honest local-dev fallback documented in docs/stack.md — Postgres is the real target
and is what docker-compose wires up.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite fallback for bare-metal local dev; compose overrides with Postgres.
    database_url: str = "sqlite:///./kiln_dev.db"
    service_name: str = "kiln-api"
    version: str = "0.0.0"
    # Comma-separated origins allowed for direct (non-proxied) browser calls in dev.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()
