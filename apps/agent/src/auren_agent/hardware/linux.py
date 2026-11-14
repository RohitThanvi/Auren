"""Linux hardware probe: reads /proc and shutil, and queries NVIDIA GPUs via nvidia-smi.

nvidia-smi is run through ``hardware.nvidia`` (fixed argument list, no shell, timeout).
"""

import shutil
from pathlib import Path

import structlog

from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.hardware.models import CpuInfo, GpuInfo, HardwareInventory, MemoryInfo, StorageInfo
from auren_agent.hardware.nvidia import query_gpu_fields

logger = structlog.get_logger(__name__)

_BYTES_PER_KIB = 1024
_BYTES_PER_MIB = 1024 * 1024
_GPU_FIELDS = ("index", "uuid", "name", "memory.total", "driver_version")


class LinuxHardwareProbe:
    def __init__(
        self,
        *,
        storage_path: Path,
        gpu_probe_timeout_seconds: float,
        proc_root: Path = Path("/proc"),
        nvidia_smi: str | None = None,
    ) -> None:
        self._storage_path = storage_path
        self._gpu_probe_timeout_seconds = gpu_probe_timeout_seconds
        self._proc_root = proc_root
        self._nvidia_smi = nvidia_smi if nvidia_smi is not None else shutil.which("nvidia-smi")

    @property
    def nvidia_smi(self) -> str | None:
        return self._nvidia_smi

    def scan(self) -> HardwareInventory:
        return HardwareInventory(
            cpu=self._read_cpu(),
            memory=self._read_memory(),
            gpus=self._read_gpus(),
            storage=self._read_storage(),
        )

    def _read_text(self, name: str) -> str:
        path = self._proc_root / name
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HardwareProbeError(f"cannot read {path}: {exc.strerror}") from exc

    def _read_cpu(self) -> CpuInfo:
        model_name = "unknown"
        logical = 0
        physical: set[tuple[str, str]] = set()
        physical_id = ""
        for line in self._read_text("cpuinfo").splitlines():
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "processor":
                logical += 1
                physical_id = ""
            elif key == "model name" and model_name == "unknown":
                model_name = value
            elif key == "physical id":
                physical_id = value
            elif key == "core id":
                physical.add((physical_id, value))
        if logical == 0:
            raise HardwareProbeError("no processors found in cpuinfo")
        return CpuInfo(
            model_name=model_name, logical_cores=logical, physical_cores=len(physical) or None
        )

    def _read_memory(self) -> MemoryInfo:
        values: dict[str, int] = {}
        for line in self._read_text("meminfo").splitlines():
            key, _, rest = line.partition(":")
            fields = rest.split()
            if key in {"MemTotal", "MemAvailable"} and fields and fields[0].isdigit():
                values[key] = int(fields[0]) * _BYTES_PER_KIB
        if "MemTotal" not in values or "MemAvailable" not in values:
            raise HardwareProbeError("meminfo lacks MemTotal or MemAvailable")
        return MemoryInfo(total_bytes=values["MemTotal"], available_bytes=values["MemAvailable"])

    def _read_storage(self) -> StorageInfo:
        try:
            usage = shutil.disk_usage(self._storage_path)
        except OSError as exc:
            raise HardwareProbeError(
                f"cannot read storage at {self._storage_path}: {exc.strerror}"
            ) from exc
        return StorageInfo(
            path=str(self._storage_path), total_bytes=usage.total, free_bytes=usage.free
        )

    def _read_gpus(self) -> list[GpuInfo]:
        if self._nvidia_smi is None:
            return []
        rows = query_gpu_fields(
            self._nvidia_smi, _GPU_FIELDS, timeout_seconds=self._gpu_probe_timeout_seconds
        )
        if rows is None:
            return []
        gpus: list[GpuInfo] = []
        for row in rows:
            if len(row) != len(_GPU_FIELDS) or not row[0].isdigit() or not row[3].isdigit():
                logger.warning("gpu_probe_unparseable_row")
                continue
            gpus.append(
                GpuInfo(
                    index=int(row[0]),
                    uuid=row[1],
                    name=row[2],
                    memory_total_bytes=int(row[3]) * _BYTES_PER_MIB,
                    driver_version=row[4],
                )
            )
        return gpus
