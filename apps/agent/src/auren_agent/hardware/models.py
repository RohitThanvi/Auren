"""Hardware inventory data model reported by the agent."""

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CpuInfo(FrozenModel):
    model_name: str
    logical_cores: int = Field(gt=0)
    physical_cores: int | None = Field(default=None, gt=0)


class MemoryInfo(FrozenModel):
    total_bytes: int = Field(gt=0)
    available_bytes: int = Field(ge=0)


class GpuInfo(FrozenModel):
    index: int = Field(ge=0)
    uuid: str = Field(min_length=1)
    name: str
    memory_total_bytes: int = Field(ge=0)
    driver_version: str


class StorageInfo(FrozenModel):
    path: str
    total_bytes: int = Field(gt=0)
    free_bytes: int = Field(ge=0)


class HardwareInventory(FrozenModel):
    cpu: CpuInfo
    memory: MemoryInfo
    gpus: list[GpuInfo]
    storage: StorageInfo
