import asyncio
import uuid
from collections.abc import Callable

from fastapi import Depends
from sqlalchemy import text

from auren_api.api.deps import require_roles
from auren_api.auth.principal import Principal
from auren_api.config import Settings
from auren_api.domain.roles import Role
from tests.conftest import ClientHandle
from tests.support import TokenFactory


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_missing_token_is_unauthorized(api: ClientHandle) -> None:
    response = await api.client.get("/v1/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


async def test_non_bearer_scheme_is_unauthorized(api: ClientHandle) -> None:
    response = await api.client.get("/v1/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401


async def test_invalid_token_is_unauthorized_without_leaking_reason(api: ClientHandle) -> None:
    response = await api.client.get("/v1/me", headers=bearer("garbage"))
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid or expired token."


async def test_expired_token_is_unauthorized(api: ClientHandle, tokens: TokenFactory) -> None:
    response = await api.client.get("/v1/me", headers=bearer(tokens.token(expires_in=-60)))
    assert response.status_code == 401


async def test_first_request_provisions_a_buyer(api: ClientHandle, tokens: TokenFactory) -> None:
    response = await api.client.get("/v1/me", headers=bearer(tokens.token("user_new")))
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == ["buyer"]
    uuid.UUID(body["id"])

    again = await api.client.get("/v1/me", headers=bearer(tokens.token("user_new")))
    assert again.json() == body


async def test_distinct_subjects_get_distinct_accounts(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    first = await api.client.get("/v1/me", headers=bearer(tokens.token("user_a")))
    second = await api.client.get("/v1/me", headers=bearer(tokens.token("user_b")))
    assert first.json()["id"] != second.json()["id"]


async def test_concurrent_first_requests_create_one_account(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    responses = await asyncio.gather(
        *(api.client.get("/v1/me", headers=bearer(tokens.token("user_race"))) for _ in range(8))
    )
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["id"] for response in responses}) == 1
    async with api.app.state.container.engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM users"))
        roles = await connection.scalar(text("SELECT count(*) FROM user_roles"))
    assert (count, roles) == (1, 1)


async def test_roles_come_from_the_database_not_from_token_claims(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    token = tokens.token("user_claims", extra={"roles": ["admin"], "role": "admin"})
    response = await api.client.get("/v1/me", headers=bearer(token))
    assert response.json()["roles"] == ["buyer"]


async def test_role_changes_in_the_database_take_effect(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    token = tokens.token("user_promoted")
    me = (await api.client.get("/v1/me", headers=bearer(token))).json()
    async with api.app.state.container.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO user_roles (user_id, role) VALUES (:id, 'provider')"),
            {"id": uuid.UUID(me["id"])},
        )
    refreshed = await api.client.get("/v1/me", headers=bearer(token))
    assert refreshed.json()["roles"] == ["buyer", "provider"]


async def test_role_guard_denies_by_default_and_allows_holders(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(make_settings()).start()

    @handle.app.get("/guarded-test-route")
    async def guarded(principal: Principal = Depends(require_roles(Role.ADMIN))) -> dict[str, str]:  # noqa: B008
        return {"user": str(principal.user_id)}

    token = tokens.token("user_guard")
    assert (await handle.client.get("/guarded-test-route")).status_code == 401
    denied = await handle.client.get("/guarded-test-route", headers=bearer(token))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"

    me = (await handle.client.get("/v1/me", headers=bearer(token))).json()
    async with handle.app.state.container.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO user_roles (user_id, role) VALUES (:id, 'admin')"),
            {"id": uuid.UUID(me["id"])},
        )
    allowed = await handle.client.get("/guarded-test-route", headers=bearer(token))
    assert allowed.status_code == 200
