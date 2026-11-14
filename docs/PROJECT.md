# Project scope

Auren is a distributed compute marketplace. Individuals and organisations (providers) offer idle CPU, RAM, GPU and storage; buyers rent it. Auren owns no datacentre: it orchestrates third-party machines.

> **Status:** foundation only. This repository currently contains the platform skeleton (authentication, authorisation, rate limiting, health checks, migrations, hardware inventory in the agent, a minimal frontend). The marketplace features below are the product goal, not shipped behaviour. See [ROADMAP.md](ROADMAP.md).

## Roles

| Role | Description | Today |
| --- | --- | --- |
| `buyer` | Rents compute. Every new account gets this role. | Stored in DB, assigned on first sign-in. |
| `provider` | Hosts compute through the host agent. Self-service: any signed-in user can enable it (`POST /v1/provider/enable`); there is no approval step. | Implemented. |
| `admin` | Operates the platform. | Role exists; no API grants it yet (DB only). |

Roles are stored in PostgreSQL and never read from token claims.

## Target features

Buyers: discover compatible providers; request CPU/RAM/GPU/storage, duration, budget and security requirements; rent available compute immediately; receive a waiting ticket when nothing compatible is free; join queues with estimated availability and no guaranteed allocation; accept or reject offers; launch Python, JupyterLab and later VS Code environments; monitor usage and billing; upload datasets and fetch results.

Providers: install the provider application and host agent; register and benchmark machines; declare availability, maximum hosting duration and allocatable resources; view sessions and utilisation; pause or withdraw; track earnings.

## Initial workloads

Python and JupyterLab environments packaged as Docker images. VS Code later. Linux providers first.

## Provider model: a free market inside a platform-computed band

1. A provider enables the provider role and registers a machine.
2. The agent scans the device (CPU, memory, GPUs, storage, network, platform, virtualization and confidential-computing indicators) and the scan is submitted.
3. The platform computes a **price range** for the resources the provider chooses to offer, from an operator-configured rate card.
4. The provider lists the machine at **any price inside that range**. Outside the range is rejected server-side.
5. The provider can pause, resume or withdraw at any time.

Scans are **self-reported** until benchmark verification exists (ROADMAP M2). Pricing and listings are implemented; matching buyers to listings is not.

## Implemented now

- API: `/health/live`, `/health/ready`, `GET /v1/me` (Clerk-authenticated, provisions the user).
- API: self-service provider role, machine registration, scan intake, server-side price range, listing at a price inside the range, pause/resume/withdraw.
- Provider agent: development mode that detects CPU, memory, NVIDIA GPUs, storage, platform/KVM, confidential-computing CPU flags and network interfaces (`scan`, `run`).
- Frontend: public home page, Clerk sign-in, protected dashboard that shows the caller's roles.

## Privacy goal and its honest limits

The product goal is a sandbox in which the provider cannot see the buyer's work. Whether that can be promised depends on the isolation technology, see [SECURITY.md](SECURITY.md#provider-cannot-see-the-buyers-work-what-can-honestly-be-promised). Until confidential computing with attestation exists, user-facing text must not claim the provider cannot see a workload.

## Non-goals (initial release)

Windows providers, microVM isolation, a provider-side privileged helper, multi-region scheduling, direct handling of card/UPI credentials, microservices, a custom authentication system. Each is deferred, not rejected; see ROADMAP.
