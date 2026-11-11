"""Platform roles. Authorization is derived from stored roles, never from token claims."""

from enum import StrEnum


class Role(StrEnum):
    BUYER = "buyer"
    PROVIDER = "provider"
    ADMIN = "admin"
