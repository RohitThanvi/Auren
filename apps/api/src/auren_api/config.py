"""Environment-driven application configuration.

All operational limits live here and are overridable through ``AUREN_*`` environment
variables. Settings are validated at startup so a misconfigured deployment fails fast.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class RateLimitRule(BaseModel, frozen=True):
    """Fixed-window limit: at most ``limit`` requests per ``window_seconds``."""

    limit: int = Field(gt=0)
    window_seconds: int = Field(gt=0)


def _parse_rate_limit_rule(value: object) -> object:
    """Accept the environment form ``"<requests>/<window_seconds>"``."""
    if not isinstance(value, str):
        return value
    limit, separator, window = value.partition("/")
    if not separator or not limit.strip().isdigit() or not window.strip().isdigit():
        raise ValueError("rate limit must be formatted as '<requests>/<window_seconds>'")
    return {"limit": int(limit), "window_seconds": int(window)}


RateLimitSetting = Annotated[RateLimitRule, BeforeValidator(_parse_rate_limit_rule)]
CommaSeparated = Annotated[list[str], NoDecode]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _validate_origin(origin: str) -> str:
    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
        raise ValueError(f"'{origin}' must be an origin such as https://app.example.com")
    if parts.query or parts.fragment or "*" in origin:
        raise ValueError(f"'{origin}' must not contain wildcards, queries, or fragments")
    return f"{parts.scheme}://{parts.netloc}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUREN_", extra="forbid", frozen=True)

    environment: Environment
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    database_url: SecretStr
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    db_statement_timeout_ms: int = Field(default=5000, gt=0)
    redis_url: SecretStr
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0)

    cors_allowed_origins: CommaSeparated = Field(default_factory=list)
    trusted_proxy_count: int = Field(default=0, ge=0)
    max_request_body_bytes: int = Field(default=1_048_576, gt=0)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0)
    http_client_timeout_seconds: float = Field(default=5.0, gt=0)

    clerk_issuer: str
    clerk_authorized_parties: CommaSeparated = Field(default_factory=list)
    clerk_audience: str | None = None
    auth_clock_leeway_seconds: int = Field(default=10, ge=0, le=60)
    jwks_cache_ttl_seconds: int = Field(default=3600, gt=0)
    jwks_min_refresh_interval_seconds: int = Field(default=30, ge=0)

    rate_limit_anonymous: RateLimitSetting = RateLimitRule(limit=60, window_seconds=60)
    rate_limit_authenticated: RateLimitSetting = RateLimitRule(limit=120, window_seconds=60)
    rate_limit_auth: RateLimitSetting = RateLimitRule(limit=10, window_seconds=60)
    rate_limit_ticket_creation: RateLimitSetting = RateLimitRule(limit=10, window_seconds=60)
    rate_limit_session_creation: RateLimitSetting = RateLimitRule(limit=5, window_seconds=60)
    rate_limit_upload: RateLimitSetting = RateLimitRule(limit=10, window_seconds=600)
    rate_limit_expensive: RateLimitSetting = RateLimitRule(limit=5, window_seconds=60)
    rate_limit_fail_open: bool = False

    @field_validator("cors_allowed_origins", "clerk_authorized_parties", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("cors_allowed_origins", "clerk_authorized_parties")
    @classmethod
    def _origins(cls, value: list[str]) -> list[str]:
        return [_validate_origin(origin) for origin in value]

    @field_validator("database_url")
    @classmethod
    def _database_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg:// scheme")
        return value

    @field_validator("redis_url")
    @classmethod
    def _redis_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use the redis:// or rediss:// scheme")
        return value

    @field_validator("clerk_issuer")
    @classmethod
    def _issuer(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment:
            raise ValueError("clerk_issuer must be an https URL without query or fragment")
        return value.rstrip("/")

    @field_validator("clerk_audience")
    @classmethod
    def _audience(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _production_requirements(self) -> Self:
        if self.environment is Environment.PRODUCTION and not self.clerk_authorized_parties:
            raise ValueError("clerk_authorized_parties is required in production")
        return self

    @property
    def clerk_jwks_url(self) -> str:
        return f"{self.clerk_issuer}/.well-known/jwks.json"

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from the environment
