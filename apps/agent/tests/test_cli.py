import json
import sys
from pathlib import Path
from typing import Any

import pytest

from auren_agent import __main__ as cli
from auren_agent.config import AgentSettings, get_settings


@pytest.fixture(autouse=True)
def agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUREN_AGENT_MODE", "development")
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("AUREN_AGENT_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()


def test_scan_prints_a_json_inventory(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["scan"]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert set(inventory) == {"cpu", "memory", "gpus", "storage"}


def test_run_starts_in_development_mode_without_output_on_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["run"]) == 0
    assert capsys.readouterr().out == ""


def test_scan_failure_returns_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path / "absent"))
    get_settings.cache_clear()
    assert cli.main(["scan"]) == 1


def test_only_development_mode_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUREN_AGENT_MODE", "production")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="mode"):
        AgentSettings()  # pyright: ignore[reportCallIssue]


POLICY: dict[str, Any] = {
    "schema_version": 1,
    "enabled": True,
    "paused": False,
    "cpu_cores": 1,
    "memory_bytes": 1024,
    "storage_bytes": 1024,
    "gpu_uuids": [],
    "max_hosting_duration_seconds": 60,
    "max_temperature_celsius": 85.0,
    "allow_without_thermal_sensors": True,
    "pause_behavior": "terminate",
    "benchmark_consent": False,
}


def test_status_without_policy_reports_hosting_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {
        "agent_version",
        "inventory",
        "security",
        "health",
        "availability",
        "benchmark_refusals",
    }
    assert report["availability"]["state"] == "disabled"
    assert report["availability"]["allocatable"]["cpu_cores"] == 0
    assert report["benchmark_refusals"] == ["provider_consent_missing"]


def test_status_with_policy_reports_bounded_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(POLICY), encoding="utf-8")
    policy_file.chmod(0o600)
    monkeypatch.setenv("AUREN_AGENT_POLICY_PATH", str(policy_file))
    get_settings.cache_clear()
    assert cli.main(["status"]) == 0
    availability = json.loads(capsys.readouterr().out)["availability"]
    assert availability["state"] == "available"
    assert availability["allocatable"]["cpu_cores"] <= 1


def test_status_refuses_an_unsafe_policy_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(POLICY), encoding="utf-8")
    policy_file.chmod(0o666)
    monkeypatch.setenv("AUREN_AGENT_POLICY_PATH", str(policy_file))
    get_settings.cache_clear()
    assert cli.main(["status"]) == 1
    assert capsys.readouterr().out == ""


def test_status_failure_when_hardware_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AUREN_AGENT_STORAGE_PATH", str(tmp_path / "absent"))
    get_settings.cache_clear()
    assert cli.main(["status"]) == 1


def test_status_reads_gpu_temperatures_when_gpus_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    smi = tmp_path / "bin" / "nvidia-smi"
    smi.parent.mkdir()
    smi.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "q = sys.argv[1]\n"
        "print('0, GPU-aaa, Test GPU, 1024, 1.0' if 'index' in q else 'GPU-aaa, 66')\n",
        encoding="utf-8",
    )
    smi.chmod(0o700)
    monkeypatch.setenv("PATH", str(smi.parent))
    assert cli.main(["status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["inventory"]["gpus"][0]["uuid"] == "GPU-aaa"
    assert {"sensor": "gpu:GPU-aaa", "celsius": 66.0} in report["health"]["temperatures"]
