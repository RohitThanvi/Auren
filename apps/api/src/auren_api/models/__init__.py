"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from auren_api.models.base import Base
from auren_api.models.machine import (
    Machine,
    MachineCredential,
    MachineEnrollment,
    MachineInventory,
    MachineListing,
    MachineScan,
)
from auren_api.models.user import User, UserRole

__all__ = [
    "Base",
    "Machine",
    "MachineCredential",
    "MachineEnrollment",
    "MachineInventory",
    "MachineListing",
    "MachineScan",
    "User",
    "UserRole",
]
