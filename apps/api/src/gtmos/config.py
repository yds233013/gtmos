"""Runtime configuration. Every secret comes from the environment; nothing is hardcoded."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `.env` is read for developer convenience, but never under test: a suite whose behaviour depends on
    # whether a developer happens to have WEBHOOK_SECRET in their local file is not a suite you can
    # trust. Tests set every variable they depend on explicitly.
    model_config = SettingsConfigDict(
        env_file=None if os.environ.get("ENV") == "test" else ("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://gtmos:gtmos@localhost:56432/gtmos"
    redis_url: str | None = None
    # "inline" runs workflow jobs in-process (tests, simple local dev); "redis" enqueues to the RQ worker.
    queue_backend: Literal["inline", "redis"] = "inline"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3010", "http://127.0.0.1:3010"])
    log_level: str = "INFO"
    # Size of the deterministic demo universe (accounts). Simulated providers answer from the same universe.
    seed_accounts: int = 2000

    # Security boundary. Admin token gates live-integration and destructive endpoints.
    admin_api_token: SecretStr | None = None
    webhook_secret: SecretStr | None = None

    # LLM provider (optional). Without a key GTMOS uses deterministic demo generators.
    anthropic_api_key: SecretStr | None = None
    # Live generation is opt-in: a key present in the environment alone never triggers billed API calls.
    llm_enabled: bool = False
    llm_model: str = "claude-opus-5"

    # HubSpot (optional). Without a token the demo adapter is used and every sync is labeled SIMULATED.
    #: Refuse every write at the edge. For a publicly reachable demo instance; off everywhere else.
    #: Of this API's 36 mutating routes, four are admin-gated, two carry a gate that is a no-op
    #: unless live writes are on, and the remaining 30 have no gate at all — fine on a laptop and
    #: not fine on the internet. Enforced in `main.enforce_read_only`.
    read_only: bool = False

    hubspot_access_token: SecretStr | None = None
    hubspot_webhook_client_secret: SecretStr | None = None
    hubspot_live_writes_enabled: bool = False

    # Optional real enrichment adapter.
    apollo_api_key: SecretStr | None = None

    # Clay (optional). The webhook secret is Clay's `signingSecret`, shown once when the webhook is
    # registered; the API key is the workspace key from Settings → Account → API keys (beta). Without
    # the API key the outbound client is inert and GTMOS only receives.
    clay_webhook_secret: SecretStr | None = None
    clay_api_key: SecretStr | None = None

    # Outbound sending is never performed by GTMOS V1; this flag only documents the boundary.
    outbound_send_enabled: bool = False

    @property
    def llm_mode(self) -> Literal["live", "demo"]:
        return "live" if self.anthropic_api_key and self.llm_enabled else "demo"

    @property
    def hubspot_mode(self) -> Literal["live", "demo"]:
        return "live" if self.hubspot_access_token and self.hubspot_live_writes_enabled else "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
