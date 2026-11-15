import hashlib

import pytest

from auren_api.domain.scan import CHALLENGE_BYTES, cpu_chain, hashes_per_second, new_challenge


def test_cpu_chain_is_repeated_sha256() -> None:
    seed = b"\x01" * 32
    expected = hashlib.sha256(hashlib.sha256(hashlib.sha256(seed).digest()).digest()).digest()
    assert cpu_chain(seed, 3) == expected
    assert cpu_chain(seed, 0) == seed


def test_cpu_chain_depends_on_seed_and_length() -> None:
    assert cpu_chain(b"a" * 32, 10) != cpu_chain(b"b" * 32, 10)
    assert cpu_chain(b"a" * 32, 10) != cpu_chain(b"a" * 32, 11)


def test_challenges_are_random_and_fixed_size() -> None:
    first, second = new_challenge(), new_challenge()
    assert len(first) == len(second) == CHALLENGE_BYTES
    assert first != second


@pytest.mark.parametrize(
    ("iterations", "elapsed_ms", "expected"),
    [
        (3_000_000, 1000, 3_000_000),
        (3_000_000, 2000, 1_500_000),
        (1000, 0, 1_000_000),
        (10, 3, 3333),
    ],
)
def test_speed_is_derived_from_server_measured_time(
    iterations: int, elapsed_ms: int, expected: int
) -> None:
    assert hashes_per_second(iterations, elapsed_ms) == expected


def test_taking_longer_never_increases_the_measured_speed() -> None:
    speeds = [hashes_per_second(1_000_000, ms) for ms in (100, 200, 400, 800)]
    assert speeds == sorted(speeds, reverse=True)
