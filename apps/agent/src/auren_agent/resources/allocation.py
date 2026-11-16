"""Availability and allocatable capacity: what the agent may offer right now.

Allocatable capacity is always the minimum of what the provider approved, what the hardware
has after a host reserve, and what is currently free. It is never larger than any of them.
GPUs are whole-device and exclusive: a GPU is offered only if the provider listed its UUID,
and no sharing or partitioning is assumed to be safe.
"""

import math
from enum import StrEnum

from pydantic import Field

from auren_agent.hardware.health import HostHealth
from auren_agent.hardware.models import FrozenModel, HardwareInventory
from auren_agent.resources.policy import ProviderPolicy


class AvailabilityState(StrEnum):
    DISABLED = "disabled"
    PAUSED = "paused"
    THERMALLY_RESTRICTED = "thermally_restricted"
    THERMAL_MONITORING_UNAVAILABLE = "thermal_monitoring_unavailable"
    AVAILABLE = "available"


class HostReserve(FrozenModel):
    """Capacity always kept for the provider's own use and for the agent itself."""

    cpu_cores: int = Field(ge=1)
    memory_fraction: float = Field(gt=0, lt=1)
    storage_fraction: float = Field(gt=0, lt=1)


class AllocatableCapacity(FrozenModel):
    cpu_cores: int = Field(ge=0)
    memory_bytes: int = Field(ge=0)
    storage_bytes: int = Field(ge=0)
    gpu_uuids: list[str]


class AvailabilityReport(FrozenModel):
    state: AvailabilityState
    allocatable: AllocatableCapacity
    reasons: list[str]


_NOTHING = AllocatableCapacity(cpu_cores=0, memory_bytes=0, storage_bytes=0, gpu_uuids=[])


def max_temperature_celsius(health: HostHealth) -> float | None:
    return max((reading.celsius for reading in health.temperatures), default=None)


def _clamp(name: str, approved: int, limits: dict[str, int]) -> tuple[int, str | None]:
    """Return ``min(approved, limits)`` (never negative) and the binding limit's reason."""
    binding_reason, binding_value = min(limits.items(), key=lambda item: item[1])
    if binding_value >= approved:
        return approved, None
    return max(0, binding_value), f"{name}_limited_by_{binding_reason}"


def evaluate_availability(
    *,
    policy: ProviderPolicy | None,
    inventory: HardwareInventory,
    health: HostHealth,
    reserve: HostReserve,
) -> AvailabilityReport:
    if policy is None:
        return AvailabilityReport(
            state=AvailabilityState.DISABLED, allocatable=_NOTHING, reasons=["no_policy_configured"]
        )
    if not policy.enabled:
        return AvailabilityReport(
            state=AvailabilityState.DISABLED, allocatable=_NOTHING, reasons=["hosting_not_enabled"]
        )
    if policy.paused:
        return AvailabilityReport(
            state=AvailabilityState.PAUSED, allocatable=_NOTHING, reasons=["provider_paused"]
        )
    hottest = max_temperature_celsius(health)
    if hottest is None and not policy.allow_without_thermal_sensors:
        return AvailabilityReport(
            state=AvailabilityState.THERMAL_MONITORING_UNAVAILABLE,
            allocatable=_NOTHING,
            reasons=["no_temperature_sensors_readable"],
        )
    if hottest is not None and hottest >= policy.max_temperature_celsius:
        return AvailabilityReport(
            state=AvailabilityState.THERMALLY_RESTRICTED,
            allocatable=_NOTHING,
            reasons=["temperature_at_or_above_provider_limit"],
        )

    reasons: list[str] = []
    memory_reserve = math.ceil(inventory.memory.total_bytes * reserve.memory_fraction)
    storage_reserve = math.ceil(inventory.storage.total_bytes * reserve.storage_fraction)
    cpu, cpu_reason = _clamp(
        "cpu",
        policy.cpu_cores,
        {"host_reserve": inventory.cpu.logical_cores - reserve.cpu_cores},
    )
    memory, memory_reason = _clamp(
        "memory",
        policy.memory_bytes,
        {
            "host_reserve": inventory.memory.total_bytes - memory_reserve,
            "current_host_usage": inventory.memory.available_bytes - memory_reserve,
        },
    )
    storage, storage_reason = _clamp(
        "storage",
        policy.storage_bytes,
        {"host_reserve": inventory.storage.free_bytes - storage_reserve},
    )
    reasons.extend(reason for reason in (cpu_reason, memory_reason, storage_reason) if reason)

    detected = {gpu.uuid for gpu in inventory.gpus}
    gpus = [uuid for uuid in policy.gpu_uuids if uuid in detected]
    if len(gpus) != len(policy.gpu_uuids):
        reasons.append("approved_gpu_not_detected")

    return AvailabilityReport(
        state=AvailabilityState.AVAILABLE,
        allocatable=AllocatableCapacity(
            cpu_cores=cpu, memory_bytes=memory, storage_bytes=storage, gpu_uuids=gpus
        ),
        reasons=reasons,
    )
