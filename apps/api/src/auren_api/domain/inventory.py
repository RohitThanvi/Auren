"""Machine capacity facts and the rules for what a provider may offer from them."""

from collections.abc import Sequence
from dataclasses import dataclass

from auren_api.domain.errors import RuleViolationError

BASIS_POINTS = 10_000


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    """Capacity facts extracted from a provider's scan (self-reported, not yet verified)."""

    logical_cores: int
    memory_total_bytes: int
    storage_total_bytes: int
    gpu_memory_bytes: tuple[int, ...]
    hardware_virtualization: bool
    kvm_available: bool


@dataclass(frozen=True, slots=True)
class Allocatable:
    """The slice of a machine a provider offers to buyers."""

    cpu_cores: int
    memory_bytes: int
    gpu_indices: tuple[int, ...]
    storage_bytes: int


def check_allocatable(
    snapshot: InventorySnapshot, allocatable: Allocatable, max_allocatable_bps: int
) -> None:
    """Raise ``RuleViolationError`` unless ``allocatable`` fits inside the scanned machine."""
    if allocatable.cpu_cores < 1 or allocatable.memory_bytes < 1 or allocatable.storage_bytes < 1:
        raise RuleViolationError(
            "allocation_exceeds_capacity", "CPU, memory and storage offers must be positive."
        )
    caps = {
        "CPU cores": (allocatable.cpu_cores, snapshot.logical_cores),
        "memory": (allocatable.memory_bytes, snapshot.memory_total_bytes),
        "storage": (allocatable.storage_bytes, snapshot.storage_total_bytes),
    }
    for label, (offered, total) in caps.items():
        if offered > total * max_allocatable_bps // BASIS_POINTS:
            raise RuleViolationError(
                "allocation_exceeds_capacity",
                f"Offered {label} exceeds the share of this machine that may be offered.",
            )
    _check_gpu_indices(allocatable.gpu_indices, len(snapshot.gpu_memory_bytes))


def _check_gpu_indices(indices: Sequence[int], gpu_count: int) -> None:
    if len(set(indices)) != len(indices) or any(not 0 <= i < gpu_count for i in indices):
        raise RuleViolationError(
            "allocation_exceeds_capacity", "GPU selection must reference distinct detected GPUs."
        )
