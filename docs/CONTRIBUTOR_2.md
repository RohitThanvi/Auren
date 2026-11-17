# Contributor 2: Provider agent

## Ownership

Provider agent, hardware scanning, resource inventory, agent protocol implementation (client side), provider-side lifecycle management.

## Files owned

- `apps/agent/**`
- Agent sections of docs describing `apps/agent` behaviour

## Not owned (request changes from the backend owner)

The agent protocol definition, API, database, `packages/contracts/**`, `docker-compose.yml`, CI, other `docs/` files.

## Current state

Development mode. The agent accepts no commands from the platform and runs no workloads; it is unprivileged and never touches the Docker socket. Two commands talk to the Auren API (`enroll`, `run-scan`); the others are local. Commands (`python -m auren_agent ...`, all need `AUREN_AGENT_MODE=development` and `AUREN_AGENT_STORAGE_PATH`):

- `scan`: hardware inventory JSON (unchanged shape except each GPU now has `index` and `uuid`).
- `status`: inventory, security capabilities, health, availability and allocatable capacity as JSON. Exits 1 on an unreadable host or an invalid/unsafe policy file; it never guesses a policy.
- `run`: logs a start event and exits.
- `enroll --machine-id <id>`: registers this machine's Ed25519 public key with the API using the one-time token in `AUREN_AGENT_ENROLLMENT_TOKEN` (needs `AUREN_AGENT_STATE_DIR` and `AUREN_AGENT_CONTROL_PLANE_URL`).
- `run-scan`: runs the platform scan the provider requested: consults the benchmark gate, claims the server's challenge, answers it and submits a signed report. Exit codes: 0 ok, 1 failure, 3 no scan requested, 4 benchmark refused.

The `status` JSON is a local report. It is **not** the backend wire format. The wire format for scans is `ScanReport` (`scan_report.py`: the inventory plus `security`, `platform` and `network`), published in [API_CONTRACTS.md](API_CONTRACTS.md) and [SCAN.md](SCAN.md) with the shared example `packages/contracts/examples/inventory.json`, which both the agent and API tests validate.

### Hardware model (separated concerns)

| Concern | Module | Notes |
| --- | --- | --- |
| Identity and capability | `hardware/linux.py`, `models.py` | CPU model, logical/physical cores, memory, storage at the configured path, NVIDIA GPUs (index, UUID, name, VRAM, driver). |
| Health | `hardware/health.py` | Load average; temperatures from hwmon, thermal zones and `nvidia-smi`. Implausible readings (outside -50..150 C) are dropped. |
| Security capabilities | `hardware/security.py` | CPU virtualization flag, `/dev/kvm` presence and usability, cgroup v2 controllers, whether the agent runs as root. These are reported facts, not attestation. |
| Availability and allocatable capacity | `resources/allocation.py` | Pure function of policy, inventory, health and host reserve. |
| Benchmark preconditions | `resources/benchmark_gate.py` | Gate. `run-scan` consults it before claiming a challenge. |
| Platform and network facts | `hardware/host_facts.py` | OS, kernel, architecture and physical NIC link speeds, for the scan report only. Added by the backend owner; `HardwareInventory` is unchanged. |
| Platform scan protocol | `identity.py`, `signing.py`, `client.py`, `benchmark.py`, `scan_report.py` | Ed25519 identity (key file mode 0600), signed requests, control-plane client, the SHA-256 chain benchmark, the report type. Added by the backend owner. |

Not implemented: SMART/disk health and age evidence (needs privileged `smartctl`), battery cycles, network quality measurement, further benchmarks (memory, disk, GPU, multi-core; see SCAN.md), storage medium type (SSD/HDD). The only benchmark is the platform's single-thread CPU chain. Nothing infers hardware age.

### Provider policy and resource enforcement

