"""Provider use cases: machine registration, scan intake, price range, listing, lifecycle.

Services own transaction boundaries. Machine mutations lock the machine row, so concurrent
requests on the same machine are serialised and state transitions cannot interleave.
"""

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.domain.errors import (
    ConflictViolationError,
    ResourceNotFoundError,
    RuleViolationError,
)
from auren_api.domain.inventory import Allocatable, InventorySnapshot, check_allocatable
from auren_api.domain.machine import MachineStatus, require_transition
from auren_api.domain.money import Money
from auren_api.domain.pricing import PriceRange, price_range
from auren_api.domain.provider_policy import ProviderPolicy
from auren_api.models.machine import Machine, MachineInventory, MachineListing
from auren_api.repositories.machines import MachineRepository


@dataclass(frozen=True, slots=True)
class InventoryView:
    id: uuid.UUID
    received_at: datetime
    logical_cores: int
    memory_total_bytes: int
    storage_total_bytes: int
    gpu_count: int
    hardware_virtualization: bool
    kvm_available: bool
    confidential_computing_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListingView:
    price: Money
    allocatable: Allocatable
    max_hosting_hours: int


@dataclass(frozen=True, slots=True)
class MachineView:
    id: uuid.UUID
    name: str
    status: MachineStatus
    created_at: datetime
    inventory: InventoryView | None
    listing: ListingView | None


@dataclass(frozen=True, slots=True)
class InventoryAccepted:
    inventory: InventoryView
    listing_paused: bool


def _snapshot(inventory: MachineInventory) -> InventorySnapshot:
    return InventorySnapshot(
        logical_cores=inventory.logical_cores,
        memory_total_bytes=inventory.memory_total_bytes,
        storage_total_bytes=inventory.storage_total_bytes,
        gpu_memory_bytes=tuple(inventory.gpu_memory_bytes),
        hardware_virtualization=inventory.hardware_virtualization,
        kvm_available=inventory.kvm_available,
    )


def _inventory_view(inventory: MachineInventory) -> InventoryView:
    return InventoryView(
        id=inventory.id,
        received_at=inventory.created_at,
        logical_cores=inventory.logical_cores,
        memory_total_bytes=inventory.memory_total_bytes,
        storage_total_bytes=inventory.storage_total_bytes,
        gpu_count=len(inventory.gpu_memory_bytes),
        hardware_virtualization=inventory.hardware_virtualization,
        kvm_available=inventory.kvm_available,
        confidential_computing_flags=tuple(inventory.confidential_computing_flags),
    )


def _allocatable(listing: MachineListing) -> Allocatable:
    return Allocatable(
        cpu_cores=listing.allocatable_cpu_cores,
        memory_bytes=listing.allocatable_memory_bytes,
        gpu_indices=tuple(listing.allocatable_gpu_indices),
        storage_bytes=listing.allocatable_storage_bytes,
    )


def _listing_view(listing: MachineListing) -> ListingView:
    return ListingView(
        price=Money(listing.price_per_hour_minor, listing.currency),
        allocatable=_allocatable(listing),
        max_hosting_hours=listing.max_hosting_hours,
    )


