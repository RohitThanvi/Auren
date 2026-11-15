"""Machine (agent) request authentication.

Each enrolled machine holds an Ed25519 private key; the API stores only the public key. Every
agent request carries a signature over a canonical string that binds the HTTP method, path,
machine id, timestamp, a single-use nonce and the SHA-256 of the body. The server rejects stale
timestamps and replayed nonces, so a captured request cannot be reused.
"""

import base64
import binascii
import hashlib
import re
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PROTOCOL_TAG = "AUREN-AGENT-V1"
HEADER_MACHINE_ID = "X-Auren-Machine-Id"
HEADER_TIMESTAMP = "X-Auren-Timestamp"
HEADER_NONCE = "X-Auren-Nonce"
HEADER_SIGNATURE = "X-Auren-Signature"

PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]*$")

# Edwards25519 (RFC 8032) parameters, used only to reject weak public keys.
_FIELD = 2**255 - 19
_CURVE_D = -121665 * pow(121666, _FIELD - 2, _FIELD) % _FIELD
_SQRT_MINUS_ONE = pow(2, (_FIELD - 1) // 4, _FIELD)
_COFACTOR_DOUBLINGS = 3  # the cofactor is 8


@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    """An authenticated machine and the user who owns it."""

    machine_id: uuid.UUID
    owner_user_id: uuid.UUID


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    """Strictly decode unpadded URL-safe base64; raises ``ValueError`` on any invalid character."""
    if not _BASE64URL_PATTERN.match(value):
        raise ValueError("invalid base64url")
    standard = value.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(standard + "=" * (-len(standard) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64url") from exc


def canonical_message(
    *, method: str, path: str, machine_id: str, timestamp: int, nonce: str, body: bytes
) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    lines = [PROTOCOL_TAG, method.upper(), path, machine_id, str(timestamp), nonce, body_hash]
    return "\n".join(lines).encode("utf-8")


def verify_signature(public_key: bytes, signature: bytes, message: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


def _add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    cross = _CURVE_D * x1 * x2 * y1 * y2 % _FIELD
    x3 = (x1 * y2 + x2 * y1) * pow(1 + cross, _FIELD - 2, _FIELD) % _FIELD
    y3 = (y1 * y2 + x1 * x2) * pow(1 - cross, _FIELD - 2, _FIELD) % _FIELD
    return x3, y3


def _decode_point(encoded: bytes) -> tuple[int, int] | None:
    """Decode a canonical Edwards25519 point; None if it is not on the curve."""
    value = int.from_bytes(encoded, "little")
    y, sign = value & ((1 << 255) - 1), value >> 255
    if y >= _FIELD:
        return None
    x_squared = (y * y - 1) * pow(_CURVE_D * y * y + 1, _FIELD - 2, _FIELD) % _FIELD
    x = pow(x_squared, (_FIELD + 3) // 8, _FIELD)
    if x * x % _FIELD != x_squared:
        x = x * _SQRT_MINUS_ONE % _FIELD
    if x * x % _FIELD != x_squared or (x == 0 and sign == 1):
        return None
    return ((_FIELD - x) % _FIELD if x & 1 != sign else x), y


def is_acceptable_public_key(public_key: bytes) -> bool:
    """True for a canonical, on-curve Ed25519 key that is not a small-order (weak) point.

    Small-order keys let signatures verify for chosen messages without knowing a private key.
    """
    if len(public_key) != PUBLIC_KEY_BYTES:
        return False
    point = _decode_point(public_key)
    if point is None:
        return False
    for _ in range(_COFACTOR_DOUBLINGS):
        point = _add(point, point)
    return point != (0, 1)
