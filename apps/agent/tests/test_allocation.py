from typing import Any

import pytest

from auren_agent.hardware.health import HostHealth, TemperatureReading
from auren_agent.hardware.models import (
    CpuInfo,
    GpuInfo,
    HardwareInventory,
    MemoryInfo,
    StorageInfo,
)
from auren_agent.resources.allocation import (
    AvailabilityState,
    HostReserve,
    evaluate_availability,
)
from auren_agent.resources.policy import ProviderPolicy

GIB = 1024**3
RESERVE = HostReserve(cpu_cores=1, memory_fraction=0.25, storage_fraction=0.10)


def inventory(*, available: int = 14 * GIB, free: int = 800 * GIB) -> HardwareInventory:
    return HardwareInventory(
        cpu=CpuInfo(model_name="t", logical_cores=8, physical_cores=4),
        memory=MemoryInfo(total_bytes=16 * GIB, available_bytes=available),
        gpus=[
            GpuInfo(index=0, uuid="GPU-aaa", name="g", memory_total_bytes=GIB, driver_version="1")
        ],
        storage=StorageInfo(path="/x", total_bytes=1000 * GIB, free_bytes=free),
    )


def policy(**overrides: Any) -> ProviderPolicy:
    values: dict[str, Any] = {
        "schema_version": 1,
        "enabled": True,
        "paused": False,
        "cpu_cores": 4,
        "memory_bytes": 8 * GIB,
        "storage_bytes": 100 * GIB,
        "gpu_uuids": [],
        "max_hosting_duration_seconds": 3600,
        "max_temperature_celsius": 80.0,
        "allow_without_thermal_sensors": False,
        "pause_behavior": "drain",
        "benchmark_consent": False,
    }
    return ProviderPolicy.model_validate({**values, **overrides})


def health(*celsius: float) -> HostHealth:
    return HostHealth(
        load_average_1m=0.1,
        load_average_5m=0.1,
        load_average_15m=0.1,
        temperatures=[TemperatureReading(sensor=f"s{i}", celsius=c) for i, c in enumerate(celsius)],
    )


def evaluate(p: ProviderPolicy | None, inv: HardwareInventory, h: HostHealth):
    return evaluate_availability(policy=p, inventory=inv, health=h, reserve=RESERVE)


def test_approved_capacity_is_offered_when_the_host_has_room() -> None:
    report = evaluate(policy(), inventory(), health(50))
    assert report.state is AvailabilityState.AVAILABLE
    allocatable = report.allocatable
    assert (allocatable.cpu_cores, allocatable.memory_bytes, allocatable.storage_bytes) == (
        4,
        8 * GIB,
        100 * GIB,
    )
    assert report.reasons == []


def test_no_policy_means_nothing_is_offered() -> None:
    report = evaluate(None, inventory(), health(50))
    assert report.state is AvailabilityState.DISABLED
    assert report.allocatable.cpu_cores == 0
    assert report.reasons == ["no_policy_configured"]


def test_disabled_and_paused_policies_offer_nothing() -> None:
    assert evaluate(policy(enabled=False), inventory(), health(50)).state is (
        AvailabilityState.DISABLED
    )
    paused = evaluate(policy(paused=True), inventory(), health(50))
    assert paused.state is AvailabilityState.PAUSED
    assert paused.allocatable.memory_bytes == 0


def test_the_whole_machine_cannot_be_approved() -> None:
    report = evaluate(
        policy(cpu_cores=8, memory_bytes=16 * GIB, storage_bytes=1000 * GIB),
        inventory(available=16 * GIB, free=1000 * GIB),
        health(50),
    )
    allocatable = report.allocatable
    assert allocatable.cpu_cores == 7
    assert allocatable.memory_bytes == 12 * GIB
    assert allocatable.storage_bytes == 900 * GIB
    assert report.reasons == [
        "cpu_limited_by_host_reserve",
        "memory_limited_by_host_reserve",
        "storage_limited_by_host_reserve",
    ]


def test_current_host_memory_use_lowers_the_offer() -> None:
    report = evaluate(policy(), inventory(available=6 * GIB), health(50))
    assert report.allocatable.memory_bytes == 2 * GIB
    assert "memory_limited_by_current_host_usage" in report.reasons


def test_offer_never_goes_negative() -> None:
    report = evaluate(policy(), inventory(available=1 * GIB, free=10 * GIB), health(50))
    assert report.allocatable.memory_bytes == 0
    assert report.allocatable.storage_bytes == 0


def test_only_approved_and_detected_gpus_are_offered() -> None:
    assert evaluate(policy(), inventory(), health(50)).allocatable.gpu_uuids == []
    approved = evaluate(policy(gpu_uuids=["GPU-aaa"]), inventory(), health(50))
    assert approved.allocatable.gpu_uuids == ["GPU-aaa"]
    missing = evaluate(policy(gpu_uuids=["GPU-aaa", "GPU-zzz"]), inventory(), health(50))
    assert missing.allocatable.gpu_uuids == ["GPU-aaa"]
    assert "approved_gpu_not_detected" in missing.reasons


@pytest.mark.parametrize("hottest", [80.0, 95.0])
def test_temperature_at_or_above_limit_stops_offers(hottest: float) -> None:
    report = evaluate(policy(), inventory(), health(50, hottest))
    assert report.state is AvailabilityState.THERMALLY_RESTRICTED
    assert report.allocatable.cpu_cores == 0


def test_missing_sensors_fail_closed_unless_the_provider_allowed_it() -> None:
    closed = evaluate(policy(), inventory(), health())
    assert closed.state is AvailabilityState.THERMAL_MONITORING_UNAVAILABLE
    assert closed.allocatable.cpu_cores == 0
    allowed = evaluate(policy(allow_without_thermal_sensors=True), inventory(), health())
    assert allowed.state is AvailabilityState.AVAILABLE
