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


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()  # pyright: ignore[reportCallIssue]  # required fields come from the environment
