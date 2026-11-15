"""Provider machines, their append-only scan history, and their marketplace listing."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from auren_api.domain.machine import ListingTier, MachineStatus
from auren_api.domain.money import Currency
from auren_api.domain.scan import ScanFailure, ScanStatus
from auren_api.models.base import Base, TimestampMixin


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class Machine(TimestampMixin, Base):
    __tablename__ = "machines"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_machines_owner_user_id_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[MachineStatus] = mapped_column(
        Enum(
            MachineStatus,
            name="machine_status",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=MachineStatus.REGISTERED.value,
    )
    # Set only by the platform's attestation of a canary confidential guest (not yet implemented).
    confidential_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MachineInventory(Base):
    """One scan report. Rows are never updated; the newest row is the current inventory."""

    __tablename__ = "machine_inventories"
    __table_args__ = (
        CheckConstraint("logical_cores > 0", name="cores_positive"),
        CheckConstraint("memory_total_bytes > 0", name="memory_positive"),
        CheckConstraint("storage_total_bytes > 0", name="storage_positive"),
        CheckConstraint("cpu_hashes_per_second > 0", name="cpu_speed_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    machine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("machine_scans.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Single-thread speed measured by the platform's own clock during the scan.
    cpu_hashes_per_second: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scan_elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    logical_cores: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gpu_memory_bytes: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    hardware_virtualization: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kvm_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidential_computing_flags: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class MachineListing(TimestampMixin, Base):
    """The current offer for a machine. Visible to buyers only while the machine is ``listed``."""

    __tablename__ = "machine_listings"
    __table_args__ = (
        CheckConstraint("price_per_hour_minor > 0", name="price_positive"),
        CheckConstraint("allocatable_cpu_cores > 0", name="cores_positive"),
        CheckConstraint("allocatable_memory_bytes > 0", name="memory_positive"),
        CheckConstraint("allocatable_storage_bytes > 0", name="storage_positive"),
        CheckConstraint("max_hosting_hours > 0", name="hosting_hours_positive"),
    )

    machine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("machines.id", ondelete="RESTRICT"), primary_key=True
    )
    tier: Mapped[ListingTier] = mapped_column(
        Enum(
            ListingTier,
            name="listing_tier",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    price_per_hour_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[Currency] = mapped_column(
        Enum(
            Currency,
            name="currency",
            native_enum=False,
            length=3,
            create_constraint=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    allocatable_cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False)
    allocatable_memory_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allocatable_gpu_indices: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    allocatable_storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_hosting_hours: Mapped[int] = mapped_column(Integer, nullable=False)


class MachineEnrollment(Base):
    """A one-time, short-lived token that lets an agent register its public key for a machine.

    Only the SHA-256 hash of the token is stored.
    """

    __tablename__ = "machine_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    machine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MachineCredential(Base):
    """The Ed25519 public key an enrolled agent signs its requests with."""

    __tablename__ = "machine_credentials"
    __table_args__ = (
        CheckConstraint("octet_length(public_key) = 32", name="public_key_length"),
        Index(
            "uq_machine_credentials_active",
            "machine_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    machine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MachineScan(Base):
    """A platform-issued scan session: challenge, deadlines and outcome. Never deleted."""

    __tablename__ = "machine_scans"
    __table_args__ = (
        CheckConstraint("cpu_iterations > 0", name="iterations_positive"),
        Index(
            "uq_machine_scans_open",
            "machine_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'claimed')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    machine_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        Enum(
            ScanStatus,
            name="scan_status",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    failure_reason: Mapped[ScanFailure | None] = mapped_column(
        Enum(
            ScanFailure,
            name="scan_failure",
            native_enum=False,
            length=24,
            create_constraint=True,
            values_callable=_enum_values,
        ),
        nullable=True,
    )
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    cpu_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
