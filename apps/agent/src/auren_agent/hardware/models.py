"""Hardware inventory data model reported by the agent."""

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CpuInfo(_Frozen):
    model_name: str
    architecture: str
    logical_cores: int = Field(gt=0)
    physical_cores: int | None = Field(default=None, gt=0)
    hardware_virtualization: bool
    # CPU flags that indicate confidential-computing support (e.g. sev_snp, tdx_host_platform).
    # These are indicators reported by the CPU, not proof that a workload can be attested.
    confidential_computing_flags: list[str]


class MemoryInfo(_Frozen):
    total_bytes: int = Field(gt=0)
    available_bytes: int = Field(ge=0)


class GpuInfo(_Frozen):
    name: str
    memory_total_bytes: int = Field(ge=0)
    driver_version: str


class StorageInfo(_Frozen):
    path: str
    total_bytes: int = Field(gt=0)
    free_bytes: int = Field(ge=0)


class PlatformInfo(_Frozen):
    system: str
    kernel_release: str
    os_name: str
    kvm_available: bool


class NetworkInterface(_Frozen):
    name: str
    # Negotiated link speed in Mbit/s; None when the driver does not report one (e.g. Wi-Fi).
    speed_mbps: int | None = Field(default=None, gt=0)
    is_up: bool


class HardwareInventory(_Frozen):
    cpu: CpuInfo
    memory: MemoryInfo
    gpus: list[GpuInfo]
    storage: StorageInfo
    platform: PlatformInfo
    network: list[NetworkInterface]
