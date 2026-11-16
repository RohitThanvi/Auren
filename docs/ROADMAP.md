# Roadmap

Ordering reflects dependencies: later milestones need the earlier ones.

## M0: Foundation (done in this repository)
Monorepo, tooling, shared contracts, Clerk verification, user/role model, rate limiting, health checks, migrations, hardware inventory, minimal frontend, Docker dev stack, CI definition.

## M1: Activation and verification
Activate CI on GitHub; run the Compose stack and fix anything it reveals; add dependency scanning; frontend CSP for the chosen Clerk instance; audited admin workflow to grant `provider`/`admin`.

## M2: Provider registration (backend + agent)
Done (API and agent, no UI): self-service provider role, machine registration, agent enrolment with per-machine keys, signed agent protocol, platform-run scans with a server-timed CPU benchmark, server-side price bands per tier, listing, lifecycle.
To do: provider dashboard and agent installer (Contributor 1 and 2); agent daemon (today scans run on demand via `run-scan`); the verification layers in [SCAN.md](SCAN.md) in priority order: server-measured network, multi-core proof, memory/disk/GPU proofs, TPM attestation. Depends on M1.

## Open product decisions (found while integrating the agent and the platform scan)
- **Sensor-less hosts:** the agent's benchmark gate requires a readable temperature sensor, so VMs and many desktops cannot be scanned. Decide whether to keep that, or allow a provider-acknowledged override for the short scan benchmark.
- **GPU identity:** listings use GPU indices; the agent's policy uses UUIDs. Move listings to UUIDs so a reboot cannot reorder devices.
- **Single source of truth for what is offered:** the provider's local policy (agent) and the listing (API) are separate. The agent should report its policy-bounded capacity and the API should cap listings at it.

## M2b: Confidential tier enablement
Canary confidential guest per host with attestation verification (AMD SEV-SNP, Intel TDX; confidential GPUs later), writing `confidential_verified_at`, scheduled re-verification, pausing lapsed listings. Needs M2 and the workload runtime from M4 for the guest launch. Until then no machine can list in the Confidential tier.

## M3: Marketplace core
Resource requests, matching, allocation with transactional guarantees, tickets, queues, offers. Depends on M2 and DATABASE.md allocation invariants.

## M4: Workload execution
Privileged helper (ADR-0010), Docker workloads with limits, Jupyter/Python environments, usage metering, dataset upload/result retrieval with validated filenames and quotas. Depends on M2/M3.

## M5: Billing
Select gateway (ADR-0006), wallet ledger, metering to charges, signed idempotent webhooks, refunds, settlements, commission, reconciliation. Depends on M3/M4 metering.

## MVP scope
Providers register Linux machines; buyers rent Docker-based Python/Jupyter sessions immediately or via queue; usage is metered; INR top-ups and provider payouts work through one verified gateway. Isolation for untrusted code (microVM) is a gate before opening to the public.

## Deferred
VS Code environments, Windows providers, Go agent, microVM rollout, multi-region scheduling, advanced pricing, provider reputation, automated hardware attestation.