The provider writes a JSON policy file (`AUREN_AGENT_POLICY_PATH`, schema in `resources/policy.py`, `schema_version` 1). Every field is required; there are no permissive defaults. Without a policy, hosting is `disabled`. The loader refuses a file that is group/world-writable, owned by another user, not a regular file, or larger than 64 KiB, so another local account cannot widen the limits.

Allocatable capacity is the minimum of: the provider's approved amount, hardware minus a host reserve, and what is currently free. Reserve defaults (`AUREN_AGENT_HOST_RESERVE_CPU_CORES=1`, `..._MEMORY_FRACTION=0.25`, `..._STORAGE_FRACTION=0.10`) are conservative starting values, not measured. At least one core is always reserved, so a 1-core machine offers no CPU. GPUs are whole-device and exclusive and are offered only if the provider listed their UUID; sharing or partitioning is not assumed safe.

States: `disabled`, `paused`, `thermally_restricted` (any sensor at or above the provider's limit), `thermal_monitoring_unavailable` (no readable sensor; fails closed unless the provider set `allow_without_thermal_sensors`), `available`. This is **calculation only**: nothing enforces limits on a running workload yet, because no workloads exist. Enforcement (cgroups, container limits) belongs to the future execution component.

Benchmarks additionally require `benchmark_consent`, a readable temperature sensor (no override), no pause, a temperature below the limit, and 1-minute load at most 0.5 per logical core. The platform scan's CPU benchmark is a benchmark, so `run-scan` honours all of these: it exits with code 4 and **does not claim the challenge** (the server's timer never starts) if any applies. Consequence for the product: a provider must set `benchmark_consent` to be scannable, and a machine with no readable temperature sensor (common in VMs) cannot be scanned until that is resolved. This is a decision for the product owner; see ROADMAP.

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

## Proposal for ADR-0010: privileged-helper interface (NOT adopted, NOT implemented)

Status: design proposal from the provider-agent workstream for the architect to accept, amend or reject. No helper code exists, and no helper wire types should be written until it is accepted and the backend publishes the session/workload messages (enrolment and signed scan requests are published; heartbeat and session messages are not).

**Problem.** Running buyer workloads needs root-equivalent power (Docker daemon, KVM, cgroups, network setup). The agent must stay unprivileged and must never hold the Docker socket (SECURITY.md, ADR-0010). Something minimal has to hold that power, and it must be unable to do more than the provider approved, even if the agent or backend is compromised.

