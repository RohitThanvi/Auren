from pathlib import Path

import pytest

from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.hardware.security import LinuxSecurityProbe


def make_probe(tmp_path: Path, *, uid: int = 1000) -> LinuxSecurityProbe:
    return LinuxSecurityProbe(
        proc_root=tmp_path / "proc",
        cgroup_root=tmp_path / "cgroup",
        kvm_device=tmp_path / "kvm",
        effective_uid=uid,
    )


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    (root / "cpuinfo").write_text("processor : 0\nflags : fpu vmx sse\n", encoding="utf-8")
    return root


def test_reports_virtualization_flag_kvm_and_cgroups(tmp_path: Path, proc: Path) -> None:
    (tmp_path / "kvm").write_text("", encoding="utf-8")
    (tmp_path / "cgroup").mkdir()
    (tmp_path / "cgroup" / "cgroup.controllers").write_text("cpu memory io pids\n", "utf-8")
    caps = make_probe(tmp_path).scan()
    assert caps.cpu_reports_hardware_virtualization
    assert caps.kvm_device_present
    assert caps.kvm_device_usable_by_agent
    assert caps.cgroup_v2
    assert caps.cgroup_controllers == ["cpu", "memory", "io", "pids"]
    assert not caps.agent_running_as_root


def test_missing_capabilities_are_reported_as_absent(tmp_path: Path, proc: Path) -> None:
    (proc / "cpuinfo").write_text("processor : 0\nflags : fpu sse\n", encoding="utf-8")
    caps = make_probe(tmp_path, uid=0).scan()
    assert not caps.cpu_reports_hardware_virtualization
    assert not caps.kvm_device_present
    assert not caps.kvm_device_usable_by_agent
    assert not caps.cgroup_v2
    assert caps.cgroup_controllers == []
    assert caps.agent_running_as_root


def test_amd_svm_flag_is_recognised(tmp_path: Path, proc: Path) -> None:
    (proc / "cpuinfo").write_text("flags : svm\n", encoding="utf-8")
    assert make_probe(tmp_path).scan().cpu_reports_hardware_virtualization


def test_unreadable_cpuinfo_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(HardwareProbeError, match="cpuinfo"):
        make_probe(tmp_path).scan()


def test_default_construction_reads_the_real_host() -> None:
    assert isinstance(LinuxSecurityProbe().scan().cgroup_controllers, list)
