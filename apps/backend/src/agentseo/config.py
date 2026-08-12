from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./agentseo.db"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    demo_mode: bool = True
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    max_upload_bytes: int = 2_097_152
    max_tasks_per_run: int = 100
    max_parallelism: int = 4
    max_tool_calls: int = 12
    max_iterations: int = 16
    run_timeout_seconds: int = 120

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
