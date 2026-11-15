"""provider machines scans and agent credentials

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "registered",
                "listed",
                "paused",
                "withdrawn",
                name="machine_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="registered",
            nullable=False,
        ),
        sa.Column("confidential_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_machines_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machines")),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_machines_owner_user_id_name"),
    )
    op.create_index(op.f("ix_machines_owner_user_id"), "machines", ["owner_user_id"], unique=False)
    op.create_table(
        "machine_credentials",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(public_key) = 32", name=op.f("ck_machine_credentials_public_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_machine_credentials_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machine_credentials")),
    )
    op.create_index(
        "uq_machine_credentials_active",
        "machine_credentials",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "machine_enrollments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_machine_enrollments_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machine_enrollments")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_machine_enrollments_token_hash")),
    )
    op.create_index(
        op.f("ix_machine_enrollments_machine_id"),
        "machine_enrollments",
        ["machine_id"],
        unique=False,
    )
    op.create_table(
        "machine_listings",
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                "standard",
                "confidential",
                name="listing_tier",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("price_per_hour_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "currency",
            sa.Enum("INR", name="currency", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("allocatable_cpu_cores", sa.Integer(), nullable=False),
        sa.Column("allocatable_memory_bytes", sa.BigInteger(), nullable=False),
        sa.Column("allocatable_gpu_indices", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("allocatable_storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_hosting_hours", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "allocatable_cpu_cores > 0", name=op.f("ck_machine_listings_cores_positive")
        ),
        sa.CheckConstraint(
            "allocatable_memory_bytes > 0", name=op.f("ck_machine_listings_memory_positive")
        ),
        sa.CheckConstraint(
            "allocatable_storage_bytes > 0", name=op.f("ck_machine_listings_storage_positive")
        ),
        sa.CheckConstraint(
            "max_hosting_hours > 0", name=op.f("ck_machine_listings_hosting_hours_positive")
        ),
        sa.CheckConstraint(
            "price_per_hour_minor > 0", name=op.f("ck_machine_listings_price_positive")
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_machine_listings_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("machine_id", name=op.f("pk_machine_listings")),
    )
    op.create_table(
        "machine_scans",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "claimed",
                "completed",
                "failed",
                name="scan_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "failure_reason",
            sa.Enum(
                "expired",
                "benchmark_mismatch",
                name="scan_failure",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=True,
        ),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("cpu_iterations", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cpu_iterations > 0", name=op.f("ck_machine_scans_iterations_positive")),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_machine_scans_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machine_scans")),
    )
    op.create_index(
        op.f("ix_machine_scans_machine_id"), "machine_scans", ["machine_id"], unique=False
    )
    op.create_index(
        "uq_machine_scans_open",
        "machine_scans",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'claimed')"),
    )
    op.create_table(
        "machine_inventories",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cpu_hashes_per_second", sa.BigInteger(), nullable=False),
        sa.Column("scan_elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("logical_cores", sa.Integer(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("gpu_memory_bytes", sa.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("hardware_virtualization", sa.Boolean(), nullable=False),
        sa.Column("kvm_available", sa.Boolean(), nullable=False),
        sa.Column("confidential_computing_flags", sa.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "cpu_hashes_per_second > 0", name=op.f("ck_machine_inventories_cpu_speed_positive")
        ),
        sa.CheckConstraint("logical_cores > 0", name=op.f("ck_machine_inventories_cores_positive")),
        sa.CheckConstraint(
            "memory_total_bytes > 0", name=op.f("ck_machine_inventories_memory_positive")
        ),
        sa.CheckConstraint(
            "storage_total_bytes > 0", name=op.f("ck_machine_inventories_storage_positive")
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_machine_inventories_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["machine_scans.id"],
            name=op.f("fk_machine_inventories_scan_id_machine_scans"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machine_inventories")),
        sa.UniqueConstraint("scan_id", name=op.f("uq_machine_inventories_scan_id")),
    )
    op.create_index(
        op.f("ix_machine_inventories_machine_id"),
        "machine_inventories",
        ["machine_id"],
        unique=False,
    )
    op.add_column(
        "user_roles",
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_roles", "granted_at")
    op.drop_index(op.f("ix_machine_inventories_machine_id"), table_name="machine_inventories")
    op.drop_table("machine_inventories")
    op.drop_index(
        "uq_machine_scans_open",
        table_name="machine_scans",
        postgresql_where=sa.text("status IN ('pending', 'claimed')"),
    )
    op.drop_index(op.f("ix_machine_scans_machine_id"), table_name="machine_scans")
    op.drop_table("machine_scans")
    op.drop_table("machine_listings")
    op.drop_index(op.f("ix_machine_enrollments_machine_id"), table_name="machine_enrollments")
    op.drop_table("machine_enrollments")
    op.drop_index(
        "uq_machine_credentials_active",
        table_name="machine_credentials",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("machine_credentials")
    op.drop_index(op.f("ix_machines_owner_user_id"), table_name="machines")
    op.drop_table("machines")
