"""Platform-issued scan challenges.

The CPU challenge is a sequential SHA-256 chain seeded by a server-generated random value. It
cannot be parallelised, so its duration measures single-thread speed, and the server times it
from its own clock (claim -> result). A client can therefore make itself look slower, never
faster: the server-measured time is an upper bound on how long the work took.
"""

import hashlib
import secrets
from enum import StrEnum

CHALLENGE_BYTES = 32
DIGEST_BYTES = 32


class ScanStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanFailure(StrEnum):
    EXPIRED = "expired"
    BENCHMARK_MISMATCH = "benchmark_mismatch"


def new_challenge() -> bytes:
    return secrets.token_bytes(CHALLENGE_BYTES)


def cpu_chain(challenge: bytes, iterations: int) -> bytes:
    """Apply SHA-256 ``iterations`` times, starting from ``challenge``."""
    digest = challenge
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return digest


def hashes_per_second(iterations: int, elapsed_ms: int) -> int:
    """Single-thread speed implied by a server-measured duration (at least 1 ms)."""
    return iterations * 1000 // max(elapsed_ms, 1)
