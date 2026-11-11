"""Application dependency container: infrastructure wired once at startup."""

from dataclasses import dataclass

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from auren_api.auth.clerk import ClerkTokenVerifier
from auren_api.config import Settings
from auren_api.infrastructure.rate_limit import RedisRateLimiter


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    http_client: httpx.AsyncClient
    token_verifier: ClerkTokenVerifier
    rate_limiter: RedisRateLimiter
