"""Agent configuration from ``AUREN_AGENT_*`` environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentMode(StrEnum):
    """Only development mode exists: it never contacts the control plane or runs workloads."""

    DEVELOPMENT = "development"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUREN_AGENT_", extra="forbid", frozen=True)

    mode: AgentMode
    storage_path: Path
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    gpu_probe_timeout_seconds: float = Field(default=5.0, gt=0)
    # Hosting policy file written by the provider. Unset means hosting is disabled.
    policy_path: Path | None = None
    # Capacity always kept for the provider and the agent. These are conservative starting
    # values, not measured ones; providers can raise them. CPU reserve cannot be below 1 core.
    host_reserve_cpu_cores: int = Field(default=1, ge=1)
    host_reserve_memory_fraction: float = Field(default=0.25, gt=0, lt=1)
    host_reserve_storage_fraction: float = Field(default=0.10, gt=0, lt=1)


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()  # pyright: ignore[reportCallIssue]  # required fields come from the environment
