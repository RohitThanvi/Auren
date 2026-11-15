"""Provider use cases: machines, enrolment, scan requests, price range, listing, lifecycle.

Services own transaction boundaries. Machine mutations lock the machine row, so concurrent
requests on the same machine are serialised and state transitions cannot interleave.
Providers never submit hardware facts: those come only from platform-run scans (see AgentService).
"""

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.domain.clock import utcnow
from auren_api.domain.errors import (
    ConflictViolationError,
    ResourceNotFoundError,
    RuleViolationError,
)
from auren_api.domain.inventory import Allocatable, InventorySnapshot
from auren_api.domain.machine import ListingTier, MachineStatus, require_transition
from auren_api.domain.money import Money
from auren_api.domain.pricing import PriceRange
from auren_api.domain.provider_policy import ProviderPolicy
from auren_api.domain.scan import ScanStatus, new_challenge
from auren_api.models.machine import Machine, MachineInventory, MachineListing, MachineScan
from auren_api.repositories.agents import AgentRepository
from auren_api.repositories.machines import MachineRepository
from auren_api.services.listing_rules import ListingRules, allocatable_from, snapshot_from

EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class InventoryView:
    id: uuid.UUID
    scan_id: uuid.UUID
    received_at: datetime
    cpu_hashes_per_second: int
    logical_cores: int
    memory_total_bytes: int
    storage_total_bytes: int
    gpu_count: int
    hardware_virtualization: bool
    kvm_available: bool
    confidential_computing_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListingView:
    tier: ListingTier
    price: Money
    allocatable: Allocatable
    max_hosting_hours: int


@dataclass(frozen=True, slots=True)
class MachineView:
    id: uuid.UUID
    name: str
    status: MachineStatus
    created_at: datetime
    confidential_verified: bool
    inventory: InventoryView | None
    listing: ListingView | None


@dataclass(frozen=True, slots=True)
class ScanView:
    id: uuid.UUID
    status: str
    failure_reason: str | None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    cpu_hashes_per_second: int | None


@dataclass(frozen=True, slots=True)
class EnrollmentIssued:
    token: str
    expires_at: datetime


def inventory_view(inventory: MachineInventory) -> InventoryView:
    return InventoryView(
        id=inventory.id,
        scan_id=inventory.scan_id,
        received_at=inventory.created_at,
        cpu_hashes_per_second=inventory.cpu_hashes_per_second,
        logical_cores=inventory.logical_cores,
        memory_total_bytes=inventory.memory_total_bytes,
        storage_total_bytes=inventory.storage_total_bytes,
        gpu_count=len(inventory.gpu_memory_bytes),
        hardware_virtualization=inventory.hardware_virtualization,
        kvm_available=inventory.kvm_available,
        confidential_computing_flags=tuple(inventory.confidential_computing_flags),
    )


def _listing_view(listing: MachineListing) -> ListingView:
    return ListingView(
        tier=listing.tier,
        price=Money(listing.price_per_hour_minor, listing.currency),
        allocatable=allocatable_from(listing),
        max_hosting_hours=listing.max_hosting_hours,
    )


