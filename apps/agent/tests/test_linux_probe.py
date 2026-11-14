import platform
import shutil
import stat
import sys
from pathlib import Path

import pytest

from auren_agent.hardware.linux import LinuxHardwareProbe, LinuxPaths
from auren_agent.hardware.probe import HardwareProbeError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def proc_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    shutil.copy(FIXTURES / "cpuinfo", root / "cpuinfo")
    shutil.copy(FIXTURES / "meminfo", root / "meminfo")
    return root


def make_probe(proc_root: Path, storage: Path, nvidia_smi: str | None = None, timeout: float = 5.0):
    return LinuxHardwareProbe(
        storage_path=storage,
        gpu_probe_timeout_seconds=timeout,
        paths=LinuxPaths(
            proc=proc_root,
            sys=proc_root.parent / "sys",
            dev=proc_root.parent / "dev",
            etc=proc_root.parent / "etc",
        ),
        nvidia_smi=nvidia_smi,
    )


def fake_nvidia_smi(directory: Path, body: str) -> str:
    script = directory / "nvidia-smi"
    script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_cpu_and_memory_are_parsed(proc_root: Path, tmp_path: Path) -> None:
    inventory = make_probe(proc_root, tmp_path).scan()
    assert inventory.cpu.model_name == "Test CPU 3000"
    assert inventory.cpu.logical_cores == 4
    assert inventory.cpu.physical_cores == 2
    assert inventory.memory.total_bytes == 16_384_000 * 1024
    assert inventory.memory.available_bytes == 8_192_000 * 1024
    assert inventory.gpus == []


def test_storage_reports_the_configured_path(proc_root: Path, tmp_path: Path) -> None:
    storage = make_probe(proc_root, tmp_path).scan().storage
    assert storage.path == str(tmp_path)
    assert 0 <= storage.free_bytes <= storage.total_bytes


def test_missing_storage_path_is_an_error(proc_root: Path, tmp_path: Path) -> None:
    with pytest.raises(HardwareProbeError, match="storage"):
        make_probe(proc_root, tmp_path / "absent").scan()


def test_missing_proc_files_are_an_error(tmp_path: Path) -> None:
    with pytest.raises(HardwareProbeError, match="cpuinfo"):
        make_probe(tmp_path, tmp_path).scan()


def test_cpuinfo_without_processors_is_an_error(proc_root: Path, tmp_path: Path) -> None:
    (proc_root / "cpuinfo").write_text("vendor_id : x\n", encoding="utf-8")
    with pytest.raises(HardwareProbeError, match="no processors"):
        make_probe(proc_root, tmp_path).scan()


def test_cpuinfo_without_topology_leaves_physical_cores_unknown(
    proc_root: Path, tmp_path: Path
) -> None:
    (proc_root / "cpuinfo").write_text("processor : 0\nprocessor : 1\n", encoding="utf-8")
    cpu = make_probe(proc_root, tmp_path).scan().cpu
    assert (cpu.model_name, cpu.logical_cores, cpu.physical_cores) == ("unknown", 2, None)


def test_incomplete_meminfo_is_an_error(proc_root: Path, tmp_path: Path) -> None:
    (proc_root / "meminfo").write_text("MemTotal: 100 kB\n", encoding="utf-8")
    with pytest.raises(HardwareProbeError, match="MemAvailable"):
        make_probe(proc_root, tmp_path).scan()


def test_gpus_are_parsed_from_nvidia_smi(proc_root: Path, tmp_path: Path) -> None:
    smi = fake_nvidia_smi(
        tmp_path,
        "print('NVIDIA RTX 4090, 24564, 550.54')\nprint('NVIDIA A100, 81920, 550.54')",
    )
    gpus = make_probe(proc_root, tmp_path, smi).scan().gpus
    assert [(gpu.name, gpu.memory_total_bytes, gpu.driver_version) for gpu in gpus] == [
        ("NVIDIA RTX 4090", 24564 * 1024 * 1024, "550.54"),
        ("NVIDIA A100", 81920 * 1024 * 1024, "550.54"),
    ]


def test_unparseable_gpu_rows_are_skipped(proc_root: Path, tmp_path: Path) -> None:
    smi = fake_nvidia_smi(
        tmp_path, "print('garbage')\nprint('GPU, notanumber, 1')\nprint('OK, 10, 1')"
    )
    gpus = make_probe(proc_root, tmp_path, smi).scan().gpus
    assert [gpu.name for gpu in gpus] == ["OK"]


