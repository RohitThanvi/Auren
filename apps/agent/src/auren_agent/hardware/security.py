"""Security-relevant host capabilities. Reported facts only; nothing here grants anything.

Presence of a CPU virtualization flag or ``/dev/kvm`` shows that a microVM runtime may be
possible later. It does not prove that one works, and it is not an attestation.
"""

import os
from pathlib import Path

from pydantic import Field

from auren_agent.hardware.errors import HardwareProbeError
from auren_agent.hardware.models import FrozenModel

_X86_VIRTUALIZATION_FLAGS = frozenset({"vmx", "svm"})


class SecurityCapabilities(FrozenModel):
    cpu_reports_hardware_virtualization: bool = Field(
        description="x86 vmx/svm flag in cpuinfo. False is also reported on CPUs without the flag."
    )
    kvm_device_present: bool
    kvm_device_usable_by_agent: bool
    cgroup_v2: bool
    cgroup_controllers: list[str]
    agent_running_as_root: bool


class LinuxSecurityProbe:
    def __init__(
        self,
        *,
        proc_root: Path = Path("/proc"),
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        kvm_device: Path = Path("/dev/kvm"),
        effective_uid: int | None = None,
    ) -> None:
        self._proc_root = proc_root
        self._cgroup_root = cgroup_root
        self._kvm_device = kvm_device
        self._effective_uid = os.geteuid() if effective_uid is None else effective_uid

    def scan(self) -> SecurityCapabilities:
        controllers = self._read_cgroup_controllers()
        return SecurityCapabilities(
            cpu_reports_hardware_virtualization=self._cpu_reports_virtualization(),
            kvm_device_present=self._kvm_device.exists(),
            kvm_device_usable_by_agent=os.access(self._kvm_device, os.R_OK | os.W_OK),
            cgroup_v2=controllers is not None,
            cgroup_controllers=controllers or [],
            agent_running_as_root=self._effective_uid == 0,
        )

    def _cpu_reports_virtualization(self) -> bool:
        path = self._proc_root / "cpuinfo"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HardwareProbeError(f"cannot read {path}: {exc.strerror}") from exc
        for line in text.splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "flags" and _X86_VIRTUALIZATION_FLAGS & set(value.split()):
                return True
        return False

    def _read_cgroup_controllers(self) -> list[str] | None:
        """Controllers available on the unified hierarchy, or ``None`` if it is absent."""
        try:
            return (self._cgroup_root / "cgroup.controllers").read_text(encoding="utf-8").split()
        except OSError:
            return None
