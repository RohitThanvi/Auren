# Platform device scan: design and trust model

The platform, not the provider, scans a machine before it can be listed, in the way assessment companies scan a candidate's computer before an online exam. The provider only asks for a scan; the Auren agent (our software, installed on the machine) performs it against challenges generated and timed by our servers.

## Honest trust model

Any software that runs on a machine its owner controls can be tampered with. Proctoring software can be defeated too; its value is raising the cost of cheating and making it detectable. The same holds here, with one important difference: **some evidence is measured on our side of the network, where the provider cannot touch it.** The design therefore ranks every claim by how it is verified:

| Strength | Meaning | Example |
| --- | --- | --- |
| Measured by us | Our server's clock or computation decides; the provider can only look worse, not better | Single-thread CPU speed (implemented); network throughput and latency (designed) |
| Cryptographically attested | Rooted in hardware keys the provider cannot forge | TPM quote, SEV-SNP / TDX / GPU attestation (designed) |
| Challenge-verified | The agent must prove it has the resource by answering a random, server-checked challenge | Memory, disk and GPU proofs (designed) |
| Agent-reported | Read from the OS by the agent; a modified agent or spoofed OS can lie | Core count, RAM size, GPU names and UUIDs, kernel, NIC list, CPU flags, security capabilities (implemented) |

The scan record and API label this: `verification: "agent_scanned"` means "reported through an enrolled agent with a server-timed benchmark". It does **not** mean the hardware facts are proven.

## Implemented (v1)

### Machine identity

1. The provider registers a machine and requests an **enrolment token** (`POST /v1/provider/machines/{id}/enrollment`): 256-bit random, single use, expires after `AUREN_ENROLLMENT_TTL_SECONDS`, stored only as a SHA-256 hash, shown once. A newer token revokes older unused ones.
2. On the machine, `auren-agent enroll --machine-id <id>` (token supplied through `AUREN_AGENT_ENROLLMENT_TOKEN`, never argv) generates an **Ed25519 key pair**. The private key stays on the machine (file mode 0600, directory 0700; the agent refuses a key readable by others). The public key is sent to `POST /v1/agent/enroll`.
3. The API stores the public key (one active credential per machine; re-enrolling revokes the old key) and rejects weak keys (small-order points; the check is covered by tests because an all-zero key verifies all-zero signatures).

Every token or machine failure at enrolment returns the same generic 401, so tokens and machine ids cannot be probed.

### Request signing (AUREN-AGENT-V1)

Each agent request carries `X-Auren-Machine-Id`, `X-Auren-Timestamp`, `X-Auren-Nonce`, `X-Auren-Signature`. The signature covers: protocol tag, HTTP method, path, machine id, timestamp, nonce and the SHA-256 of the body. The server rejects a request unless the machine is enrolled and not withdrawn, the signature verifies, the timestamp is within `AUREN_AGENT_REQUEST_MAX_SKEW_SECONDS`, and the nonce has not been used (Redis `SET NX`, recorded only after the signature verifies; the store fails closed if Redis is down). Agent endpoints are also rate limited per machine. The API and agent implementations are tested against a shared vector, `packages/contracts/examples/signing_vector.json`. Deployments must not rewrite request paths (the path is signed).

### Scan session

```
Provider (browser)        API                                   Agent (on the machine)
  POST .../scans  ------>  create pending scan, random 32-byte
                           challenge, expires in SCAN_TTL
                                                     <----------  read hardware locally
                                                     <----------  POST /v1/agent/scans/claim (signed)
                           mark claimed, start the SERVER timer,
                           deadline = SCAN_RESULT_DEADLINE
                           return challenge + iterations  ---->
                                                                  digest = SHA-256 chain(challenge, N)
                                                     <----------  POST /v1/agent/scans/{id}/result (signed)
                                                                  {report, cpu_digest}
                           stop timer; recompute the chain;
                           compare digest (constant time);
                           speed = N / server-elapsed;
                           store inventory (append-only);
                           re-check any listing, pause if invalid
```

Security properties, all covered by tests:

- **Single use, single claimer.** Exactly one claim succeeds (row lock); a result can be accepted once; results for unclaimed scans, other machines' scans, or expired scans are rejected (404 for foreign scans, indistinguishable from unknown ids).
- **Only one open scan per machine** (partial unique index), so scan requests cannot be used to burn server CPU; requests are also rate limited with the strict `expensive` policy. Verification cost is bounded by `AUREN_SCAN_CPU_ITERATIONS` and run in a worker thread.
- **Wrong answers fail the scan permanently**; a failed scan never blocks a new one. A stale open scan is failed automatically when a new one is requested.
- **Invalid reports do not consume the scan**: validation happens before the result is processed. Reports are strictly validated (unknown fields, absurd values and control characters rejected).
- **Providers cannot submit hardware facts.** The old provider-submitted inventory endpoint does not exist; only an enrolled agent's completed scan creates an inventory row.

### The CPU benchmark and why it is trustworthy

The challenge is a sequential SHA-256 chain started from a server-generated random value. It cannot be parallelised, so its duration measures single-thread speed. The server computes the same chain to verify the answer and times it from **its own clock** (claim to result). That elapsed time is an upper bound on how long the work took, so the measured speed is a **lower bound on real speed**: a provider can make a machine look slower, never faster. (Network delay also counts against the provider.)

Limit: this proves "some machine answered quickly", not "this specific hardware did". See the proxy attack below.

### Provider consent and the host's condition

