"""Single-use nonce registry (Redis) used to reject replayed agent requests."""

import uuid

from redis.asyncio import Redis


class RedisNonceStore:
    def __init__(self, redis: Redis, key_prefix: str) -> None:
        self._redis = redis
        self._key_prefix = key_prefix

    async def claim(self, machine_id: uuid.UUID, nonce: str, ttl_seconds: int) -> bool:
        """Record the nonce. Returns False if it was already used within the TTL."""
        key = f"{self._key_prefix}:{machine_id}:{nonce}"
        stored = await self._redis.set(key, "1", nx=True, ex=ttl_seconds)  # pyright: ignore[reportUnknownMemberType]
        return bool(stored)
