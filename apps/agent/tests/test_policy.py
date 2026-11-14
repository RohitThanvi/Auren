import json
import os
from pathlib import Path
from typing import Any

import pytest

from auren_agent.resources.policy import (
    MAX_POLICY_FILE_BYTES,
    PauseBehavior,
    PolicyError,
    load_policy,
)

VALID: dict[str, Any] = {
    "schema_version": 1,
    "enabled": True,
    "paused": False,
    "cpu_cores": 2,
    "memory_bytes": 4 * 1024**3,
    "storage_bytes": 20 * 1024**3,
    "gpu_uuids": ["GPU-aaa"],
    "max_hosting_duration_seconds": 3600,
    "max_temperature_celsius": 80.0,
    "allow_without_thermal_sensors": False,
    "pause_behavior": "drain",
    "benchmark_consent": False,
}


def write_policy(tmp_path: Path, data: dict[str, Any], mode: int = 0o600) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(mode)
    return path


def test_valid_policy_loads(tmp_path: Path) -> None:
    policy = load_policy(write_policy(tmp_path, VALID))
    assert policy.cpu_cores == 2
    assert policy.pause_behavior is PauseBehavior.DRAIN
    assert not policy.benchmark_consent


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_policy_writable_by_others_is_refused(tmp_path: Path, mode: int) -> None:
    with pytest.raises(PolicyError, match="writable by group or others"):
        load_policy(write_policy(tmp_path, VALID, mode))


def test_missing_policy_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="cannot read"):
        load_policy(tmp_path / "absent.json")


def test_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="not a regular file"):
        load_policy(tmp_path)


def test_oversized_policy_is_refused(tmp_path: Path) -> None:
    data = {**VALID, "padding": "x" * MAX_POLICY_FILE_BYTES}
    with pytest.raises(PolicyError, match="exceeds"):
        load_policy(write_policy(tmp_path, data))


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to create a file owned by another user")
def test_policy_owned_by_another_user_is_refused(tmp_path: Path) -> None:
    path = write_policy(tmp_path, VALID)
    os.chown(path, 12345, 12345)
    with pytest.raises(PolicyError, match="owned by another user"):
        load_policy(path)


def test_undecodable_policy_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_bytes(b"\xff\xfe")
    path.chmod(0o600)
    with pytest.raises(PolicyError, match="cannot read"):
        load_policy(path)


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"cpu_cores": -1}, "cpu_cores"),
        ({"max_temperature_celsius": 150.0}, "max_temperature_celsius"),
        ({"max_temperature_celsius": 10.0}, "max_temperature_celsius"),
        ({"max_hosting_duration_seconds": 0}, "max_hosting_duration_seconds"),
        ({"gpu_uuids": ["GPU-a", "GPU-a"]}, "gpu_uuids"),
        ({"gpu_uuids": [""]}, "gpu_uuids"),
        ({"schema_version": 2}, "schema_version"),
        ({"pause_behavior": "ignore"}, "pause_behavior"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_invalid_values_are_refused(
    tmp_path: Path, override: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(PolicyError, match=fragment):
        load_policy(write_policy(tmp_path, {**VALID, **override}))


@pytest.mark.parametrize("missing", sorted(VALID))
def test_every_field_is_required(tmp_path: Path, missing: str) -> None:
    data = {key: value for key, value in VALID.items() if key != missing}
    with pytest.raises(PolicyError, match=missing):
        load_policy(write_policy(tmp_path, data))


def test_invalid_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{not json", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(PolicyError, match="invalid policy"):
        load_policy(path)
