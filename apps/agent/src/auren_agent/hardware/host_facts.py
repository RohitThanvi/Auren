"""Platform and network facts included in the scan report.

Kept apart from ``HardwareInventory`` so the capability inventory stays exactly as it was. Reported
facts only: the OS and sysfs are controlled by the provider.
"""

import platform
from pathlib import Path

from pydantic import Field

from auren_agent.hardware.models import FrozenModel


class PlatformInfo(FrozenModel):
    system: str
    architecture: str
    kernel_release: str
    os_name: str


class NetworkInterface(FrozenModel):
    name: str
    # Negotiated link speed in Mbit/s; None when the driver does not report one (e.g. Wi-Fi).
    speed_mbps: int | None = Field(default=None, gt=0)
    is_up: bool


class LinuxHostFactsProbe:
    def __init__(self, *, sys_root: Path = Path("/sys"), etc_root: Path = Path("/etc")) -> None:
        self._sys_root = sys_root
        self._etc_root = etc_root

    def platform_info(self) -> PlatformInfo:
        os_name = "unknown"
        try:
            release = (self._etc_root / "os-release").read_text(encoding="utf-8")
        except OSError:
            release = ""
        for line in release.splitlines():
            key, _, value = line.partition("=")
            if key == "PRETTY_NAME":
                os_name = value.strip().strip('"') or "unknown"
        return PlatformInfo(
            system=platform.system(),
            architecture=platform.machine(),
            kernel_release=platform.release(),
            os_name=os_name,
        )

    def network_interfaces(self) -> list[NetworkInterface]:
        """Physical network interfaces (those backed by a device), excluding loopback."""
        net_root = self._sys_root / "class" / "net"
        try:
            entries = sorted(net_root.iterdir())
        except OSError:
            return []
        interfaces: list[NetworkInterface] = []
        for entry in entries:
            if entry.name == "lo" or not (entry / "device").exists():
                continue
            interfaces.append(
                NetworkInterface(
                    name=entry.name,
                    speed_mbps=self._link_speed(entry / "speed"),
                    is_up=self._read(entry / "operstate") == "up",
                )
            )
        return interfaces

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _link_speed(path: Path) -> int | None:
        text = LinuxHostFactsProbe._read(path)
        return int(text) if text.lstrip("-").isdigit() and int(text) > 0 else None
