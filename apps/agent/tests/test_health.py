import stat
import sys
from pathlib import Path

import pytest

from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.hardware.health import LinuxHealthReader


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    proc, sys_root = tmp_path / "proc", tmp_path / "sys"
    write(proc / "loadavg", "0.50 0.40 0.30 1/200 999\n")
    return proc, sys_root


def reader(roots: tuple[Path, Path], smi: str | None = None) -> LinuxHealthReader:
    return LinuxHealthReader(
        gpu_probe_timeout_seconds=5.0, proc_root=roots[0], sys_root=roots[1], nvidia_smi=smi
    )


def test_load_average_is_parsed_and_no_sensors_means_no_temperatures(
    roots: tuple[Path, Path],
) -> None:
    health = reader(roots).read()
    assert (health.load_average_1m, health.load_average_5m, health.load_average_15m) == (
        0.5,
        0.4,
        0.3,
    )
    assert health.temperatures == []


def test_hwmon_and_thermal_zones_are_read(roots: tuple[Path, Path]) -> None:
    hwmon = roots[1] / "class" / "hwmon" / "hwmon0"
    write(hwmon / "name", "coretemp\n")
    write(hwmon / "temp1_input", "61000\n")
    write(hwmon / "temp1_label", "Package id 0\n")
    write(hwmon / "temp2_input", "55500\n")
    zone = roots[1] / "class" / "thermal" / "thermal_zone0"
    write(zone / "type", "acpitz\n")
    write(zone / "temp", "42000\n")
    readings = {r.sensor: r.celsius for r in reader(roots).read().temperatures}
    assert readings == {
        "hwmon:coretemp:Package id 0": 61.0,
        "hwmon:coretemp:temp2": 55.5,
        "thermal:acpitz": 42.0,
    }


def test_faulty_sensor_values_are_ignored(roots: tuple[Path, Path]) -> None:
    hwmon = roots[1] / "class" / "hwmon" / "hwmon0"
    write(hwmon / "temp1_input", "not-a-number\n")
    write(hwmon / "temp2_input", "999000\n")
    zone = roots[1] / "class" / "thermal" / "thermal_zone0"
    write(zone / "temp", "-90000\n")
    assert reader(roots).read().temperatures == []


def test_unreadable_sensor_file_is_skipped(roots: tuple[Path, Path]) -> None:
    hwmon = roots[1] / "class" / "hwmon" / "hwmon0"
    (hwmon / "temp1_input").mkdir(parents=True)  # reading a directory raises OSError
    zone = roots[1] / "class" / "thermal" / "thermal_zone0"
    (zone / "temp").mkdir(parents=True)
    assert reader(roots).read().temperatures == []


def test_missing_loadavg_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(HardwareProbeError, match="load average"):
        reader((tmp_path / "proc", tmp_path / "sys")).read()


def test_malformed_loadavg_is_an_error(roots: tuple[Path, Path]) -> None:
    write(roots[0] / "loadavg", "x y\n")
    with pytest.raises(HardwareProbeError, match="load average"):
        reader(roots).read()


def fake_smi(directory: Path, body: str) -> str:
    script = directory / "nvidia-smi"
    script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_gpu_temperatures_are_read_and_bad_rows_skipped(
    roots: tuple[Path, Path], tmp_path: Path
) -> None:
    smi = fake_smi(
        tmp_path, "print('GPU-a, 70')\nprint('GPU-b, hot')\nprint('GPU-c')\nprint('GPU-d, 900')"
    )
    readings = {r.sensor: r.celsius for r in reader(roots, smi).read().temperatures}
    assert readings == {"gpu:GPU-a": 70.0}


def test_failing_nvidia_smi_yields_no_gpu_temperatures(
    roots: tuple[Path, Path], tmp_path: Path
) -> None:
    assert reader(roots, fake_smi(tmp_path, "raise SystemExit(3)")).read().temperatures == []
