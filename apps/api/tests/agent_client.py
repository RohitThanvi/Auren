"""A test-side Auren agent: holds an Ed25519 key and signs requests exactly as the protocol says."""

import json
import secrets
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from auren_api.auth.agent import (
    HEADER_MACHINE_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    b64url_encode,
    canonical_message,
)
from auren_api.domain.scan import cpu_chain
from tests.conftest import ClientHandle

EMPTY_BODY = b""


class TestAgent:
    __test__ = False  # not a pytest test class

    def __init__(self, api: ClientHandle, machine_id: str) -> None:
        self.api = api
        self.machine_id = machine_id
        self.private_key = Ed25519PrivateKey.generate()

    @property
    def public_key_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return b64url_encode(raw)

    def headers(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timestamp: int | None = None,
        nonce: str | None = None,
        key: Ed25519PrivateKey | None = None,
        machine_id: str | None = None,
        signed_path: str | None = None,
        signed_body: bytes | None = None,
    ) -> dict[str, str]:
        ts = int(time.time()) if timestamp is None else timestamp
        nonce_value = nonce or secrets.token_urlsafe(16)
        mid = machine_id or self.machine_id
        message = canonical_message(
            method=method,
            path=signed_path or path,
            machine_id=mid,
            timestamp=ts,
            nonce=nonce_value,
            body=body if signed_body is None else signed_body,
        )
        signature = (key or self.private_key).sign(message)
        return {
            HEADER_MACHINE_ID: mid,
            HEADER_TIMESTAMP: str(ts),
            HEADER_NONCE: nonce_value,
            HEADER_SIGNATURE: b64url_encode(signature),
            "Content-Type": "application/json",
        }

    async def post(self, path: str, body: bytes = EMPTY_BODY, **kwargs: Any) -> httpx.Response:
        return await self.api.client.post(
            path, content=body, headers=self.headers("POST", path, body, **kwargs)
        )

    async def enroll(self, token: str, *, machine_id: str | None = None) -> httpx.Response:
        body = {
            "machine_id": machine_id or self.machine_id,
            "enrollment_token": token,
            "public_key": self.public_key_b64,
        }
        return await self.api.client.post("/v1/agent/enroll", json=body)

    async def claim(self, **kwargs: Any) -> httpx.Response:
        return await self.post("/v1/agent/scans/claim", **kwargs)

    async def submit(
        self,
        scan_id: str,
        report: dict[str, Any],
        digest: str,
        **kwargs: Any,
    ) -> httpx.Response:
        body = json.dumps({"report": report, "cpu_digest": digest}).encode()
        return await self.post(f"/v1/agent/scans/{scan_id}/result", body, **kwargs)

    @staticmethod
    def answer(challenge: dict[str, Any]) -> str:
        return cpu_chain(bytes.fromhex(challenge["challenge"]), challenge["cpu_iterations"]).hex()
