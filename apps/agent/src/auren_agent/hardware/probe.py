"""Hardware detection interface. Platform-specific implementations live in sibling modules."""

from typing import Protocol

from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.hardware.health import HostHealth
from auren_agent.hardware.models import HardwareInventory
from auren_agent.hardware.security import SecurityCapabilities


class HardwareProbe(Protocol):
    def scan(self) -> HardwareInventory:
        """Return the current hardware inventory or raise ``HardwareProbeError``."""
        ...


class SecurityProbe(Protocol):
    def scan(self) -> SecurityCapabilities:
        """Return reported security capabilities or raise ``HardwareProbeError``."""
        ...


class HealthReader(Protocol):
    def read(self) -> HostHealth:
        """Return current load and temperatures or raise ``HardwareProbeError``."""
        ...


__all__ = ["HardwareProbe", "HardwareProbeError", "HealthReader", "SecurityProbe"]
