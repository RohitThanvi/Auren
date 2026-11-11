"""Linux hardware probe: reads /proc and shutil, and queries NVIDIA GPUs via nvidia-smi.

nvidia-smi is executed with a fixed argument list (no shell, no external input) and a timeout.
"""

import csv
import shutil
import subprocess
from pathlib import Path

import structlog

from auren_agent.hardware.models import CpuInfo, GpuInfo, HardwareInventory, MemoryInfo, StorageInfo
from auren_agent.hardware.probe import HardwareProbeError

logger = structlog.get_logger(__name__)

_BYTES_PER_KIB = 1024
_BYTES_PER_MIB = 1024 * 1024
_NVIDIA_QUERY = ("--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits")


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
        try:
            result = subprocess.run(  # noqa: S603  # fixed argv, no shell, no external input
                [self._nvidia_smi, *_NVIDIA_QUERY],
                capture_output=True,
                text=True,
                timeout=self._gpu_probe_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("gpu_probe_failed", error=type(exc).__name__)
            return []
        if result.returncode != 0:
            logger.warning("gpu_probe_nonzero_exit", returncode=result.returncode)
            return []
        gpus: list[GpuInfo] = []
        for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
            if len(row) != 3 or not row[1].strip().isdigit():
                logger.warning("gpu_probe_unparseable_row")
                continue
            gpus.append(
                GpuInfo(
                    name=row[0].strip(),
                    memory_total_bytes=int(row[1]) * _BYTES_PER_MIB,
                    driver_version=row[2].strip(),
                )
            )
        return gpus
