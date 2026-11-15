"""Agent-facing use cases: enrolment, scan challenges, and verified scan results.

The platform, not the provider, produces the hardware inventory: the provider only asks for a
scan; the enrolled agent claims a server-generated challenge and submits a signed result. The
CPU benchmark is verified by recomputation and timed by the server's clock.
"""

import asyncio
import hmac
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.auth.agent import is_acceptable_public_key
from auren_api.domain.clock import utcnow
from auren_api.domain.errors import (
    AuthenticationFailedError,
    ConflictViolationError,
    ResourceNotFoundError,
    RuleViolationError,
)
from auren_api.domain.inventory import InventorySnapshot
from auren_api.domain.machine import MachineStatus
from auren_api.domain.provider_policy import ProviderPolicy
from auren_api.domain.scan import ScanFailure, ScanStatus, cpu_chain, hashes_per_second
from auren_api.repositories.agents import AgentRepository
from auren_api.repositories.machines import MachineRepository
from auren_api.services.listing_rules import ListingRules, snapshot_from
from auren_api.services.provider import hash_enrollment_token

_INVALID_ENROLLMENT = "The enrollment token is invalid, expired or already used."


@dataclass(frozen=True, slots=True)
class ClaimedScan:
    scan_id: uuid.UUID
    challenge: bytes
    cpu_iterations: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    scan_id: uuid.UUID
    cpu_hashes_per_second: int
    listing_paused: bool


class AgentService:
    def __init__(
        self,
        session: AsyncSession,
        policy: ProviderPolicy,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._policy = policy
        self._clock = clock
        self._agents = AgentRepository(session)
        self._machines = MachineRepository(session)
        self._rules = ListingRules(policy)

    async def enroll(self, machine_id: uuid.UUID, token: str, public_key: bytes) -> None:
        """Bind the agent's public key to the machine using a one-time token."""
        if not is_acceptable_public_key(public_key):
            raise RuleViolationError(
                "invalid_public_key", "The public key is not an acceptable Ed25519 key."
            )
        machine = await self._agents.lock_machine(machine_id)
        if machine is None or machine.status is MachineStatus.WITHDRAWN:
            raise AuthenticationFailedError("invalid_enrollment", _INVALID_ENROLLMENT)
        consumed = await self._agents.consume_enrollment(
            machine_id, hash_enrollment_token(token), self._clock()
        )
        if not consumed:
            raise AuthenticationFailedError("invalid_enrollment", _INVALID_ENROLLMENT)
        await self._agents.replace_credential(machine_id, public_key, self._clock())
        await self._session.commit()

    async def claim_scan(self, machine_id: uuid.UUID) -> ClaimedScan:
        """Hand the agent the oldest pending challenge and start the server-side timer."""
        machine = await self._agents.lock_machine(machine_id)
        if machine is None or machine.status is MachineStatus.WITHDRAWN:
            raise ConflictViolationError("machine_withdrawn", "This machine has been withdrawn.")
        now = self._clock()
        scan = await self._agents.oldest_pending_scan(machine_id, now)
        if scan is None:
            raise ResourceNotFoundError("no_pending_scan", "No scan has been requested.")
        deadline = now + timedelta(seconds=self._policy.scan_result_deadline_seconds)
        scan.status = ScanStatus.CLAIMED
        scan.claimed_at = now
        scan.expires_at = min(scan.expires_at, deadline)
        await self._session.commit()
        return ClaimedScan(scan.id, scan.challenge, scan.cpu_iterations, scan.expires_at)

    async def submit_result(
        self,
        machine_id: uuid.UUID,
        scan_id: uuid.UUID,
        snapshot: InventorySnapshot,
        report: Mapping[str, Any],
        cpu_digest: bytes,
    ) -> ScanOutcome:
        """Verify and record a scan result. A scan can be answered exactly once."""
        received_at = self._clock()
        machine = await self._agents.lock_machine(machine_id)
        if machine is None:
            raise ResourceNotFoundError("scan_not_found", "Scan not found.")
        if machine.status is MachineStatus.WITHDRAWN:
            raise ConflictViolationError("machine_withdrawn", "This machine has been withdrawn.")
        scan = await self._agents.get_scan(machine_id, scan_id, for_update=True)
        if scan is None:
            raise ResourceNotFoundError("scan_not_found", "Scan not found.")
        if scan.status is not ScanStatus.CLAIMED or scan.claimed_at is None:
            raise ConflictViolationError("scan_not_claimed", "This scan is not awaiting a result.")
        if received_at > scan.expires_at:
            await self._fail(scan, ScanFailure.EXPIRED)
            raise ConflictViolationError("scan_expired", "The scan deadline has passed.")

        expected = await asyncio.to_thread(cpu_chain, scan.challenge, scan.cpu_iterations)
        if not hmac.compare_digest(expected, cpu_digest):
            await self._fail(scan, ScanFailure.BENCHMARK_MISMATCH)
            raise RuleViolationError("benchmark_mismatch", "The benchmark result is incorrect.")

        elapsed_ms = int((received_at - scan.claimed_at).total_seconds() * 1000)
        speed = hashes_per_second(scan.cpu_iterations, elapsed_ms)
        await self._machines.add_inventory(machine_id, scan.id, snapshot, report, speed, elapsed_ms)
        scan.status = ScanStatus.COMPLETED
        scan.completed_at = received_at

        paused = False
        if machine.status is MachineStatus.LISTED:
            listing = (await self._machines.listings([machine_id])).get(machine_id)
            if listing is None or not self._rules.is_listing_valid(
                snapshot_from((await self._machines.latest_inventories([machine_id]))[machine_id]),
                listing,
                confidential_verified=machine.confidential_verified_at is not None,
            ):
                machine.status = MachineStatus.PAUSED
                paused = True
        await self._session.commit()
        return ScanOutcome(scan_id=scan.id, cpu_hashes_per_second=speed, listing_paused=paused)

    async def _fail(self, scan: Any, reason: ScanFailure) -> None:
        scan.status = ScanStatus.FAILED
        scan.failure_reason = reason
        await self._session.commit()
