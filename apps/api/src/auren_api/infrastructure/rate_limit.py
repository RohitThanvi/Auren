"""Redis-backed fixed-window rate limiter shared by all API instances.

A window starts at the first request for a key and ends ``window_seconds`` later. Fixed windows
allow a burst of up to twice the limit across a window boundary; this is an accepted trade-off
documented in docs/SECURITY.md.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from redis.asyncio import Redis

from auren_api.config import RateLimitRule, Settings

_HIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('PTTL', KEYS[1])}
"""


class RateLimitPolicy(StrEnum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"
    AUTH = "auth"
    TICKET_CREATION = "ticket_creation"
    SESSION_CREATION = "session_creation"
    UPLOAD = "upload"
    EXPENSIVE = "expensive"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


def rules_from_settings(settings: Settings) -> dict[RateLimitPolicy, RateLimitRule]:
    return {
        RateLimitPolicy.ANONYMOUS: settings.rate_limit_anonymous,
        RateLimitPolicy.AUTHENTICATED: settings.rate_limit_authenticated,
        RateLimitPolicy.AUTH: settings.rate_limit_auth,
        RateLimitPolicy.TICKET_CREATION: settings.rate_limit_ticket_creation,
        RateLimitPolicy.SESSION_CREATION: settings.rate_limit_session_creation,
        RateLimitPolicy.UPLOAD: settings.rate_limit_upload,
        RateLimitPolicy.EXPENSIVE: settings.rate_limit_expensive,
    }


class RedisRateLimiter:
    def __init__(
        self, redis: Redis, rules: Mapping[RateLimitPolicy, RateLimitRule], key_prefix: str
    ) -> None:
        self._rules = rules
        self._key_prefix = key_prefix
        self._hit_script = redis.register_script(_HIT_SCRIPT)

    async def hit(self, policy: RateLimitPolicy, identity: str) -> RateLimitDecision:
        """Count one request for ``identity`` under ``policy`` and report whether it is allowed."""
        rule = self._rules[policy]
        key = f"{self._key_prefix}:{policy.value}:{identity}"
        count, ttl_ms = await self._hit_script(keys=[key], args=[rule.window_seconds * 1000])
        if count <= rule.limit:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        retry_after = math.ceil(max(int(ttl_ms), 0) / 1000) or rule.window_seconds
        return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)
