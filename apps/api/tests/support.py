"""Test helpers: signing keys and token factory standing in for Clerk (test-only)."""

import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://clerk.example.test"
AUTHORIZED_PARTY = "https://app.example.test"


class TokenFactory:
    def __init__(self, key_ids: tuple[str, ...] = ("key-1",)) -> None:
        self._private_keys = {
            kid: rsa.generate_private_key(public_exponent=65537, key_size=2048) for kid in key_ids
        }

    def add_key(self, kid: str) -> None:
        self._private_keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        keys: list[dict[str, Any]] = []
        for kid, private_key in self._private_keys.items():
            jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
            keys.append({**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
        return {"keys": keys}

    def token(
        self,
        subject: str = "user_123",
        *,
        kid: str = "key-1",
        issuer: str = ISSUER,
        authorized_party: str | None = AUTHORIZED_PARTY,
        expires_in: int = 300,
        not_before_offset: int = 0,
        signing_kid: str | None = None,
        extra: dict[str, Any] | None = None,
        omit: tuple[str, ...] = (),
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": subject,
            "iss": issuer,
            "iat": now,
            "nbf": now + not_before_offset,
            "exp": now + expires_in,
            **({"azp": authorized_party} if authorized_party else {}),
            **(extra or {}),
        }
        for name in omit:
            claims.pop(name, None)
        private_key = self._private_keys[signing_kid or kid]
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})
