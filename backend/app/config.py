"""Application settings, read from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden by an env var of the same name."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite:///./storage/dev.db"
    storage_dir: str = "./storage"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    public_base_url: str = "http://localhost:8000"
    max_upload_mb: int = 25
    api_prefix: str = "/api/v1"

    # AI layer (Phase 3)
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    # None = auto (on when ANTHROPIC_API_KEY is set). Set true to use another credential
    # source the SDK understands (e.g. ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile).
    llm_enabled: bool | None = None
    llm_timeout_seconds: float = 60.0
    # Ask AI uses the agent team (retrieval, SQL and CSV agents); false = fixed query plans.
    agentic_chat: bool = True
    agent_deadline_seconds: float = 85.0


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
