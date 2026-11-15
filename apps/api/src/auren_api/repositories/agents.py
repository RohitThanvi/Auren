"""Persistence for machine enrollment, credentials and platform-run scans."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.domain.machine import MachineStatus
from auren_api.domain.scan import ScanFailure, ScanStatus
from auren_api.models.machine import (
    Machine,
    MachineCredential,
    MachineEnrollment,
    MachineScan,
)


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    machine_id: uuid.UUID
    owner_user_id: uuid.UUID
    public_key: bytes
    machine_status: MachineStatus


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- enrollment and credentials ---------------------------------------------------------

    async def create_enrollment(
        self, machine_id: uuid.UUID, token_hash: str, now: datetime, expires_at: datetime
    ) -> None:
        """Issue a token and revoke any earlier unused ones for the machine."""
        await self._session.execute(
            update(MachineEnrollment)
            .where(
                MachineEnrollment.machine_id == machine_id,
                MachineEnrollment.used_at.is_(None),
                MachineEnrollment.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        self._session.add(
            MachineEnrollment(machine_id=machine_id, token_hash=token_hash, expires_at=expires_at)
        )
        await self._session.flush()

    async def consume_enrollment(
        self, machine_id: uuid.UUID, token_hash: str, now: datetime
    ) -> bool:
        """Atomically mark a valid token as used. False if unknown, used, revoked or expired."""
        result = await self._session.execute(
            update(MachineEnrollment)
            .where(
                MachineEnrollment.machine_id == machine_id,
                MachineEnrollment.token_hash == token_hash,
                MachineEnrollment.used_at.is_(None),
                MachineEnrollment.revoked_at.is_(None),
                MachineEnrollment.expires_at > now,
            )
            .values(used_at=now)
            .returning(MachineEnrollment.id)
        )
        return result.scalar_one_or_none() is not None

    async def replace_credential(
        self, machine_id: uuid.UUID, public_key: bytes, now: datetime
    ) -> None:
        await self._session.execute(
            update(MachineCredential)
            .where(
                MachineCredential.machine_id == machine_id, MachineCredential.revoked_at.is_(None)
            )
            .values(revoked_at=now)
        )
        self._session.add(MachineCredential(machine_id=machine_id, public_key=public_key))
        await self._session.flush()

    async def identity(self, machine_id: uuid.UUID) -> AgentIdentity | None:
        result = await self._session.execute(
            select(Machine.owner_user_id, Machine.status, MachineCredential.public_key)
            .join(MachineCredential, MachineCredential.machine_id == Machine.id)
            .where(Machine.id == machine_id, MachineCredential.revoked_at.is_(None))
        )
        row = result.one_or_none()
        if row is None:
            return None
        return AgentIdentity(
            machine_id=machine_id,
            owner_user_id=row.owner_user_id,
            public_key=row.public_key,
            machine_status=row.status,
        )

    async def lock_machine(self, machine_id: uuid.UUID) -> Machine | None:
        result = await self._session.execute(
            select(Machine).where(Machine.id == machine_id).with_for_update()
        )
        return result.scalar_one_or_none()

    # --- scans ------------------------------------------------------------------------------

    async def fail_stale_open_scans(self, machine_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(MachineScan)
            .where(
                MachineScan.machine_id == machine_id,
                MachineScan.status.in_([ScanStatus.PENDING, ScanStatus.CLAIMED]),
                MachineScan.expires_at <= now,
            )
            .values(status=ScanStatus.FAILED, failure_reason=ScanFailure.EXPIRED)
        )

    async def create_scan(
        self, machine_id: uuid.UUID, challenge: bytes, cpu_iterations: int, expires_at: datetime
    ) -> MachineScan | None:
        """Insert a pending scan; None if the machine already has a live open scan."""
        result = await self._session.execute(
            pg_insert(MachineScan)
            .values(
                machine_id=machine_id,
                status=ScanStatus.PENDING,
                challenge=challenge,
                cpu_iterations=cpu_iterations,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(
                index_elements=[MachineScan.machine_id],
                index_where=text("status IN ('pending', 'claimed')"),
            )
            .returning(MachineScan.id)
        )
        scan_id = result.scalar_one_or_none()
        return None if scan_id is None else await self.get_scan(machine_id, scan_id)

    async def get_scan(
        self, machine_id: uuid.UUID, scan_id: uuid.UUID, *, for_update: bool = False
    ) -> MachineScan | None:
        statement = select(MachineScan).where(
            MachineScan.id == scan_id, MachineScan.machine_id == machine_id
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def oldest_pending_scan(self, machine_id: uuid.UUID, now: datetime) -> MachineScan | None:
        result = await self._session.execute(
            select(MachineScan)
            .where(
                MachineScan.machine_id == machine_id,
                MachineScan.status == ScanStatus.PENDING,
                MachineScan.expires_at > now,
            )
            .order_by(MachineScan.created_at)
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def scans_for(self, machine_ids: Collection[uuid.UUID]) -> list[MachineScan]:
        if not machine_ids:
            return []
        result = await self._session.execute(
            select(MachineScan)
            .where(MachineScan.machine_id.in_(machine_ids))
            .order_by(MachineScan.created_at.desc())
        )
        return list(result.scalars())
