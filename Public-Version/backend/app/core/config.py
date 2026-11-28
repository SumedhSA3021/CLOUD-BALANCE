"""12-Factor Environment Configuration for CloudBalance Controller."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
ROOT_ENV_FILE = ROOT_DIR / ".env"

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_CONTROLLER_HOST = "0.0.0.0"
DEFAULT_CONTROLLER_PORT = 8000
DEFAULT_CONTROLLER_URL = f"http://{DEFAULT_LOCAL_HOST}:{DEFAULT_CONTROLLER_PORT}"
DEFAULT_WORKER_HOST = DEFAULT_LOCAL_HOST
DEFAULT_WORKER_PORT = 8001
DEFAULT_WORKER_ID = "worker-1"
DEFAULT_WORKER_URLS = [
    f"http://{DEFAULT_LOCAL_HOST}:8001",
    f"http://{DEFAULT_LOCAL_HOST}:8002",
    f"http://{DEFAULT_LOCAL_HOST}:8003",
]
DEFAULT_BENCHMARK_WORKER_IP = "10.128.0.10"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_MONGO_URL = "mongodb://localhost:27017"
DEFAULT_MONGO_DB_NAME = "cloudbalance"
DEFAULT_DATA_DIR = "data"
DEFAULT_FRONTEND_DIST_DIR = "frontend/dist"
DEFAULT_TEST_LOG_FILENAME = "test_log.csv"
DEFAULT_TEST_SUMMARY_FILENAME = "test_summary.csv"
DEFAULT_DISPATCH_TIMEOUT_SEC = 15.0
DEFAULT_HEAVY_TASK_ITERATIONS = 180000
DEFAULT_MAX_PAYLOAD_BYTES = 64 * 1024
DEFAULT_WORKER_TOTAL_MEM_MB = 4096.0
DEFAULT_WORKER_BASE_CPU_PCT = 8.0
DEFAULT_WORKER_BASE_MEM_MB = 420.0
DEFAULT_WORKER_TIME_SCALE = 0.15
DEFAULT_WORKER_MAX_PHYSICAL_DIM = 350
DEFAULT_WORKER_CONCURRENCY_LIMIT = 2
DEFAULT_WORKER_QUEUE_CAPACITY = 4
DEFAULT_WORKER_TASK_TIMEOUT_SEC = 10.0
DEFAULT_TELEMETRY_INTERVAL_SEC = 1.5
DEFAULT_AGENT_INTERVAL_SEC = 2.0


@dataclass(frozen=True)
class WorkerEndpoint:
    """Parsed worker endpoint derived from WORKER_URLS."""

    worker_id: str
    url: str
    scheme: str
    host: str
    port: int


def parse_worker_endpoints(worker_urls: Sequence[str] | str | None) -> list[WorkerEndpoint]:
    """Parse WORKER_URLS (list or CSV string) into ordered WorkerEndpoint entries."""
    if worker_urls is None:
        raw_items = list(DEFAULT_WORKER_URLS)
    elif isinstance(worker_urls, str):
        raw_items = [item.strip() for item in worker_urls.split(",") if item.strip()]
    else:
        raw_items = [str(item).strip() for item in worker_urls if str(item).strip()]

    endpoints: list[WorkerEndpoint] = []
    for idx, raw in enumerate(raw_items, start=1):
        if "=" in raw and "://" in raw.split("=", 1)[1]:
            wid_part, url_part = raw.split("=", 1)
            worker_id = wid_part.strip() or f"worker-{idx}"
            raw_url = url_part.strip()
        else:
            worker_id = f"worker-{idx}"
            raw_url = raw
        if "://" not in raw_url:
            raw_url = f"http://{raw_url}"
        parsed = urlparse(raw_url.rstrip("/"))
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname or DEFAULT_LOCAL_HOST
        port = parsed.port or (443 if scheme == "https" else 80)
        clean_url = f"{scheme}://{parsed.netloc}".rstrip("/")
        endpoints.append(
            WorkerEndpoint(
                worker_id=worker_id,
                url=clean_url,
                scheme=scheme,
                host=host,
                port=port,
            )
        )
    return endpoints


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV_FILE), ".env"),
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
    admin_token: str = Field(
        ...,
        validation_alias=AliasChoices("ADMIN_TOKEN", "CB_ADMIN_TOKEN"),
    )
    worker_secret: str = Field(
        ...,
        validation_alias=AliasChoices("WORKER_SECRET", "CB_WORKER_SECRET"),
    )
    worker_urls: Annotated[list[str], NoDecode] = Field(
        default=list(DEFAULT_WORKER_URLS),
        validation_alias=AliasChoices("WORKER_URLS", "CB_WORKER_URLS"),
    )
    controller_url: str = Field(
        default=DEFAULT_CONTROLLER_URL,
        validation_alias=AliasChoices("CONTROLLER_URL", "CB_CONTROLLER_URL", "CB_BASE_URL"),
    )
    controller_host: str = Field(
        default=DEFAULT_CONTROLLER_HOST,
        validation_alias=AliasChoices("CONTROLLER_HOST", "CB_CONTROLLER_HOST"),
    )
    controller_port: int = Field(
        default=DEFAULT_CONTROLLER_PORT,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("CONTROLLER_PORT", "CB_CONTROLLER_PORT"),
    )
    api_key: str | None = Field(
        default=None,
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
        default=DEFAULT_REDIS_URL,
        validation_alias=AliasChoices("CB_REDIS_URL", "REDIS_URL"),
    )
    mongo_url: str = Field(
        default=DEFAULT_MONGO_URL,
        validation_alias=AliasChoices("CB_MONGO_URL", "MONGO_URL"),
    )
    mongo_db_name: str = Field(
        default=DEFAULT_MONGO_DB_NAME,
        validation_alias=AliasChoices("CB_MONGO_DB_NAME", "MONGO_DB_NAME"),
    )
    local_mode: bool = Field(
        default=True,
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
    rate_limit_per_min: int = Field(
        default=2400,
        ge=1,
        validation_alias=AliasChoices("CB_RATE_LIMIT_PER_MIN", "RATE_LIMIT_PER_MIN"),
    )
    max_payload_bytes: int = Field(
        default=DEFAULT_MAX_PAYLOAD_BYTES,
        ge=256,
        validation_alias=AliasChoices("CB_MAX_PAYLOAD_BYTES", "MAX_PAYLOAD_BYTES"),
    )
    data_dir: str = Field(
        default=DEFAULT_DATA_DIR,
        validation_alias=AliasChoices("CB_DATA_DIR", "DATA_DIR"),
    )
    frontend_dist_dir: str = Field(
        default=DEFAULT_FRONTEND_DIST_DIR,
        validation_alias=AliasChoices("CB_FRONTEND_DIST_DIR", "FRONTEND_DIST_DIR"),
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
        default=DEFAULT_DISPATCH_TIMEOUT_SEC,
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

    @field_validator("admin_token", "worker_secret")
    @classmethod
    def validate_non_empty_secret(cls, value: str, info: ValidationInfo) -> str:
        """Require non-empty ADMIN_TOKEN and WORKER_SECRET on startup."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name.upper()} is required and must be non-empty")
        return cleaned

    @field_validator("worker_urls", mode="before")
    @classmethod
    def parse_worker_urls(cls, value: str | list[str]) -> list[str]:
        """Parse comma-separated WORKER_URLS string or list and ensure non-empty."""
        raw_list = value.split(",") if isinstance(value, str) else value
        urls = [str(u).strip().rstrip("/") for u in raw_list if str(u).strip()]
        if not urls:
            raise ValueError("WORKER_URLS must contain at least one worker URL")
        return urls

    def worker_endpoints(self) -> list[WorkerEndpoint]:
        """Return parsed WorkerEndpoint objects for configured WORKER_URLS."""
        return parse_worker_endpoints(self.worker_urls)

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

    @model_validator(mode="after")
    def validate_api_key_when_required(self) -> Settings:
        """Refuse startup when CB_REQUIRE_API_KEY=true and CB_API_KEY is missing or blank."""
        cleaned = self.api_key.strip() if self.api_key is not None else ""
        self.api_key = cleaned or None
        if self.require_api_key and self.api_key is None:
            raise ValueError(
                "CB_API_KEY is required and must be non-empty when CB_REQUIRE_API_KEY=true"
            )
        return self


