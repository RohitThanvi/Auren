"""Provider-defined hosting policy, loaded from a local file only the provider controls.

The policy is the upper bound on what the agent may ever offer. Nothing received from the
backend or a buyer can raise it. Every field is explicit: there are no permissive defaults,
so a provider must make each choice consciously.
"""

import os
import stat
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from auren_agent.hardware.models import FrozenModel

MAX_POLICY_FILE_BYTES = 64 * 1024
# Bounds for the provider's thermal ceiling: below the lower bound the host could never host;
# above the upper bound is past the point where most CPUs and GPUs throttle or shut down.
MIN_THERMAL_LIMIT_CELSIUS = 40.0
MAX_THERMAL_LIMIT_CELSIUS = 100.0


class PolicyError(Exception):
    """The policy file is missing, unsafe or invalid. The agent must not guess a policy."""


class PauseBehavior(StrEnum):
    """What a pause does to sessions that are already running."""

    DRAIN = "drain"
    TERMINATE = "terminate"


class ProviderPolicy(FrozenModel):
    schema_version: Literal[1]
    enabled: bool
    paused: bool
    cpu_cores: int = Field(ge=0)
    memory_bytes: int = Field(ge=0)
    storage_bytes: int = Field(ge=0)
    gpu_uuids: list[str]
    max_hosting_duration_seconds: int = Field(gt=0)
    max_temperature_celsius: float = Field(
        ge=MIN_THERMAL_LIMIT_CELSIUS, le=MAX_THERMAL_LIMIT_CELSIUS
    )
    allow_without_thermal_sensors: bool
    pause_behavior: PauseBehavior
    benchmark_consent: bool

    @field_validator("gpu_uuids")
    @classmethod
    def _gpu_uuids_unique_and_non_empty(cls, value: list[str]) -> list[str]:
        if any(not item for item in value) or len(set(value)) != len(value):
            raise ValueError("gpu_uuids must be unique, non-empty strings")
        return value


def load_policy(path: Path) -> ProviderPolicy:
    """Load and validate the policy file, refusing files other local users could have altered."""
    try:
        info = path.stat()
    except OSError as exc:
        raise PolicyError(f"cannot read policy file {path}: {exc.strerror}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise PolicyError(f"policy path {path} is not a regular file")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PolicyError(f"policy file {path} is writable by group or others")
    if info.st_uid not in {0, os.geteuid()}:
        raise PolicyError(f"policy file {path} is owned by another user")
    if info.st_size > MAX_POLICY_FILE_BYTES:
        raise PolicyError(f"policy file {path} exceeds {MAX_POLICY_FILE_BYTES} bytes")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"cannot read policy file {path}") from exc
    try:
        return ProviderPolicy.model_validate_json(text)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'policy'}: {error['msg']}"
            for error in exc.errors(include_input=False)
        )
        raise PolicyError(f"invalid policy file {path}: {problems}") from exc
