from pathlib import Path

from auren_agent.hardware.security import LinuxSecurityProbe


def capabilities(tmp_path: Path, flags: str) -> list[str]:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "cpuinfo").write_text(f"processor : 0\nflags : {flags}\n", encoding="utf-8")
    probe = LinuxSecurityProbe(
        proc_root=proc,
        cgroup_root=tmp_path / "cgroup",
        kvm_device=tmp_path / "kvm",
        effective_uid=1000,
    )
    return probe.scan().confidential_computing_flags


def test_confidential_computing_indicators_are_reported_sorted(tmp_path: Path) -> None:
    assert capabilities(tmp_path, "fpu svm sev_snp sev nx sev_es") == ["sev", "sev_es", "sev_snp"]


def test_intel_tdx_host_flag_is_reported(tmp_path: Path) -> None:
    assert capabilities(tmp_path, "fpu vmx tdx_host_platform") == ["tdx_host_platform"]


def test_no_indicators_when_the_cpu_reports_none(tmp_path: Path) -> None:
    assert capabilities(tmp_path, "fpu vmx nx") == []
