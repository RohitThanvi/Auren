"""Persistence for users and roles."""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.domain.roles import Role
from auren_api.models.user import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_clerk_user_id(self, clerk_user_id: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        )
        return result.scalar_one_or_none()

    async def create_if_absent(self, clerk_user_id: str, roles: Collection[Role]) -> bool:
        """Insert the user and roles unless the Clerk subject exists. Safe under concurrency.

        Returns True if this call created the user. Does not commit.
        """
        result = await self._session.execute(
            pg_insert(User)
            .values(clerk_user_id=clerk_user_id)
            .on_conflict_do_nothing(index_elements=[User.clerk_user_id])
            .returning(User.id)
        )
        user_id = result.scalar_one_or_none()
        if user_id is None:
            return False
        self._session.add_all(UserRole(user_id=user_id, role=role) for role in roles)
        await self._session.flush()
        return True
