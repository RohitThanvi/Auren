import json
import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from auren_agent import __main__ as cli
from auren_agent.benchmark import cpu_chain
from auren_agent.config import AgentSettings, get_settings
from auren_agent.identity import (
    KEY_FILE,
    IdentityError,
    load_machine_id,
    load_or_create_identity,
    save_machine_id,
)
from auren_agent.signing import canonical_message, sign_request
from tests.fake_control_plane import CHALLENGE, ITERATIONS, FakeControlPlane

VECTOR = json.loads(
    (
        Path(__file__).resolve().parents[3] / "packages/contracts/examples/signing_vector.json"
    ).read_text()
)
MACHINE_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")


# --- protocol vector (shared with the API test suite) ---------------------------------------


def test_signing_matches_the_shared_vector() -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(VECTOR["private_key_seed_hex"]))
    body = VECTOR["body"].encode()
    message = canonical_message(
        method=VECTOR["method"],
        path=VECTOR["path"],
        machine_id=VECTOR["machine_id"],
        timestamp=VECTOR["timestamp"],
        nonce=VECTOR["nonce"],
        body=body,
    )
    assert message.decode() == VECTOR["canonical_message"]
    headers = sign_request(
        key,
        machine_id=uuid.UUID(VECTOR["machine_id"]),
        method=VECTOR["method"],
        path=VECTOR["path"],
        body=body,
        timestamp=VECTOR["timestamp"],
        nonce=VECTOR["nonce"],
    )
    assert headers["X-Auren-Signature"] == VECTOR["signature_b64url"]


def test_every_request_gets_a_fresh_nonce() -> None:
    key = Ed25519PrivateKey.generate()
    nonces = {
        sign_request(key, machine_id=MACHINE_ID, method="POST", path="/p", body=b"")[
            "X-Auren-Nonce"
        ]
        for _ in range(50)
    }
    assert len(nonces) == 50


def test_benchmark_matches_the_server_definition() -> None:
    assert cpu_chain(b"\x00" * 32, 0) == b"\x00" * 32
    assert len(cpu_chain(b"\x00" * 32, 10)) == 32


# --- identity -------------------------------------------------------------------------------


def test_identity_is_created_private_and_reused(tmp_path: Path) -> None:
    state = tmp_path / "state"
    first = load_or_create_identity(state)
    assert stat.S_IMODE((state / KEY_FILE).stat().st_mode) == 0o600
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert load_or_create_identity(state).public_key_b64 == first.public_key_b64
    assert len(first.public_key_b64) == 43


def test_insecure_or_corrupt_keys_are_refused(tmp_path: Path) -> None:
    load_or_create_identity(tmp_path)
    key_path = tmp_path / KEY_FILE
    key_path.chmod(0o644)
    with pytest.raises(IdentityError, match="chmod 600"):
        load_or_create_identity(tmp_path)
    key_path.chmod(0o600)
    key_path.write_bytes(b"short")
    with pytest.raises(IdentityError, match="not a valid"):
        load_or_create_identity(tmp_path)


def test_machine_id_round_trip_and_missing(tmp_path: Path) -> None:
    with pytest.raises(IdentityError, match="not enrolled"):
        load_machine_id(tmp_path)
    save_machine_id(tmp_path, MACHINE_ID)
    assert load_machine_id(tmp_path) == MACHINE_ID


# --- settings -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://api.example.com", "ftp://x", "https://api.example.com/v1", "https://a?b=1", "api"],
)
def test_unsafe_control_plane_urls_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    monkeypatch.setenv("AUREN_AGENT_MODE", "development")
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("AUREN_AGENT_CONTROL_PLANE_URL", url)
    with pytest.raises(ValidationError):
        AgentSettings()  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.example.com/", "https://api.example.com"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_safe_control_plane_urls_are_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str, expected: str
) -> None:
    monkeypatch.setenv("AUREN_AGENT_MODE", "development")
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("AUREN_AGENT_CONTROL_PLANE_URL", url)
    assert AgentSettings().control_plane_url == expected  # pyright: ignore[reportCallIssue]


def test_enrollment_token_is_not_exposed_in_repr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AUREN_AGENT_MODE", "development")
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("AUREN_AGENT_ENROLLMENT_TOKEN", "very-secret-token-value")
    assert "very-secret-token-value" not in repr(AgentSettings())  # pyright: ignore[reportCallIssue]


