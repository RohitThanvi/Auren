"""User application service. Owns the transaction boundary for user provisioning."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.domain.roles import Role
from auren_api.repositories.users import UserRepository

DEFAULT_ROLES = frozenset({Role.BUYER})


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: uuid.UUID
    clerk_user_id: str
    roles: frozenset[Role]


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def get_or_provision(self, clerk_user_id: str) -> UserAccount:
        """Return the account for a verified Clerk subject, creating it with default roles."""
        user = await self._users.get_by_clerk_user_id(clerk_user_id)
        if user is None:
            await self._users.create_if_absent(clerk_user_id, DEFAULT_ROLES)
            await self._session.commit()
            user = await self._users.get_by_clerk_user_id(clerk_user_id)
        if user is None:
            raise RuntimeError("user missing immediately after provisioning")
        return UserAccount(
            id=user.id,
            clerk_user_id=user.clerk_user_id,
            roles=frozenset(user_role.role for user_role in user.roles),
        )
