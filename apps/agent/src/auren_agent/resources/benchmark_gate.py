"""Preconditions for benchmarking. No benchmark runner exists yet; this gate must pass first.

Benchmarks are optional, consented to by the provider, and must never run on a host that is
hot, busy with the provider's own work, or cannot be monitored.
"""

from auren_agent.hardware.health import HostHealth
from auren_agent.resources.allocation import max_temperature_celsius
from auren_agent.resources.policy import ProviderPolicy

# Refuse when the 1-minute load average exceeds this many runnable tasks per logical core:
# above it the provider is likely using the machine and a benchmark would compete with them.
BENCHMARK_MAX_LOAD_PER_CORE = 0.5


def benchmark_refusals(
    *, policy: ProviderPolicy | None, health: HostHealth, logical_cores: int
) -> list[str]:
    """Return reason codes that forbid a benchmark now; an empty list means it may start."""
    if policy is None or not policy.benchmark_consent:
        return ["provider_consent_missing"]
    refusals: list[str] = []
    if policy.paused:
        refusals.append("provider_paused")
    hottest = max_temperature_celsius(health)
    if hottest is None:
        refusals.append("thermal_monitoring_unavailable")
    elif hottest >= policy.max_temperature_celsius:
        refusals.append("temperature_at_or_above_provider_limit")
    if health.load_average_1m > BENCHMARK_MAX_LOAD_PER_CORE * logical_cores:
        refusals.append("host_busy")
    return refusals