def hash_enrollment_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ProviderService:
    def __init__(
        self,
        session: AsyncSession,
        policy: ProviderPolicy,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._policy = policy
        self._clock = clock
        self._machines = MachineRepository(session)
        self._agents = AgentRepository(session)
        self._rules = ListingRules(policy)

    # --- machines ---------------------------------------------------------------------------

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

    # --- enrolment and platform scans -------------------------------------------------------

    async def create_enrollment(
        self, owner_id: uuid.UUID, machine_id: uuid.UUID
    ) -> EnrollmentIssued:
        """Issue a one-time token for installing the agent. The token is returned only once."""
        machine = await self._require_machine(owner_id, machine_id, for_update=True)
        self._require_not_withdrawn(machine)
        now = self._clock()
        expires_at = now + timedelta(seconds=self._policy.enrollment_ttl_seconds)
        token = secrets.token_urlsafe(32)
        await self._agents.create_enrollment(
            machine.id, hash_enrollment_token(token), now, expires_at
        )
        await self._session.commit()
        return EnrollmentIssued(token=token, expires_at=expires_at)

    async def request_scan(self, owner_id: uuid.UUID, machine_id: uuid.UUID) -> ScanView:
        """Ask the machine's enrolled agent to run a platform scan."""
        machine = await self._require_machine(owner_id, machine_id, for_update=True)
        self._require_not_withdrawn(machine)
        if await self._agents.identity(machine.id) is None:
            raise RuleViolationError(
                "agent_not_enrolled", "Install and enrol the Auren agent on this machine first."
            )
        now = self._clock()
        await self._agents.fail_stale_open_scans(machine.id, now)
        scan = await self._agents.create_scan(
            machine.id,
            new_challenge(),
            self._policy.scan_cpu_iterations,
            now + timedelta(seconds=self._policy.scan_ttl_seconds),
        )
        if scan is None:
            raise ConflictViolationError(
                "scan_in_progress", "A scan is already pending or running for this machine."
            )
        await self._session.commit()
        return self._scan_view(scan, None, now)

    async def get_scan(
        self, owner_id: uuid.UUID, machine_id: uuid.UUID, scan_id: uuid.UUID
    ) -> ScanView:
        machine = await self._require_machine(owner_id, machine_id)
        scan = await self._agents.get_scan(machine.id, scan_id)
        if scan is None:
            raise ResourceNotFoundError("scan_not_found", "Scan not found.")
        inventory = await self._machines.inventory_for_scan(scan.id)
        return self._scan_view(scan, inventory, self._clock())

    # --- pricing, listing, lifecycle --------------------------------------------------------

    async def price_range(
        self,
        owner_id: uuid.UUID,
        machine_id: uuid.UUID,
        allocatable: Allocatable,
        tier: ListingTier,
    ) -> PriceRange:
        machine = await self._require_machine(owner_id, machine_id)
        snapshot = await self._require_snapshot(machine.id)
        return self._rules.price_band(
            snapshot,
            allocatable,
            tier,
            confidential_verified=machine.confidential_verified_at is not None,
        )

    async def set_listing(
        self,
        owner_id: uuid.UUID,
        machine_id: uuid.UUID,
        tier: ListingTier,
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
        band = self._rules.price_band(
            snapshot,
            allocatable,
            tier,
            confidential_verified=machine.confidential_verified_at is not None,
        )
        price = Money(price_per_hour_minor, band.base.currency)
        if not band.contains(price):
            raise RuleViolationError(
                "price_out_of_range",
                f"Price must be between {band.floor.amount_minor} and "
                f"{band.ceiling.amount_minor} {band.base.currency.value} minor units per hour.",
            )
        await self._machines.upsert_listing(machine.id, tier, price, allocatable, max_hosting_hours)
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
        self._rules.assert_listing_valid(
            snapshot, listing, confidential_verified=machine.confidential_verified_at is not None
        )
        machine.status = MachineStatus.LISTED
        await self._session.commit()
        return await self.get_machine(owner_id, machine_id)

    # --- helpers ----------------------------------------------------------------------------

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

    @staticmethod
    def _require_not_withdrawn(machine: Machine) -> None:
        if machine.status is MachineStatus.WITHDRAWN:
            raise ConflictViolationError("machine_withdrawn", "This machine has been withdrawn.")

    async def _require_snapshot(self, machine_id: uuid.UUID) -> InventorySnapshot:
        inventory = (await self._machines.latest_inventories([machine_id])).get(machine_id)
        if inventory is None:
            raise RuleViolationError(
                "inventory_required", "The platform must scan this machine first."
            )
        return snapshot_from(inventory)

    @staticmethod
    def _scan_view(
        scan: MachineScan, inventory: MachineInventory | None, now: datetime
    ) -> ScanView:
        open_and_late = (
            scan.status in {ScanStatus.PENDING, ScanStatus.CLAIMED} and scan.expires_at <= now
        )
        return ScanView(
            id=scan.id,
            status=EXPIRED if open_and_late else scan.status.value,
            failure_reason=scan.failure_reason.value if scan.failure_reason else None,
            created_at=scan.created_at,
            expires_at=scan.expires_at,
            completed_at=scan.completed_at,
            cpu_hashes_per_second=inventory.cpu_hashes_per_second if inventory else None,
        )

    @staticmethod
    def _view(
        machine: Machine, inventory: MachineInventory | None, listing: MachineListing | None
    ) -> MachineView:
        return MachineView(
            id=machine.id,
            name=machine.name,
            status=machine.status,
            created_at=machine.created_at,
            confidential_verified=machine.confidential_verified_at is not None,
            inventory=inventory_view(inventory) if inventory else None,
            listing=_listing_view(listing) if listing else None,
        )
