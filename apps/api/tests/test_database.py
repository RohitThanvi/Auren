"""Schema-level guarantees enforced by PostgreSQL, independent of application code."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import ClientHandle


async def _insert_user(handle: ClientHandle, clerk_id: str) -> uuid.UUID:
    async with handle.app.state.container.engine.begin() as connection:
        result = await connection.execute(
            text("INSERT INTO users (clerk_user_id) VALUES (:c) RETURNING id"), {"c": clerk_id}
        )
        return result.scalar_one()


async def test_clerk_subject_is_unique(api: ClientHandle) -> None:
    await _insert_user(api, "user_dup")
    with pytest.raises(IntegrityError):
        await _insert_user(api, "user_dup")


async def test_invalid_role_values_are_rejected(api: ClientHandle) -> None:
    user_id = await _insert_user(api, "user_role_check")
    with pytest.raises(IntegrityError):
        async with api.app.state.container.engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES (:u, 'superuser')"),
                {"u": user_id},
            )


async def test_user_roles_require_an_existing_user(api: ClientHandle) -> None:
    with pytest.raises(IntegrityError):
        async with api.app.state.container.engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES (:u, 'buyer')"),
                {"u": uuid.uuid4()},
            )


async def test_users_with_roles_cannot_be_deleted(api: ClientHandle) -> None:
    user_id = await _insert_user(api, "user_keep")
    async with api.app.state.container.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO user_roles (user_id, role) VALUES (:u, 'buyer')"), {"u": user_id}
        )
    with pytest.raises(IntegrityError):
        async with api.app.state.container.engine.begin() as connection:
            await connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


async def test_timestamps_are_timezone_aware_utc(api: ClientHandle) -> None:
    await _insert_user(api, "user_ts")
    async with api.app.state.container.engine.connect() as connection:
        created_at = await connection.scalar(text("SELECT created_at FROM users"))
        timezone = await connection.scalar(text("SHOW timezone"))
    assert created_at is not None
    assert created_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert timezone == "UTC"
