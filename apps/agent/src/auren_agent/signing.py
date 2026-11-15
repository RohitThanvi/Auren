"""Request signing for the Auren agent protocol (AUREN-AGENT-V1).

The canonical string and header names must match the API exactly; both sides are tested against
``packages/contracts/examples/signing_vector.json``.
"""

import base64
import hashlib
import secrets
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROTOCOL_TAG = "AUREN-AGENT-V1"
HEADER_MACHINE_ID = "X-Auren-Machine-Id"
HEADER_TIMESTAMP = "X-Auren-Timestamp"
HEADER_NONCE = "X-Auren-Nonce"
HEADER_SIGNATURE = "X-Auren-Signature"
_NONCE_BYTES = 16


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical_message(
    *, method: str, path: str, machine_id: str, timestamp: int, nonce: str, body: bytes
) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    lines = [PROTOCOL_TAG, method.upper(), path, machine_id, str(timestamp), nonce, body_hash]
    return "\n".join(lines).encode("utf-8")


def sign_request(
    private_key: Ed25519PrivateKey,
    *,
    machine_id: uuid.UUID,
    method: str,
    path: str,
    body: bytes,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Return the authentication headers for one request. Each call uses a fresh nonce."""
    ts = int(time.time()) if timestamp is None else timestamp
    nonce_value = nonce or b64url_encode(secrets.token_bytes(_NONCE_BYTES))
    message = canonical_message(
        method=method,
        path=path,
        machine_id=str(machine_id),
        timestamp=ts,
        nonce=nonce_value,
        body=body,
    )
    return {
        HEADER_MACHINE_ID: str(machine_id),
        HEADER_TIMESTAMP: str(ts),
        HEADER_NONCE: nonce_value,
        HEADER_SIGNATURE: b64url_encode(private_key.sign(message)),
    }
