# Contributor 2: Provider agent

## Ownership

Provider agent, hardware scanning, resource inventory, agent protocol implementation (client side), provider-side lifecycle management.

## Files owned

- `apps/agent/**`
- Agent sections of docs describing `apps/agent` behaviour

## Not owned (request changes from the backend owner)

The agent protocol definition, API, database, `packages/contracts/**`, `docker-compose.yml`, CI, other `docs/` files.

## Scan contract (shared with the API)

The scan `report` the API accepts is exactly the JSON that `python -m auren_agent scan` prints, validated strictly (unknown fields rejected), and only as part of a platform-run scan (see [SCAN.md](SCAN.md)). `packages/contracts/examples/inventory.json` is the shared example; `tests/test_cli.py` checks it against the agent model. **Adding or renaming a scan field requires the backend owner to change the API first**, otherwise submitted scans will be rejected. Reported confidential-computing flags are indicators, not attestation.

## Commands

`scan` (local JSON, no network), `run` (development mode log, no network), `enroll --machine-id <id>` (token from `AUREN_AGENT_ENROLLMENT_TOKEN`), `run-scan` (claim, answer the challenge, submit). Exit codes: 0 ok, 1 failure, 3 no scan requested. Network commands need `AUREN_AGENT_STATE_DIR` and `AUREN_AGENT_CONTROL_PLANE_URL`.

## Protocol rules

The canonical string and header names in `signing.py` must match the API byte for byte; both sides are tested against `packages/contracts/examples/signing_vector.json`, which the backend owner changes. The benchmark in `benchmark.py` must match `domain/scan.py` in the API. Never log the enrolment token or key material, never accept an `http://` control plane except on loopback, and keep the key file at mode 0600.

## Current state

`scan`/`run` read CPU, memory, NVIDIA GPUs, storage, platform/KVM, confidential-computing flags and network interfaces through `HardwareProbe`/`LinuxHardwareProbe`. `enroll` and `run-scan` talk to the API. There is no long-running daemon and no workload execution; `AUREN_AGENT_MODE` accepts only `development`.

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
