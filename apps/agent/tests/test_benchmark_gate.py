from auren_agent.hardware.health import HostHealth, TemperatureReading
from auren_agent.resources.benchmark_gate import benchmark_refusals
from tests.test_allocation import policy


def health(celsius: float | None = 50.0, load: float = 0.1) -> HostHealth:
    readings = [] if celsius is None else [TemperatureReading(sensor="s", celsius=celsius)]
    return HostHealth(
        load_average_1m=load, load_average_5m=load, load_average_15m=load, temperatures=readings
    )


def test_no_policy_or_no_consent_refuses() -> None:
    assert benchmark_refusals(policy=None, health=health(), logical_cores=8) == [
        "provider_consent_missing"
    ]
    assert benchmark_refusals(policy=policy(), health=health(), logical_cores=8) == [
        "provider_consent_missing"
    ]


def test_consented_cool_idle_host_may_benchmark() -> None:
    assert (
        benchmark_refusals(policy=policy(benchmark_consent=True), health=health(), logical_cores=8)
        == []
    )


def test_every_safety_condition_refuses() -> None:
    consented = policy(benchmark_consent=True, paused=True)
    refusals = benchmark_refusals(policy=consented, health=health(90.0, load=6.0), logical_cores=8)
    assert refusals == ["provider_paused", "temperature_at_or_above_provider_limit", "host_busy"]


def test_sensors_are_mandatory_even_if_hosting_does_not_require_them() -> None:
    lenient = policy(benchmark_consent=True, allow_without_thermal_sensors=True)
    assert benchmark_refusals(policy=lenient, health=health(None), logical_cores=8) == [
        "thermal_monitoring_unavailable"
    ]