class ProviderService:
    def __init__(self, session: AsyncSession, policy: ProviderPolicy) -> None:
        self._session = session
        self._policy = policy
        self._machines = MachineRepository(session)

    async def create_machine(self, owner_id: uuid.UUID, name: str) -> MachineView:
        await self._machines.lock_owner(owner_id)
        if await self._machines.count_for_owner(owner_id) >= self._policy.max_machines:
            raise ConflictViolationError(
                "machine_limit_reached",
                f"A provider may register at most {self._policy.max_machines} machines.",
            )
        machine = await self._machines.create(owner_id, name)
        if machine is None:
            raise ConflictViolationError(
                "machine_name_taken", "You already have a machine with this name."
            )
        await self._session.commit()
        return self._view(machine, None, None)

    async def list_machines(self, owner_id: uuid.UUID) -> list[MachineView]:
        machines = await self._machines.list_for_owner(owner_id)
        ids = [machine.id for machine in machines]
        inventories = await self._machines.latest_inventories(ids)
        listings = await self._machines.listings(ids)
        return [
            self._view(machine, inventories.get(machine.id), listings.get(machine.id))
            for machine in machines
        ]

    async def get_machine(self, owner_id: uuid.UUID, machine_id: uuid.UUID) -> MachineView:
        machine = await self._require_machine(owner_id, machine_id)
        inventory = (await self._machines.latest_inventories([machine.id])).get(machine.id)
        listing = (await self._machines.listings([machine.id])).get(machine.id)
        return self._view(machine, inventory, listing)

    async def submit_inventory(
        self,
        owner_id: uuid.UUID,
        machine_id: uuid.UUID,
        snapshot: InventorySnapshot,
        confidential_computing_flags: Collection[str],
        report: Mapping[str, Any],
    ) -> InventoryAccepted:
        machine = await self._require_machine(owner_id, machine_id, for_update=True)
        if machine.status is MachineStatus.WITHDRAWN:
            raise ConflictViolationError("machine_withdrawn", "This machine has been withdrawn.")
        inventory = await self._machines.add_inventory(
            machine.id, snapshot, confidential_computing_flags, report
        )
        paused = False
        if machine.status is MachineStatus.LISTED:
            listing = (await self._machines.listings([machine.id])).get(machine.id)
            if listing is None or not self._listing_is_valid(snapshot, listing):
                machine.status = MachineStatus.PAUSED
                paused = True
        await self._session.commit()
        return InventoryAccepted(inventory=_inventory_view(inventory), listing_paused=paused)

    async def price_range(
        self, owner_id: uuid.UUID, machine_id: uuid.UUID, allocatable: Allocatable
    ) -> PriceRange:
        machine = await self._require_machine(owner_id, machine_id)
        snapshot = await self._require_snapshot(machine.id)
        return self._range_for(snapshot, allocatable)

    async def set_listing(
        self,
        owner_id: uuid.UUID,
        machine_id: uuid.UUID,
        allocatable: Allocatable,
        price_per_hour_minor: int,
        max_hosting_hours: int,
    ) -> MachineView:
        machine = await self._require_machine(owner_id, machine_id, for_update=True)
        require_transition(machine.status, MachineStatus.LISTED)
        if max_hosting_hours > self._policy.max_hosting_hours:
            raise RuleViolationError(
                "max_hosting_hours_exceeded",
                f"Maximum hosting duration is {self._policy.max_hosting_hours} hours.",
            )
        snapshot = await self._require_snapshot(machine.id)
        band = self._range_for(snapshot, allocatable)
        price = Money(price_per_hour_minor, band.base.currency)
        if not band.contains(price):
            raise RuleViolationError(
                "price_out_of_range",
                f"Price must be between {band.floor.amount_minor} and "
                f"{band.ceiling.amount_minor} {band.base.currency.value} minor units per hour.",
            )
        await self._machines.upsert_listing(machine.id, price, allocatable, max_hosting_hours)
        machine.status = MachineStatus.LISTED
        await self._session.commit()
        return await self.get_machine(owner_id, machine_id)

    async def pause(self, owner_id: uuid.UUID, machine_id: uuid.UUID) -> MachineView:
        return await self._transition(owner_id, machine_id, MachineStatus.PAUSED)

    async def withdraw(self, owner_id: uuid.UUID, machine_id: uuid.UUID) -> MachineView:
        return await self._transition(owner_id, machine_id, MachineStatus.WITHDRAWN)

    async def resume(self, owner_id: uuid.UUID, machine_id: uuid.UUID) -> MachineView:
        machine = await self._require_machine(owner_id, machine_id, for_update=True)
        require_transition(machine.status, MachineStatus.LISTED)
        listing = (await self._machines.listings([machine.id])).get(machine.id)
        if listing is None:
            raise RuleViolationError("listing_required", "Create a listing before resuming.")
        snapshot = await self._require_snapshot(machine.id)
        self._assert_listing_valid(snapshot, listing)
        machine.status = MachineStatus.LISTED
        await self._session.commit()
        return await self.get_machine(owner_id, machine_id)

    async def _transition(
        self, owner_id: uuid.UUID, machine_id: uuid.UUID, target: MachineStatus
    ) -> MachineView:
        machine = await self._require_machine(owner_id, machine_id, for_update=True)
        require_transition(machine.status, target)
        machine.status = target
        await self._session.commit()
        return await self.get_machine(owner_id, machine_id)

    async def _require_machine(
        self, owner_id: uuid.UUID, machine_id: uuid.UUID, *, for_update: bool = False
    ) -> Machine:
        machine = await self._machines.get_owned(owner_id, machine_id, for_update=for_update)
        if machine is None:
            raise ResourceNotFoundError("machine_not_found", "Machine not found.")
        return machine

    async def _require_snapshot(self, machine_id: uuid.UUID) -> InventorySnapshot:
        inventory = (await self._machines.latest_inventories([machine_id])).get(machine_id)
        if inventory is None:
            raise RuleViolationError(
                "inventory_required", "Submit a hardware scan for this machine first."
            )
        return _snapshot(inventory)

    def _range_for(self, snapshot: InventorySnapshot, allocatable: Allocatable) -> PriceRange:
        check_allocatable(snapshot, allocatable, self._policy.max_allocatable_bps)
        return price_range(self._policy.rate_card, snapshot, allocatable)

    def _assert_listing_valid(self, snapshot: InventorySnapshot, listing: MachineListing) -> None:
        band = self._range_for(snapshot, _allocatable(listing))
        if not band.contains(Money(listing.price_per_hour_minor, listing.currency)):
            raise RuleViolationError(
                "price_out_of_range", "The listed price is outside the current price range."
            )

    def _listing_is_valid(self, snapshot: InventorySnapshot, listing: MachineListing) -> bool:
        try:
            self._assert_listing_valid(snapshot, listing)
        except RuleViolationError:
            return False
        return True

    @staticmethod
    def _view(
        machine: Machine, inventory: MachineInventory | None, listing: MachineListing | None
    ) -> MachineView:
        return MachineView(
            id=machine.id,
            name=machine.name,
            status=machine.status,
            created_at=machine.created_at,
            inventory=_inventory_view(inventory) if inventory else None,
            listing=_listing_view(listing) if listing else None,
        )
