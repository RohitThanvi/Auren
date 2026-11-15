"""Server-side price range computation. Providers choose a price inside this range."""

from dataclasses import dataclass

from auren_api.domain.errors import RuleViolationError
from auren_api.domain.inventory import Allocatable, InventorySnapshot
from auren_api.domain.machine import ListingTier
from auren_api.domain.money import Money

BYTES_PER_GIB = 1024**3
STORAGE_UNIT_BYTES = 100 * BYTES_PER_GIB


@dataclass(frozen=True, slots=True)
class RateCard:
    """Per-hour unit rates (all in the same currency) and the permitted deviation band."""

    cpu_core_hour: Money
    memory_gib_hour: Money
    gpu_vram_gib_hour: Money
    storage_100gib_hour: Money
    floor_bps: int
    ceiling_bps: int
    confidential_premium_bps: int


@dataclass(frozen=True, slots=True)
class PriceRange:
    base: Money
    floor: Money
    ceiling: Money

    def contains(self, price: Money) -> bool:
        return self.floor.amount_minor <= price.amount_minor <= self.ceiling.amount_minor


def price_range(
    rate_card: RateCard,
    snapshot: InventorySnapshot,
    allocatable: Allocatable,
    tier: ListingTier = ListingTier.STANDARD,
) -> PriceRange:
    """Compute the hourly price band for an offered allocation.

    Whole units only: partial GiB of memory/VRAM and partial 100 GiB storage blocks are not billed.
    GPUs are priced by the VRAM of the selected devices. The confidential tier's base price is the
    standard base price scaled by the configured premium.
    """
    vram_bytes = sum(snapshot.gpu_memory_bytes[i] for i in allocatable.gpu_indices)
    base = (
        rate_card.cpu_core_hour.times(allocatable.cpu_cores)
        + rate_card.memory_gib_hour.times(allocatable.memory_bytes // BYTES_PER_GIB)
        + rate_card.gpu_vram_gib_hour.times(vram_bytes // BYTES_PER_GIB)
        + rate_card.storage_100gib_hour.times(allocatable.storage_bytes // STORAGE_UNIT_BYTES)
    )
    if base.amount_minor <= 0:
        raise RuleViolationError(
            "allocation_exceeds_capacity", "The offered resources are too small to be priced."
        )
    if tier is ListingTier.CONFIDENTIAL:
        base = base.apply_basis_points(rate_card.confidential_premium_bps)
    floor = base.apply_basis_points(rate_card.floor_bps)
    floor = floor if floor.amount_minor >= 1 else Money(1, base.currency)
    ceiling = base.apply_basis_points(rate_card.ceiling_bps)
    return PriceRange(base=base, floor=floor, ceiling=ceiling)