# --- commands against a real (loopback) control plane --------------------------------------


@pytest.fixture
def plane() -> Iterator[FakeControlPlane]:
    with FakeControlPlane() as server:
        yield server


@pytest.fixture
def agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, plane: FakeControlPlane) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("AUREN_AGENT_MODE", "development")
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("AUREN_AGENT_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("AUREN_AGENT_STATE_DIR", str(state))
    monkeypatch.setenv("AUREN_AGENT_CONTROL_PLANE_URL", plane.url)
    monkeypatch.setenv("AUREN_AGENT_ENROLLMENT_TOKEN", plane.state.enrollment_token)
    get_settings.cache_clear()
    return state


def enroll() -> int:
    return cli.main(["enroll", "--machine-id", str(MACHINE_ID)])


def test_enroll_registers_the_public_key_and_remembers_the_machine(
    agent_env: Path, plane: FakeControlPlane
) -> None:
    assert enroll() == 0
    registered = plane.state.public_keys[str(MACHINE_ID)]
    identity = load_or_create_identity(agent_env)
    assert identity.public_key_b64 == __import__(
        "auren_agent.signing", fromlist=["x"]
    ).b64url_encode(registered)
    assert load_machine_id(agent_env) == MACHINE_ID


def test_enroll_with_a_wrong_token_fails_and_stores_nothing(
    agent_env: Path, plane: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUREN_AGENT_ENROLLMENT_TOKEN", "some-other-token-value")
    get_settings.cache_clear()
    assert enroll() == 1
    assert plane.state.public_keys == {}
    with pytest.raises(IdentityError):
        load_machine_id(agent_env)


@pytest.mark.parametrize(
    "missing",
    ["AUREN_AGENT_ENROLLMENT_TOKEN", "AUREN_AGENT_STATE_DIR", "AUREN_AGENT_CONTROL_PLANE_URL"],
)
def test_network_commands_need_their_settings(
    agent_env: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)
    get_settings.cache_clear()
    assert enroll() == 1


def test_run_scan_reports_when_nothing_was_requested(agent_env: Path) -> None:
    assert enroll() == 0
    assert cli.main(["run-scan"]) == 3


def test_run_scan_answers_the_challenge_and_submits_a_signed_report(
    agent_env: Path, plane: FakeControlPlane
) -> None:
    assert enroll() == 0
    plane.state.pending_scan = True
    assert cli.main(["run-scan"]) == 0
    (result,) = plane.state.results
    assert result["digest_correct"] is True
    assert result["cpu_digest"] == cpu_chain(CHALLENGE, ITERATIONS).hex()
    assert set(result["report"]) == {"cpu", "memory", "gpus", "storage", "platform", "network"}
    assert len(plane.state.nonces) == 2  # claim and result each used a fresh nonce


def test_run_scan_requires_enrolment(agent_env: Path) -> None:
    assert cli.main(["run-scan"]) == 1


def test_run_scan_fails_when_the_server_rejects_the_result(
    agent_env: Path, plane: FakeControlPlane
) -> None:
    assert enroll() == 0
    plane.state.pending_scan = True
    plane.state.fail_result_with = (422, "benchmark_mismatch")
    assert cli.main(["run-scan"]) == 1


def test_run_scan_fails_when_the_server_is_unreachable(
    agent_env: Path, plane: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert enroll() == 0
    monkeypatch.setenv("AUREN_AGENT_CONTROL_PLANE_URL", "http://127.0.0.1:1")
    get_settings.cache_clear()
    assert cli.main(["run-scan"]) == 1


def test_a_stolen_key_file_is_not_accepted_with_loose_permissions(agent_env: Path) -> None:
    assert enroll() == 0
    os.chmod(agent_env / KEY_FILE, 0o644)
    assert cli.main(["run-scan"]) == 1


def test_empty_environment_values_mean_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Copying .env.example leaves the network settings empty; they must not break local commands."""
    monkeypatch.setenv("AUREN_AGENT_MODE", "development")
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path))
    for name in ("STATE_DIR", "CONTROL_PLANE_URL", "ENROLLMENT_TOKEN"):
        monkeypatch.setenv(f"AUREN_AGENT_{name}", "")
    settings = AgentSettings()  # pyright: ignore[reportCallIssue]
    assert (settings.state_dir, settings.control_plane_url, settings.enrollment_token) == (
        None,
        None,
        None,
    )
