"""Server-side verification of Clerk-issued session JWTs.

The frontend's authentication state is never trusted. Each token is verified for signature
(RS256 against Clerk's published JWKS), issuer, expiry, not-before, authorized party (``azp``),
and, when configured, audience.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import jwt
import structlog
from jwt import PyJWK

logger = structlog.get_logger(__name__)

_ALGORITHM = "RS256"
_REQUIRED_CLAIMS = ["exp", "iat", "nbf", "sub", "iss"]


class TokenVerificationError(Exception):
    """The token is invalid for any reason. Details are logged, never returned to clients."""


class JwksUnavailableError(Exception):
    """Signing keys could not be obtained and no cached keys exist."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    authorized_party: str | None


class ClerkTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        authorized_parties: frozenset[str],
        audience: str | None,
        leeway_seconds: int,
        cache_ttl_seconds: int,
        min_refresh_interval_seconds: int,
        http_client: httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._authorized_parties = authorized_parties
        self._audience = audience
        self._leeway_seconds = leeway_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._min_refresh_interval_seconds = min_refresh_interval_seconds
        self._http_client = http_client
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_attempt_at: float | None = None
        self._refresh_lock = asyncio.Lock()

    async def verify(self, token: str) -> TokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenVerificationError("malformed token header") from exc
        key_id = header.get("kid")
        if header.get("alg") != _ALGORITHM or not isinstance(key_id, str):
            raise TokenVerificationError("unsupported algorithm or missing key id")

        key = await self._signing_key(key_id)
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[_ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway_seconds,
                options={"require": _REQUIRED_CLAIMS, "verify_aud": self._audience is not None},
            )
        except jwt.PyJWTError as exc:
            raise TokenVerificationError(f"token rejected: {type(exc).__name__}") from exc

        subject = payload["sub"]
        if not isinstance(subject, str) or not subject:
            raise TokenVerificationError("invalid subject")
        authorized_party = payload.get("azp")
        if self._authorized_parties and authorized_party not in self._authorized_parties:
            raise TokenVerificationError("unauthorized party")
        return TokenClaims(
            subject=subject,
            authorized_party=authorized_party if isinstance(authorized_party, str) else None,
        )

    async def _signing_key(self, key_id: str) -> PyJWK:
        now = self._clock()
        fresh = self._fetched_at is not None and now - self._fetched_at < self._cache_ttl_seconds
        if fresh and key_id in self._keys:
            return self._keys[key_id]

        if self._may_attempt_refresh(now):
            await self._refresh()
        key = self._keys.get(key_id)
        if key is not None:
            return key  # includes a stale key served while refreshes are failing
        if not self._keys:
            raise JwksUnavailableError("signing keys unavailable")
        raise TokenVerificationError("unknown signing key")

    def _may_attempt_refresh(self, now: float) -> bool:
        return (
            self._last_attempt_at is None
            or now - self._last_attempt_at >= self._min_refresh_interval_seconds
        )

    async def _refresh(self) -> None:
        async with self._refresh_lock:
            now = self._clock()
            if not self._may_attempt_refresh(now):
                return  # another task refreshed while this one waited for the lock
            self._last_attempt_at = now
            try:
                response = await self._http_client.get(self._jwks_url)
                response.raise_for_status()
                document = response.json()
                keys = {
                    jwk["kid"]: PyJWK.from_dict(jwk, algorithm=_ALGORITHM)
                    for jwk in document["keys"]
                    if jwk.get("kty") == "RSA" and isinstance(jwk.get("kid"), str)
                }
            except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as exc:
                if not self._keys:
                    raise JwksUnavailableError("signing keys unavailable") from exc
                logger.warning("jwks_refresh_failed_using_cached_keys", error=type(exc).__name__)
                return
            self._keys = keys
            self._fetched_at = now
