"""Application configuration loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "agent"
    postgres_password: str = "agent"
    postgres_db: str = "ai_operations_agent"

    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")  # type: ignore[assignment]

    # ── LLM ──────────────────────────────────────────────────────────────────
    #: The agent runs its deterministic path when this is off or unauthenticated,
    #: so an absent key degrades the system rather than breaking it.
    llm_enabled: bool = True
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 4096
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    anthropic_api_key: SecretStr | None = None

    # ── Agent guardrails ─────────────────────────────────────────────────────
    max_tool_calls: int = 12
    max_workflow_steps: int = 30
    tool_timeout_seconds: float = 15.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
