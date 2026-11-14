"""Persistence for provider machines, inventories and listings.

Every lookup of a machine is scoped by ``owner_user_id``: a machine that belongs to someone else is
indistinguishable from one that does not exist (no IDOR, no existence oracle).
"""

import uuid
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.domain.inventory import Allocatable, InventorySnapshot
from auren_api.domain.money import Money
from auren_api.models.machine import Machine, MachineInventory, MachineListing
from auren_api.models.user import User


class MachineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_owner(self, owner_user_id: uuid.UUID) -> None:
        """Serialise per-owner mutations (e.g. the machine count limit) with a row lock."""
        await self._session.execute(
            select(User.id).where(User.id == owner_user_id).with_for_update()
        )

    async def count_for_owner(self, owner_user_id: uuid.UUID) -> int:
        result = await self._session.scalar(
            select(func.count()).select_from(Machine).where(Machine.owner_user_id == owner_user_id)
        )
        return result or 0

    async def create(self, owner_user_id: uuid.UUID, name: str) -> Machine | None:
        """Insert a machine; returns None if the owner already has one with this name."""
        result = await self._session.execute(
            pg_insert(Machine)
            .values(owner_user_id=owner_user_id, name=name)
            .on_conflict_do_nothing(constraint="uq_machines_owner_user_id_name")
            .returning(Machine.id)
        )
        machine_id = result.scalar_one_or_none()
        if machine_id is None:
            return None
        return await self.get_owned(owner_user_id, machine_id)

    async def list_for_owner(self, owner_user_id: uuid.UUID) -> Sequence[Machine]:
        result = await self._session.execute(
            select(Machine)
            .where(Machine.owner_user_id == owner_user_id)
            .order_by(Machine.created_at, Machine.id)
        )
        return result.scalars().all()

    async def get_owned(
        self, owner_user_id: uuid.UUID, machine_id: uuid.UUID, *, for_update: bool = False
    ) -> Machine | None:
        statement = select(Machine).where(
            Machine.id == machine_id, Machine.owner_user_id == owner_user_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def add_inventory(
        self,
        machine_id: uuid.UUID,
        snapshot: InventorySnapshot,
        confidential_computing_flags: Collection[str],
        report: Mapping[str, Any],
    ) -> MachineInventory:
        inventory = MachineInventory(
            machine_id=machine_id,
            logical_cores=snapshot.logical_cores,
            memory_total_bytes=snapshot.memory_total_bytes,
            storage_total_bytes=snapshot.storage_total_bytes,
            gpu_memory_bytes=list(snapshot.gpu_memory_bytes),
            hardware_virtualization=snapshot.hardware_virtualization,
            kvm_available=snapshot.kvm_available,
            confidential_computing_flags=sorted(confidential_computing_flags),
            report=dict(report),
        )
        self._session.add(inventory)
        await self._session.flush()
        await self._session.refresh(inventory)
        return inventory

    async def latest_inventories(
        self, machine_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, MachineInventory]:
        if not machine_ids:
            return {}
        result = await self._session.execute(
            select(MachineInventory)
            .where(MachineInventory.machine_id.in_(machine_ids))
            .ext(distinct_on(MachineInventory.machine_id))
            .order_by(
                MachineInventory.machine_id,
                MachineInventory.created_at.desc(),
                MachineInventory.id.desc(),
            )
        )
        return {inventory.machine_id: inventory for inventory in result.scalars()}

    async def listings(self, machine_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, MachineListing]:
        if not machine_ids:
            return {}
        result = await self._session.execute(
            select(MachineListing).where(MachineListing.machine_id.in_(machine_ids))
        )
        return {listing.machine_id: listing for listing in result.scalars()}

    async def upsert_listing(
        self,
        machine_id: uuid.UUID,
        price: Money,
        allocatable: Allocatable,
        max_hosting_hours: int,
    ) -> None:
        values = {
            "price_per_hour_minor": price.amount_minor,
            "currency": price.currency,
            "allocatable_cpu_cores": allocatable.cpu_cores,
            "allocatable_memory_bytes": allocatable.memory_bytes,
            "allocatable_gpu_indices": list(allocatable.gpu_indices),
            "allocatable_storage_bytes": allocatable.storage_bytes,
            "max_hosting_hours": max_hosting_hours,
        }
        statement = pg_insert(MachineListing).values(machine_id=machine_id, **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[MachineListing.machine_id],
                set_={**values, "updated_at": func.now()},
            )
        )
