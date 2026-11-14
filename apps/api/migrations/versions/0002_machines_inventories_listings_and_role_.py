"""machines inventories listings and role grant time

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
        "machine_inventories",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("logical_cores", sa.Integer(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("gpu_memory_bytes", sa.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("hardware_virtualization", sa.Boolean(), nullable=False),
        sa.Column("kvm_available", sa.Boolean(), nullable=False),
        sa.Column("confidential_computing_flags", sa.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machine_inventories")),
    )
    op.create_index(
        op.f("ix_machine_inventories_machine_id"),
        "machine_inventories",
        ["machine_id"],
        unique=False,
    )
    op.create_table(
        "machine_listings",
        sa.Column("machine_id", sa.Uuid(), nullable=False),
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
    op.drop_table("machine_listings")
    op.drop_index(op.f("ix_machine_inventories_machine_id"), table_name="machine_inventories")
    op.drop_table("machine_inventories")
    op.drop_index(op.f("ix_machines_owner_user_id"), table_name="machines")
    op.drop_table("machines")