The CPU benchmark loads the machine, so `run-scan` respects the provider's own rules (the agent's benchmark gate, `resources/benchmark_gate.py`). It reads the provider's local policy file and refuses to run, **without claiming the challenge** (so the server's timer never starts), unless the provider has set `benchmark_consent`, the host is not paused, a temperature sensor is readable and below the provider's limit, and the 1-minute load is at most 0.5 per core. The command exits with code 4 and logs the reasons. The scan then stays pending until it expires. Because the gate requires a readable temperature sensor, machines without one (common in VMs) cannot currently be scanned; this is an open product decision (ROADMAP).

### What the agent collects

The report (`ScanReport`, example in `packages/contracts/examples/inventory.json`) contains: CPU model and core counts; total and available memory; for each NVIDIA GPU its index, UUID, name, VRAM and driver; free and total space of one configured directory; security capabilities (virtualization flag, `/dev/kvm` presence and usability, cgroup v2 controllers, whether the agent runs as root, confidential-computing CPU flags); OS name, kernel and architecture; and physical network interfaces (name, link speed, up/down). It does not read files, processes, browsing data, user accounts or network traffic.

## Attacks and residual risk

| Attack | Mitigation today | Residual risk |
| --- | --- | --- |
| Hand-written report instead of the agent | Needs the machine's private key and a live, server-issued challenge | A provider who runs a modified agent can still send false hardware facts |
| Replay or tamper with a request | Signature over body, path, nonce, timestamp; nonce store; short skew | None known in the protocol itself |
| Steal an enrolment token | Single use, short lifetime, hashed at rest, shown once | A stolen unused token can enrol the thief's key, so the provider must treat it as a secret |
| Steal the agent's key file | 0600 permissions enforced; re-enrolment revokes the key | Root on the machine can copy it; the thief can only impersonate that machine |
| Inflate CPU speed | Server-side timing makes this impossible | None |
| **Proxy attack:** run the benchmark on a fast machine, sell a slow one | None yet | Real. Mitigated by the planned canary and in-session checks (below) and by TPM attestation |
| **Spoofed hardware:** report 64 cores or 128 GB on a small box, or present a VM as bare metal | None yet; facts are agent-reported | Real. Needs the challenge-verified and attested layers below |
| Fake confidential support | The confidential tier needs platform attestation that does not exist yet, so it cannot be listed | None today; the gate fails closed |
| Make the server burn CPU | One open scan per machine, strict rate limit, bounded iterations, signed requests | Bounded by configuration |

## Designed, not yet implemented

Each layer closes a gap in the table above. None of it exists in code.

1. **Multi-core proof.** The server issues N independent chains (N = claimed cores). The agent commits to all digests, the server picks a random sample to reveal and recomputes only those, and requires the whole job to finish within a bound derived from the single-core time. Strong against claiming more cores than exist.
2. **Memory proof.** A memory-hard computation sized to the claimed RAM, with server-chosen random queries after commitment, timed by the server. Proves the machine can hold the data.
3. **Disk proof.** Fill an allocated area with server-seeded data, then answer random read challenges; timing gives throughput and proves capacity.
4. **Network measurement.** The server streams data to and from the agent and measures throughput, latency and jitter with its own clock, from more than one region. This is fully server-measured.
5. **GPU proof.** Random matrix multiplications checked cheaply with Freivalds' algorithm, timed by the server, plus a VRAM fill-and-sample test; GPU model inferred from timing profile and compared with the report.
6. **TPM 2.0 attestation.** A quote signed by a key chained to the TPM vendor's certificate binds the scan to physical hardware and defeats cloning one agent across machines. Works with firmware TPMs on most modern CPUs.
7. **Confidential computing.** The platform boots a canary confidential guest on the host and verifies its attestation report (AMD VCEK certificate chain, Intel TDX quote, NVIDIA GPU attestation). A pass sets `machines.confidential_verified_at`, which today nothing writes. Re-verification on a schedule; a lapse pauses confidential listings.
8. **Continuous verification.** Rescans at random times, benchmarks re-run inside the actual sandbox at session start (so the measured machine is the serving machine, which defeats the proxy attack), telemetry consistency checks, buyer-reported performance, and economic deterrence (held payouts, reputation, delisting).

## Tiers

- **Standard:** cheaper; no confidentiality guarantee against the provider; the buyer is told so.
- **Confidential:** priced at `AUREN_PRICING_CONFIDENTIAL_PREMIUM_BPS` of the standard base price (both floor and ceiling scale). Listing requires (a) the latest scan reports confidential-computing CPU flags and virtualization, (b) the platform has verified the machine (`confidential_verified_at`), and (c) no GPUs in the offer, because GPU confidentiality cannot be verified yet. A rescan that removes support pauses the listing. Until item 7 above exists, no machine can reach the confidential tier.

The bands for the two tiers can overlap across different machines; the guarantee is per machine: the same offer is always more expensive in the confidential tier.

## Configuration

`AUREN_SCAN_TTL_SECONDS` (request lifetime), `AUREN_SCAN_RESULT_DEADLINE_SECONDS` (time allowed after claim), `AUREN_SCAN_CPU_ITERATIONS` (benchmark size; also the server's verification cost), `AUREN_ENROLLMENT_TTL_SECONDS`, `AUREN_AGENT_REQUEST_MAX_SKEW_SECONDS`. Agent side: `AUREN_AGENT_STATE_DIR`, `AUREN_AGENT_CONTROL_PLANE_URL` (https; http only for loopback), `AUREN_AGENT_ENROLLMENT_TOKEN`.
