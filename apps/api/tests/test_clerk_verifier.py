from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from auren_api.auth.clerk import ClerkTokenVerifier, JwksUnavailableError, TokenVerificationError
from tests.support import AUTHORIZED_PARTY, ISSUER, TokenFactory

JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
CACHE_TTL = 100
MIN_REFRESH = 10


class Harness:
    """A verifier whose JWKS endpoint and clock are controlled by the test."""

    def __init__(self, tokens: TokenFactory) -> None:
        self.tokens = tokens
        self.now = 1_000.0
        self.requests = 0
        self.failing = False
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, _: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.failing:
            return httpx.Response(503)
        return httpx.Response(200, json=self.tokens.jwks())

    def verifier(
        self,
        *,
        parties: frozenset[str] = frozenset({AUTHORIZED_PARTY}),
        audience: str | None = None,
    ) -> ClerkTokenVerifier:
        return ClerkTokenVerifier(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            authorized_parties=parties,
            audience=audience,
            leeway_seconds=0,
            cache_ttl_seconds=CACHE_TTL,
            min_refresh_interval_seconds=MIN_REFRESH,
            http_client=self.client,
            clock=lambda: self.now,
        )


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory(("key-1",))


@pytest.fixture
def harness(tokens: TokenFactory) -> Harness:
    return Harness(tokens)


async def test_valid_token_returns_subject_and_party(harness: Harness) -> None:
    claims = await harness.verifier().verify(harness.tokens.token("user_abc"))
    assert claims.subject == "user_abc"
    assert claims.authorized_party == AUTHORIZED_PARTY


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"expires_in": -5}, id="expired"),
        pytest.param({"not_before_offset": 300}, id="not-yet-valid"),
        pytest.param({"issuer": "https://evil.example.test"}, id="wrong-issuer"),
        pytest.param({"authorized_party": "https://evil.example.test"}, id="bad-azp"),
        pytest.param({"authorized_party": None}, id="missing-azp"),
        pytest.param({"omit": ("exp",)}, id="missing-exp"),
        pytest.param({"omit": ("nbf",)}, id="missing-nbf"),
        pytest.param({"omit": ("sub",)}, id="missing-sub"),
        pytest.param({"subject": ""}, id="empty-sub"),
        pytest.param({"kid": "unknown", "signing_kid": "key-1"}, id="unknown-kid"),
    ],
)
async def test_invalid_tokens_are_rejected(harness: Harness, claims: dict[str, Any]) -> None:
    with pytest.raises(TokenVerificationError):
        await harness.verifier().verify(harness.tokens.token(**claims))


async def test_garbage_token_is_rejected(harness: Harness) -> None:
    with pytest.raises(TokenVerificationError):
        await harness.verifier().verify("not-a-jwt")


async def test_token_signed_by_a_different_key_is_rejected(harness: Harness) -> None:
    forged = jwt.encode(
        {"sub": "user_1", "iss": ISSUER, "iat": 1, "nbf": 1, "exp": 9_999_999_999},
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        algorithm="RS256",
        headers={"kid": "key-1"},
    )
    with pytest.raises(TokenVerificationError):
        await harness.verifier().verify(forged)


@pytest.mark.parametrize(("algorithm", "key"), [("HS256", "x" * 32), ("none", "")])
async def test_non_rs256_algorithms_are_rejected(
    harness: Harness, algorithm: str, key: str
) -> None:
    claims: dict[str, Any] = {"sub": "u", "iss": ISSUER, "iat": 1, "nbf": 1, "exp": 9_999_999_999}
    token = jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "key-1"})
    with pytest.raises(TokenVerificationError):
        await harness.verifier().verify(token)


async def test_token_without_key_id_is_rejected(harness: Harness) -> None:
    token = jwt.encode(
        {"sub": "u", "iss": ISSUER, "iat": 1, "nbf": 1, "exp": 9_999_999_999},
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        algorithm="RS256",
    )
    with pytest.raises(TokenVerificationError):
        await harness.verifier().verify(token)


async def test_audience_is_enforced_only_when_configured(harness: Harness) -> None:
    with_aud = harness.tokens.token(extra={"aud": "other"})
    assert (await harness.verifier().verify(with_aud)).subject == "user_123"
    with pytest.raises(TokenVerificationError):
        await harness.verifier(audience="auren-api").verify(with_aud)
    good = harness.tokens.token(extra={"aud": "auren-api"})
    assert (await harness.verifier(audience="auren-api").verify(good)).subject == "user_123"


async def test_authorized_parties_are_optional_outside_production(harness: Harness) -> None:
    token = harness.tokens.token(authorized_party=None)
    claims = await harness.verifier(parties=frozenset()).verify(token)
    assert claims.authorized_party is None


async def test_keys_are_cached_between_verifications(harness: Harness) -> None:
    verifier = harness.verifier()
    for _ in range(3):
        await verifier.verify(harness.tokens.token())
    assert harness.requests == 1


async def test_cache_expires_after_ttl(harness: Harness) -> None:
    verifier = harness.verifier()
    await verifier.verify(harness.tokens.token())
    harness.now += CACHE_TTL + 1
    await verifier.verify(harness.tokens.token())
    assert harness.requests == 2


async def test_unknown_key_triggers_a_throttled_refresh(harness: Harness) -> None:
    verifier = harness.verifier()
    await verifier.verify(harness.tokens.token())
    harness.tokens.add_key("key-2")
    rotated = harness.tokens.token(kid="key-2")

    with pytest.raises(TokenVerificationError):  # within the throttle window: no refetch
        await verifier.verify(rotated)
    assert harness.requests == 1

    harness.now += MIN_REFRESH
    assert (await verifier.verify(rotated)).subject == "user_123"
    assert harness.requests == 2


async def test_unknown_keys_cannot_force_repeated_fetches(harness: Harness) -> None:
    verifier = harness.verifier()
    await verifier.verify(harness.tokens.token())
    harness.now += MIN_REFRESH
    for _ in range(5):
        with pytest.raises(TokenVerificationError):
            await verifier.verify(harness.tokens.token(kid="missing", signing_kid="key-1"))
    assert harness.requests == 2


async def test_unavailable_jwks_without_cache_raises(harness: Harness) -> None:
    harness.failing = True
    with pytest.raises(JwksUnavailableError):
        await harness.verifier().verify(harness.tokens.token())


async def test_stale_keys_are_used_while_refresh_fails(harness: Harness) -> None:
    verifier = harness.verifier()
    await verifier.verify(harness.tokens.token())
    harness.failing = True
    harness.now += CACHE_TTL + 1
    assert (await verifier.verify(harness.tokens.token())).subject == "user_123"
    assert harness.requests == 2
    await verifier.verify(harness.tokens.token())  # backs off instead of refetching immediately
    assert harness.requests == 2


async def test_malformed_jwks_document_is_unavailable(tokens: TokenFactory) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"unexpected": True}))
    )
    verifier = ClerkTokenVerifier(
        issuer=ISSUER,
        jwks_url=JWKS_URL,
        authorized_parties=frozenset(),
        audience=None,
        leeway_seconds=0,
        cache_ttl_seconds=CACHE_TTL,
        min_refresh_interval_seconds=MIN_REFRESH,
        http_client=client,
    )
    with pytest.raises(JwksUnavailableError):
        await verifier.verify(tokens.token())
