"""Runtime configuration. Every secret comes from the environment; nothing is hardcoded."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://gtmos:gtmos@localhost:5433/gtmos"
    redis_url: str | None = None
    # "inline" runs workflow jobs in-process (tests, simple local dev); "redis" enqueues to the RQ worker.
    queue_backend: Literal["inline", "redis"] = "inline"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"

    # Security boundary. Admin token gates live-integration and destructive endpoints.
    admin_api_token: SecretStr | None = None
    webhook_secret: SecretStr | None = None

    # LLM provider (optional). Without a key GTMOS uses deterministic demo generators.
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5"

    # HubSpot (optional). Without a token the demo adapter is used and every sync is labeled SIMULATED.
    hubspot_access_token: SecretStr | None = None
    hubspot_webhook_client_secret: SecretStr | None = None
    hubspot_live_writes_enabled: bool = False

    # Optional real enrichment adapter.
    apollo_api_key: SecretStr | None = None

    # Outbound sending is never performed by GTMOS V1; this flag only documents the boundary.
    outbound_send_enabled: bool = False

    @property
    def llm_mode(self) -> Literal["live", "demo"]:
        return "live" if self.anthropic_api_key else "demo"

    @property
    def hubspot_mode(self) -> Literal["live", "demo"]:
        return "live" if self.hubspot_access_token else "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
