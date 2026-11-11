"""Redis client construction."""

from redis.asyncio import Redis

from auren_api.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(  # pyright: ignore[reportUnknownMemberType]  # redis-py stub gap
        settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )
