"""The API's signing code must agree with the agent's, byte for byte (shared vector)."""

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from auren_api.auth.agent import (
    b64url_decode,
    b64url_encode,
    canonical_message,
    is_acceptable_public_key,
    verify_signature,
)

VECTOR = json.loads(
    (
        Path(__file__).resolve().parents[3] / "packages/contracts/examples/signing_vector.json"
    ).read_text()
)


def _message() -> bytes:
    return canonical_message(
        method=VECTOR["method"],
        path=VECTOR["path"],
        machine_id=VECTOR["machine_id"],
        timestamp=VECTOR["timestamp"],
        nonce=VECTOR["nonce"],
        body=VECTOR["body"].encode(),
    )


def test_canonical_message_matches_the_shared_vector() -> None:
    assert _message().decode() == VECTOR["canonical_message"]


def test_signature_from_the_agent_implementation_verifies() -> None:
    public_key = b64url_decode(VECTOR["public_key_b64url"])
    signature = b64url_decode(VECTOR["signature_b64url"])
    assert verify_signature(public_key, signature, _message())


def test_the_vector_key_pair_is_consistent_and_signing_is_deterministic() -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(VECTOR["private_key_seed_hex"]))
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert b64url_encode(public) == VECTOR["public_key_b64url"]
    assert b64url_encode(key.sign(_message())) == VECTOR["signature_b64url"]


def test_any_change_to_the_message_invalidates_the_signature() -> None:
    public_key = b64url_decode(VECTOR["public_key_b64url"])
    signature = b64url_decode(VECTOR["signature_b64url"])
    for field, value in (
        ("method", "GET"),
        ("path", "/v1/agent/scans/other"),
        ("timestamp", VECTOR["timestamp"] + 1),
        ("nonce", "BBBBBBBBBBBBBBBBBBBBBB"),
        ("body", "{}"),
        ("machine_id", "99999999-2222-4333-8444-555555555555"),
    ):
        args: dict[str, Any] = {**VECTOR, field: value}
        message = canonical_message(
            method=args["method"],
            path=args["path"],
            machine_id=args["machine_id"],
            timestamp=args["timestamp"],
            nonce=args["nonce"],
            body=args["body"].encode(),
        )
        assert not verify_signature(public_key, signature, message), field


def test_verification_rejects_malformed_keys_and_signatures() -> None:
    signature = b64url_decode(VECTOR["signature_b64url"])
    assert not verify_signature(b"short", signature, _message())
    assert not verify_signature(b"\x01" * 32, b"\x00" * 64, _message())


def test_base64url_is_strict_and_unpadded() -> None:
    assert b64url_decode(b64url_encode(b"\xfb\xff\xfe")) == b"\xfb\xff\xfe"
    assert "=" not in b64url_encode(b"a")
    for bad in ("not valid!", "ab=c", "a+b/"):
        try:
            b64url_decode(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_weak_public_keys_are_not_acceptable() -> None:
    """An all-zero key with an all-zero signature verifies: the platform must refuse such keys."""
    zero_key = b"\x00" * 32
    assert verify_signature(zero_key, b"\x00" * 64, _message())  # the weakness being guarded
    identity = b"\x01" + b"\x00" * 31
    order_two = bytes.fromhex("ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f")
    for weak in (zero_key, identity, order_two):
        assert not is_acceptable_public_key(weak)


def test_real_keys_are_acceptable_and_malformed_keys_are_not() -> None:
    assert is_acceptable_public_key(b64url_decode(VECTOR["public_key_b64url"]))
    for _ in range(20):
        raw = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        assert is_acceptable_public_key(raw)
    assert not is_acceptable_public_key(b"short")
    assert not is_acceptable_public_key(b"\xff" * 32)  # y >= field prime: non-canonical
    off_curve = next(
        candidate
        for candidate in (bytes([n]) + b"\x00" * 31 for n in range(2, 40))
        if not is_acceptable_public_key(candidate)
    )
    assert not is_acceptable_public_key(off_curve)
