"""Agent configuration from ``AUREN_AGENT_*`` environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentMode(StrEnum):
    """Only development mode exists: it never contacts the control plane or runs workloads."""

    DEVELOPMENT = "development"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUREN_AGENT_", extra="forbid", frozen=True, env_ignore_empty=True
    )

    mode: AgentMode
    storage_path: Path
    # Where the agent keeps its private key and machine id. Required for network commands.
    state_dir: Path | None = None
    # Auren API base URL. https required; plain http is accepted for loopback only (development).
    control_plane_url: str | None = None
    # One-time token from the provider dashboard. Read from the environment, never from argv.
    enrollment_token: SecretStr | None = None
    http_timeout_seconds: float = Field(default=30.0, gt=0)
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    gpu_probe_timeout_seconds: float = Field(default=5.0, gt=0)
    # Hosting policy file written by the provider. Unset means hosting is disabled.
    policy_path: Path | None = None
    # Capacity always kept for the provider and the agent. These are conservative starting
    # values, not measured ones; providers can raise them. CPU reserve cannot be below 1 core.
    host_reserve_cpu_cores: int = Field(default=1, ge=1)
    host_reserve_memory_fraction: float = Field(default=0.25, gt=0, lt=1)
    host_reserve_storage_fraction: float = Field(default=0.10, gt=0, lt=1)

    @field_validator("control_plane_url")
    @classmethod
    def _control_plane_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.query
            or parts.fragment
        ):
            raise ValueError("control_plane_url must be an http(s) URL without query or fragment")
        if parts.scheme == "http" and not loopback:
            raise ValueError("control_plane_url must use https (http is allowed for loopback only)")
        if parts.path not in {"", "/"}:
            raise ValueError("control_plane_url must not contain a path (request paths are signed)")
        return f"{parts.scheme}://{parts.netloc}"


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()  # pyright: ignore[reportCallIssue]  # required fields come from the environment
