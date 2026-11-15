"""Benchmarks demanded by the platform. The server verifies the answer and times the work."""

import hashlib


def cpu_chain(challenge: bytes, iterations: int) -> bytes:
    """Apply SHA-256 ``iterations`` times, starting from ``challenge``."""
    digest = challenge
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return digest
