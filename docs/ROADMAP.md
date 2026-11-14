# Roadmap

Ordering reflects dependencies: later milestones need the earlier ones.

## M0: Foundation (done in this repository)
Monorepo, tooling, shared contracts, Clerk verification, user/role model, rate limiting, health checks, migrations, hardware inventory, minimal frontend, Docker dev stack, CI definition.

## M1: Activation and verification
Activate CI on GitHub; run the Compose stack and fix anything it reveals; add dependency scanning; frontend CSP for the chosen Clerk instance; audited admin workflow to grant `provider`/`admin`.

## M2: Provider registration (backend + agent)
Done: self-service provider role, machine registration, scan intake, server-side price band, listing, lifecycle (API only; no UI).
To do: agent protocol and per-machine credentials (today a scan is submitted with the provider's own user session), benchmark verification of self-reported specs (CPU/memory/disk/network throughput measured by the platform), provider dashboard UI (Contributor 1), agent-side network throughput and latency probes. Depends on M1.

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
