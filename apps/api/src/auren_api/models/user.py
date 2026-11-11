"""Platform users and their roles. Only the Clerk subject is stored: no email or name."""

import uuid

from sqlalchemy import Enum, ForeignKey, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auren_api.domain.roles import Role
from auren_api.models.base import Base, TimestampMixin


def _role_values(enum_class: type[Role]) -> list[str]:
    return [role.value for role in enum_class]


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    clerk_user_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    roles: Mapped[list["UserRole"]] = relationship(lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=_role_values,
        ),
        primary_key=True,
    )