class WorkerSettings(BaseSettings):
    """Settings for internal worker executor and telemetry agent."""

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    worker_id: str = Field(
        default=DEFAULT_WORKER_ID,
        validation_alias=AliasChoices("WORKER_ID", "CB_WORKER_ID"),
    )
    worker_ip: str = Field(
        default=DEFAULT_WORKER_HOST,
        validation_alias=AliasChoices("WORKER_IP", "CB_WORKER_IP"),
    )
    worker_port: int = Field(
        default=DEFAULT_WORKER_PORT,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("WORKER_PORT", "CB_WORKER_PORT"),
    )
    worker_total_mem_mb: float = Field(
        default=DEFAULT_WORKER_TOTAL_MEM_MB,
        gt=0.0,
        validation_alias=AliasChoices("WORKER_TOTAL_MEM_MB", "CB_WORKER_TOTAL_MEM_MB"),
    )
    worker_base_cpu_pct: float = Field(
        default=DEFAULT_WORKER_BASE_CPU_PCT,
        ge=0.0,
        le=100.0,
        validation_alias=AliasChoices("WORKER_BASE_CPU_PCT", "CB_WORKER_BASE_CPU_PCT"),
    )
    worker_base_mem_mb: float = Field(
        default=DEFAULT_WORKER_BASE_MEM_MB,
        ge=0.0,
        validation_alias=AliasChoices("WORKER_BASE_MEM_MB", "CB_WORKER_BASE_MEM_MB"),
    )
    worker_time_scale: float = Field(
        default=DEFAULT_WORKER_TIME_SCALE,
        gt=0.0,
        validation_alias=AliasChoices("WORKER_TIME_SCALE", "CB_WORKER_TIME_SCALE"),
    )
    worker_max_physical_dim: int = Field(
        default=DEFAULT_WORKER_MAX_PHYSICAL_DIM,
        ge=1,
        validation_alias=AliasChoices("WORKER_MAX_PHYSICAL_DIM", "CB_WORKER_MAX_PHYSICAL_DIM"),
    )
    worker_concurrency_limit: int = Field(
        default=DEFAULT_WORKER_CONCURRENCY_LIMIT,
        ge=1,
        validation_alias=AliasChoices("WORKER_CONCURRENCY_LIMIT", "CB_WORKER_CONCURRENCY_LIMIT"),
    )
    worker_queue_capacity: int = Field(
        default=DEFAULT_WORKER_QUEUE_CAPACITY,
        ge=0,
        validation_alias=AliasChoices("WORKER_QUEUE_CAPACITY", "CB_WORKER_QUEUE_CAPACITY"),
    )
    worker_task_timeout_sec: float = Field(
        default=DEFAULT_WORKER_TASK_TIMEOUT_SEC,
        gt=0.0,
        validation_alias=AliasChoices("WORKER_TASK_TIMEOUT_SEC", "CB_WORKER_TASK_TIMEOUT_SEC"),
    )
    max_payload_bytes: int = Field(
        default=DEFAULT_MAX_PAYLOAD_BYTES,
        ge=256,
        validation_alias=AliasChoices("MAX_PAYLOAD_BYTES", "CB_MAX_PAYLOAD_BYTES"),
    )
    heavy_task_iterations: int = Field(
        default=DEFAULT_HEAVY_TASK_ITERATIONS,
        ge=1,
        validation_alias=AliasChoices("HEAVY_TASK_ITERATIONS", "CB_HEAVY_TASK_ITERATIONS"),
    )
    worker_enable_agent: bool = Field(
        default=False,
        validation_alias=AliasChoices("WORKER_ENABLE_AGENT", "CB_WORKER_ENABLE_AGENT"),
    )
    worker_telemetry_interval: float = Field(
        default=DEFAULT_TELEMETRY_INTERVAL_SEC,
        gt=0.1,
        validation_alias=AliasChoices("WORKER_TELEMETRY_INTERVAL", "CB_WORKER_TELEMETRY_INTERVAL"),
    )
    controller_url: str = Field(
        default=DEFAULT_CONTROLLER_URL,
        validation_alias=AliasChoices("CONTROLLER_URL", "CB_CONTROLLER_URL", "CB_BASE_URL"),
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CB_API_KEY", "API_KEY"),
    )
    worker_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WORKER_SECRET", "CB_WORKER_SECRET"),
    )


