import json
from pathlib import Path

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
