"""Host health readings: load and temperatures. Health is separate from capability.

Temperatures come from hwmon, thermal zones and (when present) ``nvidia-smi``. A machine
may expose none of them (virtual machines, some laptops, containers); in that case
``temperatures`` is empty and callers must treat thermal limits as unverifiable.
"""

from pathlib import Path

import structlog

from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.hardware.models import FrozenModel
from auren_agent.hardware.nvidia import query_gpu_fields

logger = structlog.get_logger(__name__)

_MILLIDEGREES_PER_DEGREE = 1000.0
# Readings outside this range are sensor faults, not temperatures: ignore rather than trust.
_PLAUSIBLE_MIN_CELSIUS = -50.0
_PLAUSIBLE_MAX_CELSIUS = 150.0
_GPU_TEMPERATURE_FIELDS = ("uuid", "temperature.gpu")


class TemperatureReading(FrozenModel):
    sensor: str
    celsius: float


class HostHealth(FrozenModel):
    load_average_1m: float
    load_average_5m: float
    load_average_15m: float
    temperatures: list[TemperatureReading]


class LinuxHealthReader:
    def __init__(
        self,
        *,
        gpu_probe_timeout_seconds: float,
        proc_root: Path = Path("/proc"),
        sys_root: Path = Path("/sys"),
        nvidia_smi: str | None = None,
    ) -> None:
        self._gpu_probe_timeout_seconds = gpu_probe_timeout_seconds
        self._proc_root = proc_root
        self._sys_root = sys_root
        self._nvidia_smi = nvidia_smi

    def read(self) -> HostHealth:
        one, five, fifteen = self._read_load()
        return HostHealth(
            load_average_1m=one,
            load_average_5m=five,
            load_average_15m=fifteen,
            temperatures=[*self._read_hwmon(), *self._read_thermal_zones(), *self._read_gpus()],
        )

    def _read_load(self) -> tuple[float, float, float]:
        path = self._proc_root / "loadavg"
        try:
            fields = path.read_text(encoding="utf-8").split()
            return float(fields[0]), float(fields[1]), float(fields[2])
        except (OSError, ValueError, IndexError) as exc:
            raise HardwareProbeError(f"cannot read load average from {path}") from exc

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    @staticmethod
    def _celsius_from_millidegrees(raw: str | None) -> float | None:
        if raw is None:
            return None
        try:
            celsius = int(raw) / _MILLIDEGREES_PER_DEGREE
        except ValueError:
            return None
        if not _PLAUSIBLE_MIN_CELSIUS <= celsius <= _PLAUSIBLE_MAX_CELSIUS:
            logger.warning("temperature_reading_implausible")
            return None
        return celsius

    def _read_hwmon(self) -> list[TemperatureReading]:
        readings: list[TemperatureReading] = []
        for chip in sorted((self._sys_root / "class" / "hwmon").glob("hwmon*")):
            chip_name = self._read_text(chip / "name") or chip.name
            for input_file in sorted(chip.glob("temp*_input")):
                celsius = self._celsius_from_millidegrees(self._read_text(input_file))
                if celsius is None:
                    continue
                prefix = input_file.name.removesuffix("_input")
                label = self._read_text(chip / f"{prefix}_label") or prefix
                readings.append(
                    TemperatureReading(sensor=f"hwmon:{chip_name}:{label}", celsius=celsius)
                )
        return readings

    def _read_thermal_zones(self) -> list[TemperatureReading]:
        readings: list[TemperatureReading] = []
        for zone in sorted((self._sys_root / "class" / "thermal").glob("thermal_zone*")):
            celsius = self._celsius_from_millidegrees(self._read_text(zone / "temp"))
            if celsius is None:
                continue
            zone_type = self._read_text(zone / "type") or zone.name
            readings.append(TemperatureReading(sensor=f"thermal:{zone_type}", celsius=celsius))
        return readings

    def _read_gpus(self) -> list[TemperatureReading]:
        if self._nvidia_smi is None:
            return []
        rows = query_gpu_fields(
            self._nvidia_smi,
            _GPU_TEMPERATURE_FIELDS,
            timeout_seconds=self._gpu_probe_timeout_seconds,
        )
        readings: list[TemperatureReading] = []
        for row in rows or []:
            try:
                celsius = float(row[1])
            except (IndexError, ValueError):
                logger.warning("gpu_temperature_unparseable_row")
                continue
            if _PLAUSIBLE_MIN_CELSIUS <= celsius <= _PLAUSIBLE_MAX_CELSIUS:
                readings.append(TemperatureReading(sensor=f"gpu:{row[0]}", celsius=celsius))
        return readings