**Proposed design**
1. **Separate process and user.** The helper (`auren-helper`) is a different OS process under a dedicated service user. It listens on a Unix domain socket that only the agent's user can open, and it checks the peer UID on every connection. No TCP, no inbound network.
2. **Closed set of typed operations, no strings to execute.** `capabilities`, `prepare_workload`, `start_workload`, `stop_workload`, `release_workload`, `workload_state`, `renew_lease`. Messages are versioned JSON, size-limited and validated with pydantic (`extra="forbid"`). There is no generic exec, no shell, no file read/write, no image build, and no operation that takes a command line for the host.
3. **The helper re-validates everything itself.** It reads the same provider policy file (same permission checks) and rejects any request exceeding the policy, the host reserve or current free capacity. It never trusts the agent's arithmetic.
4. **Mandatory limits in the spec.** `WorkloadSpec` requires: `workload_id`, `isolation` (`container` | `microvm`), `trust_class` (`trusted` | `untrusted`), image reference **by digest only** (no tags), entrypoint arguments as a list (passed to the sandbox's own exec, never a host shell), CPU, memory, pids, workspace storage quota, approved GPU UUIDs (whole device, exclusive), `max_duration_seconds` (not above the policy value), and a network profile (`none` or a named egress profile). A spec missing any limit is invalid, not defaulted.
5. **ADR-0013 enforced in code.** The helper advertises which isolation levels it supports. It refuses `trust_class=untrusted` with `isolation=container`, so the "microVM before untrusted code" release gate cannot be bypassed by configuration drift.
6. **Docker-phase baseline (trusted workloads only).** Non-root user, all capabilities dropped, `no-new-privileges`, default seccomp, read-only root filesystem, no privileged mode, no host network/PID/IPC, no host mounts except one dedicated per-workload workspace, no Docker socket, a private network per workload with no inbound, tmpfs size caps, cgroup CPU/memory/pids limits. Docker containers share the host kernel; this is **not** a strong boundary against a malicious customer.
7. **Lease and cleanup.** A workload runs under a lease the agent must renew. If the agent dies or the lease or `max_duration_seconds` expires, the helper stops and removes the workload on its own. On start the helper reconciles by label and removes orphaned workloads and workspaces. Pause follows the policy's `pause_behavior` (`drain` or `terminate`), and the agent calls `stop_workload` when availability becomes `thermally_restricted`.
8. **Audit.** Every operation is logged with workload ID, operation, validated limits and outcome to a local append-only log. Specs carry no credentials and the log never contains any.
9. **MicroVM path.** Both isolation levels sit behind one `WorkloadRuntime` interface chosen by `isolation`. A microVM runtime (for example Firecracker or Cloud Hypervisor) is driven through typed config and API calls, never shell strings, and needs a usable `/dev/kvm` (already reported by `SecurityCapabilities`).

**Open questions (need the architect or backend owner)**
- Who issues `workload_id` and session authorization, and how does the agent prove a start request is authorized? The agent already signs its requests with its Ed25519 identity (SCAN.md); the missing piece is the backend-to-agent session message and how the helper learns a start request is genuine and not merely agent-originated.
- Image distribution: which registry, and is signature verification required beyond the digest?
- How buyer entrypoint arguments are supplied and bounded.
- Network egress profiles: what exists, and who defines them.
- GPU passthrough into a microVM (device isolation is hard; may need to stay container-only or be excluded for untrusted workloads).
- Helper language and packaging (Python reuse vs a small Go binary), and whether Docker runs rootless for the helper to shrink its blast radius.

**Tests required before adoption of any implementation**: the helper rejects specs missing a limit, using tags instead of digests, exceeding policy or free capacity, using `untrusted` with `container`, or naming an unknown operation; peer-UID check; lease expiry stops a workload; orphan cleanup after restart. Container hardening must be verified on a real Docker host, which has not been possible in the authoring environment.

## Backend owner's answers to the earlier requests

- **Agent protocol:** published and implemented: enrolment (one-time token, Ed25519 key), credential rotation (re-enrol; the old key is revoked), signed requests with replay protection, scan claim and result. See [SCAN.md](SCAN.md) and [API_CONTRACTS.md](API_CONTRACTS.md). Not published yet: heartbeat and session messages (no workloads exist). The agent-side client for `enroll` and `run-scan` was written by the backend owner to make the protocol testable end to end; Contributor 2 owns it from here and should review it.
- **Changes made inside `apps/agent` by the backend owner** (review and take ownership): the new modules in the table above; `config.py` (control-plane settings, `env_ignore_empty`); `__main__.py` (`enroll`, `run-scan`, exit codes); one additive field `confidential_computing_flags` in `SecurityCapabilities` (`hardware/security.py`) with its probe code. `HardwareInventory` and `LinuxHardwareProbe` are untouched.
- **ADR-0010 (privileged helper interface):** still open. It is designed with the first workload feature.
- **Changelog, `DEVELOPMENT.md`, `ARCHITECTURE.md`:** updated by the backend owner.

## Requests to Contributor 2

- GPU identity: listings currently refer to GPUs by `index` (the API requires indices 0..n-1). Your policy uses UUIDs. Confirm whether the agent should expose the stable UUID mapping so the platform can bind listings to UUIDs.
- The scan report does not yet include the agent's `availability`/allocatable result. Decide with the backend owner whether the agent should report its policy-bounded capacity so the platform can cap listings at it.
- A machine with no readable temperature sensor can never pass the benchmark gate. Propose an approach (for example a provider-acknowledged override for scan-only benchmarks) for the product owner.
