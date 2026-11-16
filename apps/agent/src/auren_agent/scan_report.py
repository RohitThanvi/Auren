"""The report submitted with a platform scan.

The backend owner defines this contract (``packages/contracts/examples/inventory.json`` is the
shared example). It is the hardware inventory plus security capabilities, platform and network
facts. Everything here is reported by the agent; nothing is proven by the report alone.
"""

from auren_agent.hardware.host_facts import NetworkInterface, PlatformInfo
from auren_agent.hardware.models import HardwareInventory
from auren_agent.hardware.security import SecurityCapabilities


class ScanReport(HardwareInventory):
    security: SecurityCapabilities
    platform: PlatformInfo
    network: list[NetworkInterface]


def build_scan_report(
    inventory: HardwareInventory,
    security: SecurityCapabilities,
    platform: PlatformInfo,
    network: list[NetworkInterface],
) -> ScanReport:
    return ScanReport(**dict(inventory), security=security, platform=platform, network=network)