def test_failing_nvidia_smi_yields_no_gpus(proc_root: Path, tmp_path: Path) -> None:
    smi = fake_nvidia_smi(tmp_path, "raise SystemExit(9)")
    assert make_probe(proc_root, tmp_path, smi).scan().gpus == []


def test_hanging_nvidia_smi_times_out(proc_root: Path, tmp_path: Path) -> None:
    smi = fake_nvidia_smi(tmp_path, "import time\ntime.sleep(30)")
    assert make_probe(proc_root, tmp_path, smi, timeout=0.5).scan().gpus == []


def test_unexecutable_nvidia_smi_yields_no_gpus(proc_root: Path, tmp_path: Path) -> None:
    assert make_probe(proc_root, tmp_path, str(tmp_path / "missing")).scan().gpus == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads the real /proc")
def test_real_host_scan(tmp_path: Path) -> None:
    inventory = LinuxHardwareProbe(storage_path=tmp_path, gpu_probe_timeout_seconds=5.0).scan()
    assert inventory.cpu.logical_cores >= 1
    assert inventory.memory.total_bytes > 0


def test_cpu_virtualization_and_confidential_flags(proc_root: Path, tmp_path: Path) -> None:
    cpu = make_probe(proc_root, tmp_path).scan().cpu
    assert cpu.hardware_virtualization is True
    assert cpu.confidential_computing_flags == ["sev", "sev_es", "sev_snp"]
    assert cpu.architecture == platform.machine()


def test_cpu_without_flags_reports_no_virtualization(proc_root: Path, tmp_path: Path) -> None:
    (proc_root / "cpuinfo").write_text("processor : 0\nflags : fpu nx\n", encoding="utf-8")
    cpu = make_probe(proc_root, tmp_path).scan().cpu
    assert cpu.hardware_virtualization is False
    assert cpu.confidential_computing_flags == []


def test_arm_features_line_is_understood(proc_root: Path, tmp_path: Path) -> None:
    (proc_root / "cpuinfo").write_text("processor : 0\nFeatures : fp asimd\n", encoding="utf-8")
    assert make_probe(proc_root, tmp_path).scan().cpu.hardware_virtualization is False


def test_platform_reads_os_release_and_kvm(proc_root: Path, tmp_path: Path) -> None:
    root = proc_root.parent
    (root / "etc").mkdir()
    (root / "etc" / "os-release").write_text(
        'NAME=X\nPRETTY_NAME="Test Linux 1.0"\n', encoding="utf-8"
    )
    (root / "dev").mkdir()
    (root / "dev" / "kvm").touch()
    info = make_probe(proc_root, tmp_path).scan().platform
    assert (info.os_name, info.kvm_available) == ("Test Linux 1.0", True)
    assert info.kernel_release == platform.release()


def test_platform_defaults_when_files_are_absent(proc_root: Path, tmp_path: Path) -> None:
    info = make_probe(proc_root, tmp_path).scan().platform
    assert (info.os_name, info.kvm_available) == ("unknown", False)


def _nic(root: Path, name: str, *, physical: bool, speed: str | None, state: str) -> None:
    nic = root / "sys" / "class" / "net" / name
    nic.mkdir(parents=True)
    if physical:
        (nic / "device").mkdir()
    if speed is not None:
        (nic / "speed").write_text(speed + "\n", encoding="utf-8")
    (nic / "operstate").write_text(state + "\n", encoding="utf-8")


def test_only_physical_non_loopback_interfaces_are_reported(
    proc_root: Path, tmp_path: Path
) -> None:
    root = proc_root.parent
    _nic(root, "lo", physical=False, speed=None, state="unknown")
    _nic(root, "docker0", physical=False, speed="10000", state="up")
    _nic(root, "eth0", physical=True, speed="1000", state="up")
    _nic(root, "wlan0", physical=True, speed="-1", state="down")
    _nic(root, "eth1", physical=True, speed=None, state="down")
    network = make_probe(proc_root, tmp_path).scan().network
    assert [(n.name, n.speed_mbps, n.is_up) for n in network] == [
        ("eth0", 1000, True),
        ("eth1", None, False),
        ("wlan0", None, False),
    ]


def test_missing_sysfs_net_yields_no_interfaces(proc_root: Path, tmp_path: Path) -> None:
    assert make_probe(proc_root, tmp_path).scan().network == []
