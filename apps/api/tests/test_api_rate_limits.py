import dataclasses
from collections.abc import Callable

from redis.asyncio import Redis

from auren_api.config import RateLimitRule, Settings
from tests.conftest import ClientHandle
from tests.support import TokenFactory


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_anonymous_requests_are_limited_per_ip(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    rule = RateLimitRule(limit=2, window_seconds=60)
    handle = await make_client(make_settings(rate_limit_anonymous=rule)).start()
    statuses = [(await handle.client.get("/v1/me")).status_code for _ in range(3)]
    assert statuses == [401, 401, 429]

    limited = await handle.client.get("/v1/me")
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= 60


async def test_health_endpoints_are_not_rate_limited(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    rule = RateLimitRule(limit=1, window_seconds=60)
    handle = await make_client(make_settings(rate_limit_anonymous=rule)).start()
    statuses = {(await handle.client.get("/health/live")).status_code for _ in range(5)}
    assert statuses == {200}


async def test_authenticated_requests_are_limited_per_user(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(
        make_settings(rate_limit_authenticated=RateLimitRule(limit=2, window_seconds=60))
    ).start()
    alice = bearer(tokens.token("user_alice"))
    bob = bearer(tokens.token("user_bob"))
    assert [(await handle.client.get("/v1/me", headers=alice)).status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]
    assert (await handle.client.get("/v1/me", headers=bob)).status_code == 200


async def test_spoofed_forwarded_header_does_not_evade_limits_without_trusted_proxy(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(
        make_settings(rate_limit_anonymous=RateLimitRule(limit=2, window_seconds=60))
    ).start()
    statuses = [
        (await handle.client.get("/v1/me", headers={"X-Forwarded-For": f"10.0.0.{i}"})).status_code
        for i in range(3)
    ]
    assert statuses == [401, 401, 429]


async def test_trusted_proxy_count_separates_real_clients(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(
        make_settings(
            rate_limit_anonymous=RateLimitRule(limit=1, window_seconds=60), trusted_proxy_count=1
        )
    ).start()
    first = await handle.client.get("/v1/me", headers={"X-Forwarded-For": "203.0.113.1"})
    second = await handle.client.get("/v1/me", headers={"X-Forwarded-For": "203.0.113.2"})
    repeat = await handle.client.get("/v1/me", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.1"})
    assert (first.status_code, second.status_code, repeat.status_code) == (401, 401, 429)


def _with_unreachable_redis(handle: ClientHandle) -> Redis:
    unreachable = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.2
    )
    container = handle.app.state.container
    limiter = dataclasses.replace(container, redis=unreachable)
    from auren_api.infrastructure.rate_limit import RedisRateLimiter, rules_from_settings

    handle.app.state.container = dataclasses.replace(
        limiter,
        rate_limiter=RedisRateLimiter(unreachable, rules_from_settings(handle.settings), "test"),
    )
    return unreachable


async def test_limiter_fails_closed_when_redis_is_down(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings()).start()
    unreachable = _with_unreachable_redis(handle)
    response = await handle.client.get("/v1/me")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    await unreachable.aclose()


async def test_limiter_can_be_configured_to_fail_open(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings(rate_limit_fail_open=True)).start()
    unreachable = _with_unreachable_redis(handle)
    response = await handle.client.get("/v1/me")
    assert response.status_code == 401  # request proceeded to authentication
    await unreachable.aclose()
