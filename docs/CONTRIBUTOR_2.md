# Contributor 2: Provider agent

## Ownership

Provider agent, hardware scanning, resource inventory, agent protocol implementation (client side), provider-side lifecycle management.

## Files owned

- `apps/agent/**`
- Agent sections of docs describing `apps/agent` behaviour

## Not owned (request changes from the backend owner)

The agent protocol definition, API, database, `packages/contracts/**`, `docker-compose.yml`, CI, other `docs/` files.

## Current state

Development mode only. The agent makes no network connections, accepts no commands and runs no workloads. It is unprivileged and never touches the Docker socket. Commands (`python -m auren_agent ...`, all need `AUREN_AGENT_MODE=development` and `AUREN_AGENT_STORAGE_PATH`):

- `scan`: hardware inventory JSON (unchanged shape except each GPU now has `index` and `uuid`).
- `status`: inventory, security capabilities, health, availability and allocatable capacity as JSON. Exits 1 on an unreadable host or an invalid/unsafe policy file; it never guesses a policy.
- `run`: logs a start event and exits.

The `status` JSON is a local report. It is **not** the backend wire format, which the backend owner has not published.

### Hardware model (separated concerns)

| Concern | Module | Notes |
| --- | --- | --- |
| Identity and capability | `hardware/linux.py`, `models.py` | CPU model, logical/physical cores, memory, storage at the configured path, NVIDIA GPUs (index, UUID, name, VRAM, driver). |
| Health | `hardware/health.py` | Load average; temperatures from hwmon, thermal zones and `nvidia-smi`. Implausible readings (outside -50..150 C) are dropped. |
| Security capabilities | `hardware/security.py` | CPU virtualization flag, `/dev/kvm` presence and usability, cgroup v2 controllers, whether the agent runs as root. These are reported facts, not attestation. |
| Availability and allocatable capacity | `resources/allocation.py` | Pure function of policy, inventory, health and host reserve. |
| Benchmark preconditions | `resources/benchmark_gate.py` | Gate only. **No benchmark runner exists.** |

Not implemented: SMART/disk health and age evidence (needs privileged `smartctl`), battery cycles, network quality measurement, benchmarks, storage medium type (SSD/HDD). Nothing infers hardware age.

### Provider policy and resource enforcement

The provider writes a JSON policy file (`AUREN_AGENT_POLICY_PATH`, schema in `resources/policy.py`, `schema_version` 1). Every field is required; there are no permissive defaults. Without a policy, hosting is `disabled`. The loader refuses a file that is group/world-writable, owned by another user, not a regular file, or larger than 64 KiB, so another local account cannot widen the limits.

Allocatable capacity is the minimum of: the provider's approved amount, hardware minus a host reserve, and what is currently free. Reserve defaults (`AUREN_AGENT_HOST_RESERVE_CPU_CORES=1`, `..._MEMORY_FRACTION=0.25`, `..._STORAGE_FRACTION=0.10`) are conservative starting values, not measured. At least one core is always reserved, so a 1-core machine offers no CPU. GPUs are whole-device and exclusive and are offered only if the provider listed their UUID; sharing or partitioning is not assumed safe.

States: `disabled`, `paused`, `thermally_restricted` (any sensor at or above the provider's limit), `thermal_monitoring_unavailable` (no readable sensor; fails closed unless the provider set `allow_without_thermal_sensors`), `available`. This is **calculation only**: nothing enforces limits on a running workload yet, because no workloads exist. Enforcement (cgroups, container limits) belongs to the future execution component.

Benchmarks additionally require `benchmark_consent`, a readable temperature sensor (no override), no pause, a temperature below the limit, and 1-minute load at most 0.5 per logical core.

### Host compatibility and privileges

Linux only (reads `/proc`, `/sys`). The agent needs no root and no extra capabilities; running as root is reported as a security finding. Windows (Hyper-V/WSL2) is a separate design task and is not started. Validation was done on a 1-core virtual machine with no sensors, KVM or cgroup v2, so the temperature, KVM and cgroup paths are verified only against fixture directory trees, not real hardware.

### Troubleshooting

- `status_failed ... writable by group or others`: `chmod 600` the policy file and make sure you own it.
- `status_failed ... invalid policy file`: the message lists each invalid field.
- State `thermal_monitoring_unavailable`: the machine exposes no temperature sensors (common in VMs). Hosting stays off unless you set `allow_without_thermal_sensors` to true, which means thermal limits cannot be enforced.
- Offered CPU/memory lower than approved: see `availability.reasons` (host reserve or current host memory use).

## Boundaries

- Hardware detection stays behind the `HardwareProbe` interface; add platform implementations as new modules (a Windows probe is a separate, later task).
- Privileged host operations (starting/stopping containers or VMs) must be a separate component from the unprivileged agent (ADR-0010). Do not add Docker-socket access or `sudo` calls to the agent process.
- Never expose unrestricted execution. Only typed, allow-listed operations from the backend; no shell interpolation of any backend-supplied value; fixed argv and timeouts for subprocesses.
- Buyer workloads never run directly on the provider host OS, never privileged, never with the Docker socket, always with resource limits.
- Outbound connections only, authenticated TLS; no inbound ports.
- Do not invent the wire protocol. Wait for the backend owner to publish it in `docs/`, then implement the client side and report mismatches rather than adjusting your side silently.

## Integration rules

- Configuration through `AUREN_AGENT_*` environment variables validated at startup (`config.py`); add new settings there, never hardcode limits.
- Run `make agent-check` before each PR (ruff, pyright strict, pytest with coverage) and report real results. Hardware code needs tests using fixture `/proc` files and real subprocesses (see `tests/test_linux_probe.py`).
- Logs: JSON on stderr; stdout is reserved for command output. Never log credentials.
- Update this file and `docs/ARCHITECTURE.md` agent section (via the architect) when behaviour changes.

## Requests for the backend/architect owner

- Publish the agent protocol (enrolment, credential rotation, heartbeat, session messages, inventory upload). The agent implements nothing network-facing until then.
- ADR-0010: define the privileged-helper interface (typed workload spec with mandatory limits, isolation level so microVM can replace Docker) before any execution code is written here.
- Changelog line for the architect to merge: "Provider agent: security capabilities, host health and temperatures, provider policy file, allocatable-capacity calculation, benchmark safety gate, `status` command; GPUs now report index and UUID."
- `docs/DEVELOPMENT.md`: add the `status` command and the new `AUREN_AGENT_POLICY_PATH` and `AUREN_AGENT_HOST_RESERVE_*` variables to the `AUREN_AGENT_*` row.
- `docs/ARCHITECTURE.md` agent state row: now "Hardware inventory, health, policy and capacity calculation; no network, no workloads".
