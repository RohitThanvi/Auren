# Project scope

Auren is a distributed compute marketplace. Individuals and organisations (providers) offer idle CPU, RAM, GPU and storage; buyers rent it. Auren owns no datacentre: it orchestrates third-party machines.

> **Status:** foundation only. This repository currently contains the platform skeleton (authentication, authorisation, rate limiting, health checks, migrations, hardware inventory in the agent, a minimal frontend). The marketplace features below are the product goal, not shipped behaviour. See [ROADMAP.md](ROADMAP.md).

## Roles

| Role | Description | Today |
| --- | --- | --- |
| `buyer` | Rents compute. Every new account gets this role. | Stored in DB, assigned on first sign-in. |
| `provider` | Hosts compute through the host agent. | Role exists; no API grants it yet (DB only). |
| `admin` | Operates the platform. | Role exists; no API grants it yet (DB only). |

Roles are stored in PostgreSQL and never read from token claims.

## Target features

Buyers: discover compatible providers; request CPU/RAM/GPU/storage, duration, budget and security requirements; rent available compute immediately; receive a waiting ticket when nothing compatible is free; join queues with estimated availability and no guaranteed allocation; accept or reject offers; launch Python, JupyterLab and later VS Code environments; monitor usage and billing; upload datasets and fetch results.

Providers: install the provider application and host agent; register and benchmark machines; declare availability, maximum hosting duration and allocatable resources; view sessions and utilisation; pause or withdraw; track earnings.

## Initial workloads

Python and JupyterLab environments packaged as Docker images. VS Code later. Linux providers first.

## Implemented now

- API: `/health/live`, `/health/ready`, `GET /v1/me` (Clerk-authenticated, provisions the user).
- Provider agent: development mode that detects CPU, memory, NVIDIA GPUs and storage (`scan`, `run`).
- Frontend: public home page, Clerk sign-in, protected dashboard that shows the caller's roles.

## Non-goals (initial release)

Windows providers, microVM isolation, a provider-side privileged helper, multi-region scheduling, direct handling of card/UPI credentials, microservices, a custom authentication system. Each is deferred, not rejected; see ROADMAP.
