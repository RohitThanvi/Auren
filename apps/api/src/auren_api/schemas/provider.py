"""Provider API contract. The inventory report mirrors the agent's scan output exactly."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from auren_api.domain.inventory import Allocatable, InventorySnapshot
from auren_api.domain.machine import ListingTier, MachineStatus
from auren_api.domain.money import Currency

MAX_LOGICAL_CORES = 4096
MAX_BYTES = 2**50  # 1 PiB: rejects absurd self-reported values
MAX_GPUS = 16
MAX_NETWORK_INTERFACES = 32
MAX_CGROUP_CONTROLLERS = 32
MAX_LINK_SPEED_MBPS = 1_000_000
MAX_MACHINE_NAME_LENGTH = 100

# Printable text only: no control characters (self-reported text is shown to other users).
_NO_CONTROL_CHARS = r"^[^\x00-\x1f\x7f]+$"


def _printable(max_length: int) -> StringConstraints:
    return StringConstraints(
        strip_whitespace=True, min_length=1, max_length=max_length, pattern=_NO_CONTROL_CHARS
    )


Text32 = Annotated[str, _printable(32)]
Text50 = Annotated[str, _printable(50)]
Text100 = Annotated[str, _printable(100)]
Text200 = Annotated[str, _printable(200)]
Text4096 = Annotated[str, _printable(4096)]
MachineName = Annotated[str, _printable(MAX_MACHINE_NAME_LENGTH)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CpuReport(_Strict):
    model_name: Text200
    logical_cores: int = Field(ge=1, le=MAX_LOGICAL_CORES)
    physical_cores: int | None = Field(default=None, ge=1, le=MAX_LOGICAL_CORES)

    @model_validator(mode="after")
    def _physical_not_above_logical(self) -> Self:
        if self.physical_cores is not None and self.physical_cores > self.logical_cores:
            raise ValueError("physical_cores cannot exceed logical_cores")
        return self


class MemoryReport(_Strict):
    total_bytes: int = Field(ge=1, le=MAX_BYTES)
    available_bytes: int = Field(ge=0, le=MAX_BYTES)

    @model_validator(mode="after")
    def _available_within_total(self) -> Self:
        if self.available_bytes > self.total_bytes:
            raise ValueError("available_bytes cannot exceed total_bytes")
        return self


class GpuReport(_Strict):
    index: int = Field(ge=0, lt=MAX_GPUS)
    uuid: Text200
    name: Text200
    memory_total_bytes: int = Field(ge=0, le=MAX_BYTES)
    driver_version: Text50


class StorageReport(_Strict):
    path: Text4096
    total_bytes: int = Field(ge=1, le=MAX_BYTES)
    free_bytes: int = Field(ge=0, le=MAX_BYTES)

    @model_validator(mode="after")
    def _free_within_total(self) -> Self:
        if self.free_bytes > self.total_bytes:
            raise ValueError("free_bytes cannot exceed total_bytes")
        return self


class PlatformReport(_Strict):
    system: Text50
    architecture: Text50
    kernel_release: Text100
    os_name: Text200


class SecurityReport(_Strict):
    """Reported host capabilities. Indicators only: nothing here is attested."""

    cpu_reports_hardware_virtualization: bool
    kvm_device_present: bool
    kvm_device_usable_by_agent: bool
    cgroup_v2: bool
    cgroup_controllers: list[Text32] = Field(max_length=MAX_CGROUP_CONTROLLERS)
    agent_running_as_root: bool
    confidential_computing_flags: list[Literal["sev", "sev_es", "sev_snp", "tdx_host_platform"]] = (
        Field(max_length=4)
    )


class NetworkInterfaceReport(_Strict):
    name: Text32
    speed_mbps: int | None = Field(default=None, ge=1, le=MAX_LINK_SPEED_MBPS)
    is_up: bool


class InventoryReport(_Strict):
    cpu: CpuReport
    memory: MemoryReport
    gpus: list[GpuReport] = Field(max_length=MAX_GPUS)
    storage: StorageReport
    security: SecurityReport
    platform: PlatformReport
    network: list[NetworkInterfaceReport] = Field(max_length=MAX_NETWORK_INTERFACES)

    @model_validator(mode="after")
    def _gpus_are_consistently_indexed(self) -> Self:
        """Listings refer to GPUs by index, so indices must be 0..n-1 and devices distinct."""
        if sorted(gpu.index for gpu in self.gpus) != list(range(len(self.gpus))):
            raise ValueError("gpu indices must be unique and contiguous from 0")
        if len({gpu.uuid for gpu in self.gpus}) != len(self.gpus):
            raise ValueError("gpu uuids must be unique")
        return self

    def to_snapshot(self) -> InventorySnapshot:
        by_index = sorted(self.gpus, key=lambda gpu: gpu.index)
        return InventorySnapshot(
            logical_cores=self.cpu.logical_cores,
            memory_total_bytes=self.memory.total_bytes,
            storage_total_bytes=self.storage.total_bytes,
            gpu_memory_bytes=tuple(gpu.memory_total_bytes for gpu in by_index),
            hardware_virtualization=self.security.cpu_reports_hardware_virtualization,
            kvm_available=self.security.kvm_device_present,
            confidential_computing_flags=tuple(self.security.confidential_computing_flags),
        )


class CreateMachineRequest(_Strict):
    name: MachineName


class AllocatableRequest(_Strict):
    tier: Literal["standard", "confidential"]
    cpu_cores: int = Field(ge=1, le=MAX_LOGICAL_CORES)
    memory_bytes: int = Field(ge=1, le=MAX_BYTES)
    gpu_indices: list[int] = Field(max_length=MAX_GPUS)
    storage_bytes: int = Field(ge=1, le=MAX_BYTES)

    def tier_domain(self) -> ListingTier:
        return ListingTier(self.tier)

    def to_domain(self) -> Allocatable:
        return Allocatable(
            cpu_cores=self.cpu_cores,
            memory_bytes=self.memory_bytes,
            gpu_indices=tuple(self.gpu_indices),
            storage_bytes=self.storage_bytes,
        )


class ListingRequest(AllocatableRequest):
    price_per_hour_minor: int = Field(ge=1, le=MAX_BYTES)
    max_hosting_hours: int = Field(ge=1)


class MoneyResponse(BaseModel):
    amount_minor: int
    currency: Currency


class PriceRangeResponse(BaseModel):
    base: MoneyResponse
    floor: MoneyResponse
    ceiling: MoneyResponse


class InventorySummaryResponse(BaseModel):
    id: UUID
    scan_id: UUID
    received_at: datetime
    # Single-thread speed (SHA-256 chain, hashes/s) timed by the platform's own clock.
    cpu_hashes_per_second: int
    logical_cores: int
    memory_total_bytes: int
    storage_total_bytes: int
    gpu_count: int
    hardware_virtualization: bool
    kvm_available: bool
    confidential_computing_flags: list[str]
    # Produced by the platform's enrolled agent with a server-timed benchmark. Hardware facts are
    # still read on a machine the provider controls, so they are evidence, not proof.
    verification: Literal["agent_scanned"] = "agent_scanned"


class ListingResponse(BaseModel):
    tier: ListingTier
    price_per_hour: MoneyResponse
    cpu_cores: int
    memory_bytes: int
    gpu_indices: list[int]
    storage_bytes: int
    max_hosting_hours: int


class MachineResponse(BaseModel):
    id: UUID
    name: str
    status: MachineStatus
    created_at: datetime
    # True once the platform has attested this machine for the confidential tier.
    confidential_verified: bool
    inventory: InventorySummaryResponse | None
    listing: ListingResponse | None


class EnrollmentResponse(BaseModel):
    # Shown once. Single use; only its hash is stored.
    enrollment_token: str
    expires_at: datetime


class ScanResponse(BaseModel):
    id: UUID
    status: Literal["pending", "claimed", "completed", "failed", "expired"]
    failure_reason: Literal["expired", "benchmark_mismatch"] | None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    cpu_hashes_per_second: int | None
