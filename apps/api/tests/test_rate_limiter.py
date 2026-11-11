import asyncio
from collections.abc import AsyncGenerator

import pytest
from redis.asyncio import Redis

from auren_api.config import RateLimitRule, Settings
from auren_api.infrastructure.rate_limit import (
    RateLimitPolicy,
    RedisRateLimiter,
    rules_from_settings,
)
from auren_api.infrastructure.redis import create_redis


@pytest.fixture
async def redis(settings: Settings) -> AsyncGenerator[Redis]:
    client = create_redis(settings)
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]  # redis-py stub gap
    yield client
    await client.aclose()


def limiter(redis: Redis, **rules: RateLimitRule) -> RedisRateLimiter:
    mapping = {policy: RateLimitRule(limit=100, window_seconds=60) for policy in RateLimitPolicy}
    mapping.update({RateLimitPolicy(name): rule for name, rule in rules.items()})
    return RedisRateLimiter(redis, mapping, "test")


async def test_requests_over_the_limit_are_rejected_with_retry_after(redis: Redis) -> None:
    rate_limiter = limiter(redis, anonymous=RateLimitRule(limit=3, window_seconds=30))
    decisions = [await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:1.1.1.1") for _ in range(4)]
    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert 1 <= decisions[3].retry_after_seconds <= 30


async def test_identities_and_policies_are_counted_independently(redis: Redis) -> None:
    rule = RateLimitRule(limit=1, window_seconds=30)
    rate_limiter = limiter(redis, anonymous=rule, authenticated=rule)
    assert (await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:a")).allowed
    assert (await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:b")).allowed
    assert (await rate_limiter.hit(RateLimitPolicy.AUTHENTICATED, "ip:a")).allowed
    assert not (await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:a")).allowed


async def test_window_expires(redis: Redis) -> None:
    rate_limiter = limiter(redis, anonymous=RateLimitRule(limit=1, window_seconds=1))
    assert (await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:a")).allowed
    assert not (await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:a")).allowed
    await asyncio.sleep(1.2)
    assert (await rate_limiter.hit(RateLimitPolicy.ANONYMOUS, "ip:a")).allowed


async def test_concurrent_requests_never_exceed_the_limit(redis: Redis) -> None:
    rate_limiter = limiter(redis, expensive=RateLimitRule(limit=5, window_seconds=30))
    decisions = await asyncio.gather(
        *(rate_limiter.hit(RateLimitPolicy.EXPENSIVE, "user:1") for _ in range(25))
    )
    assert sum(decision.allowed for decision in decisions) == 5


async def test_counter_always_expires(redis: Redis) -> None:
    rate_limiter = limiter(redis, upload=RateLimitRule(limit=1, window_seconds=30))
    await rate_limiter.hit(RateLimitPolicy.UPLOAD, "user:1")
    assert 0 < await redis.pttl("test:upload:user:1") <= 30_000


def test_every_policy_is_configurable_from_settings(settings: Settings) -> None:
    rules = rules_from_settings(settings)
    assert set(rules) == set(RateLimitPolicy)
