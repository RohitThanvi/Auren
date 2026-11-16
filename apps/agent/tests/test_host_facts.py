import platform
from pathlib import Path

from auren_agent.hardware.host_facts import LinuxHostFactsProbe


def probe(root: Path) -> LinuxHostFactsProbe:
    return LinuxHostFactsProbe(sys_root=root / "sys", etc_root=root / "etc")


def test_platform_reads_os_release_kernel_and_architecture(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "os-release").write_text(
        'NAME=X\nPRETTY_NAME="Test Linux 1.0"\n', encoding="utf-8"
    )
    info = probe(tmp_path).platform_info()
    assert info.os_name == "Test Linux 1.0"
    assert info.kernel_release == platform.release()
    assert info.architecture == platform.machine()
    assert info.system == platform.system()


def test_os_name_defaults_when_os_release_is_absent(tmp_path: Path) -> None:
    assert probe(tmp_path).platform_info().os_name == "unknown"


def _nic(root: Path, name: str, *, physical: bool, speed: str | None, state: str) -> None:
    nic = root / "sys" / "class" / "net" / name
    nic.mkdir(parents=True)
    if physical:
        (nic / "device").mkdir()
    if speed is not None:
        (nic / "speed").write_text(speed + "\n", encoding="utf-8")
    (nic / "operstate").write_text(state + "\n", encoding="utf-8")


def test_only_physical_non_loopback_interfaces_are_reported(tmp_path: Path) -> None:
    _nic(tmp_path, "lo", physical=False, speed=None, state="unknown")
    _nic(tmp_path, "docker0", physical=False, speed="10000", state="up")
    _nic(tmp_path, "eth0", physical=True, speed="1000", state="up")
    _nic(tmp_path, "wlan0", physical=True, speed="-1", state="down")
    _nic(tmp_path, "eth1", physical=True, speed=None, state="down")
    network = probe(tmp_path).network_interfaces()
    assert [(n.name, n.speed_mbps, n.is_up) for n in network] == [
        ("eth0", 1000, True),
        ("eth1", None, False),
        ("wlan0", None, False),
    ]


def test_missing_sysfs_net_yields_no_interfaces(tmp_path: Path) -> None:
    assert probe(tmp_path).network_interfaces() == []
