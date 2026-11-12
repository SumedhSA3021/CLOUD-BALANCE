"""12-Factor Environment Configuration for CloudBalance Controller."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(
        default="CloudBalance Controller",
        validation_alias=AliasChoices("CB_APP_NAME", "APP_NAME"),
    )
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("CB_ENV", "ENVIRONMENT"),
    )
    api_key: str = Field(
        default="cb-dev-api-key-2026",
        validation_alias=AliasChoices("CB_API_KEY", "API_KEY"),
    )
    require_api_key: bool = Field(
        default=False,
        validation_alias=AliasChoices("CB_REQUIRE_API_KEY", "REQUIRE_API_KEY"),
    )
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["*"],
        validation_alias=AliasChoices("CB_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"),
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("CB_REDIS_URL", "REDIS_URL"),
    )
    mongo_url: str = Field(
        default="mongodb://localhost:27017",
        validation_alias=AliasChoices("CB_MONGO_URL", "MONGO_URL"),
    )
    mongo_db_name: str = Field(
        default="cloudbalance",
        validation_alias=AliasChoices("CB_MONGO_DB_NAME", "MONGO_DB_NAME"),
    )
    local_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("CB_LOCAL_MODE", "LOCAL_MODE"),
    )

    worker_ttl_seconds: int = Field(
        default=10,
        ge=2,
        le=120,
        validation_alias=AliasChoices("CB_WORKER_TTL_SECONDS", "WORKER_TTL_SECONDS"),
    )
    max_queue_depth: int = Field(
        default=500,
        ge=1,
        validation_alias=AliasChoices("CB_MAX_QUEUE_DEPTH", "MAX_QUEUE_DEPTH"),
    )
    rate_limit_per_sec: int = Field(
        default=300,
        ge=1,
        validation_alias=AliasChoices("CB_RATE_LIMIT_PER_SEC", "RATE_LIMIT_PER_SEC"),
    )
    batch_window_ms: int = Field(
        default=200,
        ge=10,
        le=5000,
        validation_alias=AliasChoices("CB_BATCH_WINDOW_MS", "BATCH_WINDOW_MS"),
    )
    batch_max_size: int = Field(
        default=20,
        ge=1,
        le=200,
        validation_alias=AliasChoices("CB_BATCH_MAX_SIZE", "BATCH_MAX_SIZE"),
    )
    solver_time_limit_ms: int = Field(
        default=50,
        ge=5,
        le=2000,
        validation_alias=AliasChoices("CB_SOLVER_TIME_LIMIT_MS", "SOLVER_TIME_LIMIT_MS"),
    )
    cpu_cap_pct: float = Field(
        default=85.0,
        gt=0.0,
        le=100.0,
        validation_alias=AliasChoices("CB_CPU_CAP_PCT", "CPU_CAP_PCT"),
    )
    mem_cap_pct: float = Field(
        default=90.0,
        gt=0.0,
        le=100.0,
        validation_alias=AliasChoices("CB_MEM_CAP_PCT", "MEM_CAP_PCT"),
    )
    dispatch_timeout_sec: float = Field(
        default=12.0,
        gt=0.5,
        validation_alias=AliasChoices("CB_DISPATCH_TIMEOUT_SEC", "DISPATCH_TIMEOUT_SEC"),
    )
    dispatch_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias=AliasChoices("CB_DISPATCH_MAX_RETRIES", "DISPATCH_MAX_RETRIES"),
    )
    ws_broadcast_interval_sec: float = Field(
        default=1.5,
        gt=0.1,
        validation_alias=AliasChoices(
            "CB_WS_BROADCAST_INTERVAL_SEC", "WS_BROADCAST_INTERVAL_SEC"
        ),
    )
    default_scheduler: str = Field(
        default="ortools_milp",
        validation_alias=AliasChoices("CB_DEFAULT_SCHEDULER", "DEFAULT_SCHEDULER"),
    )
    seed_demo_workers: bool = Field(
        default=True,
        validation_alias=AliasChoices("CB_SEED_DEMO_WORKERS", "SEED_DEMO_WORKERS"),
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: str | list[str]) -> list[str]:
        """Parse comma-separated string or list of origins."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return list(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()

