"""The authenticated, authorized caller of a request."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from auren_api.domain.roles import Role


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    clerk_user_id: str
    roles: frozenset[Role]

    def has_any_role(self, roles: Iterable[Role]) -> bool:
        return not self.roles.isdisjoint(roles)
