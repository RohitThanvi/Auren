"""Assemble the agent's view of the host: identity, capability, health, security, availability.

This report is local. It is not the backend wire format, which the backend owner defines.
"""

import structlog

from auren_agent import __version__
from auren_agent.config import AgentSettings
from auren_agent.hardware.health import HostHealth, LinuxHealthReader
from auren_agent.hardware.linux import LinuxHardwareProbe
from auren_agent.hardware.models import FrozenModel, HardwareInventory
from auren_agent.hardware.probe import HealthReader, SecurityProbe
from auren_agent.hardware.security import LinuxSecurityProbe, SecurityCapabilities
from auren_agent.resources.allocation import (
    AvailabilityReport,
    HostReserve,
    evaluate_availability,
)
from auren_agent.resources.benchmark_gate import benchmark_refusals
from auren_agent.resources.policy import ProviderPolicy, load_policy

logger = structlog.get_logger(__name__)


class AgentStatus(FrozenModel):
    agent_version: str
    inventory: HardwareInventory
    security: SecurityCapabilities
    health: HostHealth
    availability: AvailabilityReport
    benchmark_refusals: list[str]


def build_probe(settings: AgentSettings) -> LinuxHardwareProbe:
    return LinuxHardwareProbe(
        storage_path=settings.storage_path,
        gpu_probe_timeout_seconds=settings.gpu_probe_timeout_seconds,
    )


def load_configured_policy(settings: AgentSettings) -> ProviderPolicy | None:
    if settings.policy_path is None:
        return None
    return load_policy(settings.policy_path)


def collect_status(settings: AgentSettings) -> AgentStatus:
    """Raises ``HardwareProbeError`` or ``PolicyError``; callers decide how to fail."""
    probe = build_probe(settings)
    inventory = probe.scan()
    health_reader: HealthReader = LinuxHealthReader(
        gpu_probe_timeout_seconds=settings.gpu_probe_timeout_seconds,
        # GPU temperatures are queried only when the inventory found NVIDIA GPUs.
        nvidia_smi=probe.nvidia_smi if inventory.gpus else None,
    )
    health = health_reader.read()
    policy = load_configured_policy(settings)
    reserve = HostReserve(
        cpu_cores=settings.host_reserve_cpu_cores,
        memory_fraction=settings.host_reserve_memory_fraction,
        storage_fraction=settings.host_reserve_storage_fraction,
    )
    security_probe: SecurityProbe = LinuxSecurityProbe()
    return AgentStatus(
        agent_version=__version__,
        inventory=inventory,
        security=security_probe.scan(),
        health=health,
        availability=evaluate_availability(
            policy=policy, inventory=inventory, health=health, reserve=reserve
        ),
        benchmark_refusals=benchmark_refusals(
            policy=policy, health=health, logical_cores=inventory.cpu.logical_cores
        ),
    )
