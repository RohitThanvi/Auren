import pytest

from auren_api.domain.errors import ConflictViolationError, RuleViolationError
from auren_api.domain.inventory import Allocatable, InventorySnapshot, check_allocatable
from auren_api.domain.machine import MachineStatus, require_transition
from auren_api.domain.money import Currency, Money
from auren_api.domain.pricing import BYTES_PER_GIB, RateCard, price_range

GIB = BYTES_PER_GIB
INR = Currency.INR
RATES = RateCard(
    cpu_core_hour=Money(200, INR),
    memory_gib_hour=Money(50, INR),
    gpu_vram_gib_hour=Money(300, INR),
    storage_100gib_hour=Money(100, INR),
    floor_bps=7000,
    ceiling_bps=15000,
)
SNAPSHOT = InventorySnapshot(
    logical_cores=32,
    memory_total_bytes=64 * GIB,
    storage_total_bytes=1000 * GIB,
    gpu_memory_bytes=(24 * GIB, 8 * GIB),
    hardware_virtualization=True,
    kvm_available=True,
)


def offer(cpu: int = 8, memory_gib: int = 16, gpus: tuple[int, ...] = (), storage_gib: int = 200):
    return Allocatable(cpu, memory_gib * GIB, gpus, storage_gib * GIB)


def test_price_range_is_computed_from_the_rate_card() -> None:
    band = price_range(RATES, SNAPSHOT, offer(gpus=(0,)))
    # 8*200 + 16*50 + 24*300 + 2*100
    assert band.base == Money(9800, INR)
    assert band.floor == Money(6860, INR)
    assert band.ceiling == Money(14700, INR)


def test_gpu_price_follows_the_selected_devices() -> None:
    big = price_range(RATES, SNAPSHOT, offer(gpus=(0,))).base.amount_minor
    small = price_range(RATES, SNAPSHOT, offer(gpus=(1,))).base.amount_minor
    both = price_range(RATES, SNAPSHOT, offer(gpus=(0, 1))).base.amount_minor
    assert big - small == (24 - 8) * 300
    assert both == big + (8 * 300)


def test_partial_units_are_not_billed() -> None:
    whole = price_range(RATES, SNAPSHOT, offer(memory_gib=16, storage_gib=100)).base
    partial = price_range(
        RATES,
        SNAPSHOT,
        Allocatable(8, 16 * GIB + GIB - 1, (), 100 * GIB + 100 * GIB - 1),
    ).base
    assert partial == whole


def test_range_contains_is_inclusive() -> None:
    band = price_range(RATES, SNAPSHOT, offer())
    assert band.contains(band.floor)
    assert band.contains(band.ceiling)
    assert not band.contains(Money(band.floor.amount_minor - 1, INR))
    assert not band.contains(Money(band.ceiling.amount_minor + 1, INR))


def test_floor_is_never_below_one_minor_unit() -> None:
    cheap = RateCard(Money(1, INR), Money(1, INR), Money(1, INR), Money(1, INR), 1, 15000)
    band = price_range(cheap, SNAPSHOT, Allocatable(1, GIB // 2, (), 1))
    assert band.floor.amount_minor >= 1


def test_unpriceable_offers_are_rejected() -> None:
    zero_rates = RateCard(Money(0, INR), Money(0, INR), Money(0, INR), Money(0, INR), 7000, 15000)
    with pytest.raises(RuleViolationError):
        price_range(zero_rates, SNAPSHOT, offer())


@pytest.mark.parametrize(
    "allocatable",
    [
        offer(cpu=29),  # cap is 28 (90% of 32)
        offer(memory_gib=58),  # cap is 57.6 GiB
        offer(storage_gib=901),
        offer(cpu=0),
        offer(gpus=(2,)),
        offer(gpus=(-1,)),
        offer(gpus=(0, 0)),
        Allocatable(1, 0, (), GIB),
        Allocatable(1, GIB, (), 0),
    ],
)
def test_allocations_beyond_the_machine_are_rejected(allocatable: Allocatable) -> None:
    with pytest.raises(RuleViolationError) as caught:
        check_allocatable(SNAPSHOT, allocatable, 9000)
    assert caught.value.code == "allocation_exceeds_capacity"


def test_allocation_at_the_cap_is_accepted() -> None:
    check_allocatable(SNAPSHOT, Allocatable(28, 57 * GIB, (0, 1), 900 * GIB), 9000)


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (MachineStatus.REGISTERED, MachineStatus.LISTED, True),
        (MachineStatus.REGISTERED, MachineStatus.PAUSED, False),
        (MachineStatus.LISTED, MachineStatus.LISTED, True),
        (MachineStatus.LISTED, MachineStatus.PAUSED, True),
        (MachineStatus.PAUSED, MachineStatus.PAUSED, False),
        (MachineStatus.PAUSED, MachineStatus.LISTED, True),
        (MachineStatus.WITHDRAWN, MachineStatus.LISTED, False),
        (MachineStatus.WITHDRAWN, MachineStatus.WITHDRAWN, False),
        (MachineStatus.LISTED, MachineStatus.WITHDRAWN, True),
    ],
)
def test_state_transitions(current: MachineStatus, target: MachineStatus, allowed: bool) -> None:
    if allowed:
        require_transition(current, target)
    else:
        with pytest.raises(ConflictViolationError):
            require_transition(current, target)


def test_money_times() -> None:
    assert Money(25, INR).times(4) == Money(100, INR)
    with pytest.raises(ValueError, match="non-negative"):
        Money(25, INR).times(-1)