class ClientSettings(BaseSettings):
    """Settings for verification scripts, traffic generators, and external load tools."""

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    controller_url: str = Field(
        default=DEFAULT_CONTROLLER_URL,
        validation_alias=AliasChoices("CB_BASE_URL", "CONTROLLER_URL", "CB_CONTROLLER_URL"),
    )
    worker_urls: Annotated[list[str], NoDecode] = Field(
        default=list(DEFAULT_WORKER_URLS),
        validation_alias=AliasChoices("WORKER_URLS", "CB_WORKER_URLS"),
    )
    worker_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WORKER_URL", "CB_WORKER_URL"),
    )
    admin_token: str = Field(
        default="",
        validation_alias=AliasChoices("ADMIN_TOKEN", "CB_ADMIN_TOKEN"),
    )
    worker_secret: str = Field(
        default="",
        validation_alias=AliasChoices("WORKER_SECRET", "CB_WORKER_SECRET"),
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CB_API_KEY", "API_KEY"),
    )

    @field_validator("worker_urls", mode="before")
    @classmethod
    def parse_client_worker_urls(cls, value: str | list[str]) -> list[str]:
        raw_list = value.split(",") if isinstance(value, str) else value
        urls = [str(u).strip().rstrip("/") for u in raw_list if str(u).strip()]
        return urls or list(DEFAULT_WORKER_URLS)

    def resolved_worker_url(self) -> str:
        """Return explicit WORKER_URL/CB_WORKER_URL or the first configured WORKER_URLS endpoint."""
        if self.worker_url and self.worker_url.strip():
            return self.worker_url.strip().rstrip("/")
        endpoints = parse_worker_endpoints(self.worker_urls)
        return endpoints[0].url if endpoints else DEFAULT_WORKER_URLS[0]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()

