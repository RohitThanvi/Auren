"""Hardware inventory data model reported by the agent."""

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CpuInfo(_Frozen):
    model_name: str
    logical_cores: int = Field(gt=0)
    physical_cores: int | None = Field(default=None, gt=0)


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


class HardwareInventory(_Frozen):
    cpu: CpuInfo
    memory: MemoryInfo
    gpus: list[GpuInfo]
    storage: StorageInfo
