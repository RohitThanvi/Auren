"""Hardware detection interface. Platform-specific implementations live in sibling modules."""

from typing import Protocol

from auren_agent.hardware.models import HardwareInventory


class HardwareProbeError(Exception):
    """Hardware information required for an inventory could not be read."""


class HardwareProbe(Protocol):
    def scan(self) -> HardwareInventory:
        """Return the current hardware inventory or raise ``HardwareProbeError``."""
        ...
