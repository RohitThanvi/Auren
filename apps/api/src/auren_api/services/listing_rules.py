"""Rules deciding what a machine may offer, shared by the provider and agent services."""

from auren_api.domain.errors import RuleViolationError
from auren_api.domain.inventory import (
    Allocatable,
    InventorySnapshot,
    check_allocatable,
    check_tier,
)
from auren_api.domain.machine import ListingTier
from auren_api.domain.money import Money
from auren_api.domain.pricing import PriceRange, price_range
from auren_api.domain.provider_policy import ProviderPolicy
from auren_api.models.machine import MachineInventory, MachineListing


def snapshot_from(inventory: MachineInventory) -> InventorySnapshot:
    return InventorySnapshot(
        logical_cores=inventory.logical_cores,
        memory_total_bytes=inventory.memory_total_bytes,
        storage_total_bytes=inventory.storage_total_bytes,
        gpu_memory_bytes=tuple(inventory.gpu_memory_bytes),
        hardware_virtualization=inventory.hardware_virtualization,
        kvm_available=inventory.kvm_available,
        confidential_computing_flags=tuple(inventory.confidential_computing_flags),
    )


def allocatable_from(listing: MachineListing) -> Allocatable:
    return Allocatable(
        cpu_cores=listing.allocatable_cpu_cores,
        memory_bytes=listing.allocatable_memory_bytes,
        gpu_indices=tuple(listing.allocatable_gpu_indices),
        storage_bytes=listing.allocatable_storage_bytes,
    )


class ListingRules:
    def __init__(self, policy: ProviderPolicy) -> None:
        self._policy = policy

    def price_band(
        self,
        snapshot: InventorySnapshot,
        allocatable: Allocatable,
        tier: ListingTier,
        *,
        confidential_verified: bool,
    ) -> PriceRange:
        """The permitted price band, or ``RuleViolationError`` if the offer is not allowed."""
        check_allocatable(snapshot, allocatable, self._policy.max_allocatable_bps)
        check_tier(tier, snapshot, allocatable, confidential_verified=confidential_verified)
        return price_range(self._policy.rate_card, snapshot, allocatable, tier)

    def assert_listing_valid(
        self,
        snapshot: InventorySnapshot,
        listing: MachineListing,
        *,
        confidential_verified: bool,
    ) -> None:
        band = self.price_band(
            snapshot,
            allocatable_from(listing),
            listing.tier,
            confidential_verified=confidential_verified,
        )
        if not band.contains(Money(listing.price_per_hour_minor, listing.currency)):
            raise RuleViolationError(
                "price_out_of_range", "The listed price is outside the current price range."
            )

    def is_listing_valid(
        self,
        snapshot: InventorySnapshot,
        listing: MachineListing,
        *,
        confidential_verified: bool,
    ) -> bool:
        try:
            self.assert_listing_valid(
                snapshot, listing, confidential_verified=confidential_verified
            )
        except RuleViolationError:
            return False
        return True
