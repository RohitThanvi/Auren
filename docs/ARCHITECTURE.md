# Architecture

## Components

```
Browser (apps/web) --HTTPS, Bearer Clerk JWT--> API (apps/api) --> PostgreSQL
                                                  |  \--> Redis (rate limits)
Provider host (apps/agent) --outbound HTTPS, Ed25519-signed requests--> API   (enrol + scan implemented)
```

| Component | Path | State |
| --- | --- | --- |
| API (modular monolith, FastAPI) | `apps/api` | Foundation implemented |
| Provider agent (Python) | `apps/agent` | Hardware scan, enrolment, signed scan protocol; no workloads |
| Web (React, Vite) | `apps/web` | Home, sign-in, dashboard |
| Shared contracts | `packages/contracts` | Types generated from the API's OpenAPI document |
| Dev infrastructure | `docker-compose.yml`, `infra/` | PostgreSQL, Redis, migrations, API |

## API module boundaries (`apps/api/src/auren_api`)

| Package | Responsibility | May depend on |
| --- | --- | --- |
| `api/` | HTTP routes, dependencies, middleware. No business logic. | services, schemas, auth, errors, infrastructure |
| `auth/` | Token verification (`clerk.py`), `Principal`. | config |
| `domain/` | Pure rules and value objects (`Role`, `Money`). No I/O. | nothing |
| `services/` | Application use cases; own transaction boundaries. | repositories, domain |
| `repositories/` | Persistence. Only place that builds queries. | models, domain |
| `models/` | SQLAlchemy models. | domain |
| `schemas/` | Pydantic request/response models (public contract). | domain |
| `infrastructure/` | Database, Redis, rate limiter, payment provider protocol. | config, domain |
| `config.py`, `logging.py`, `errors.py`, `container.py`, `main.py` | Cross-cutting wiring. | -- |

Dependencies point inward (api -> services -> repositories -> models/domain). There are no cycles. Background jobs are not implemented yet; when added they live in a `jobs/` package calling services, never routes.

## Provider onboarding and pricing (implemented)

`api/v1/provider.py` -> `services/provider.ProviderService` -> `repositories/machines.py`. Rules live in `domain/`:

- `domain/inventory.py`: `InventorySnapshot` and `check_allocatable` (an offer must fit inside the scanned machine, capped at `AUREN_PROVIDER_MAX_ALLOCATABLE_BPS` of CPU, memory and storage; GPUs are selected by index).
- `domain/pricing.py`: `price_range` from a `RateCard` (per core-hour, GiB-hour of memory, GiB-hour of GPU VRAM, 100 GiB-hour of storage), floor and ceiling in basis points. Integer arithmetic only; partial GiB are not billed.
- `domain/machine.py`: `registered -> listed <-> paused`, any non-withdrawn state `-> withdrawn` (terminal); `ListingTier` (standard, confidential).
- `domain/scan.py`: scan challenge (SHA-256 chain) and the speed derived from server-measured time.
- `auth/agent.py`: request signing, canonical message, weak-key rejection. `api/deps.get_agent_principal` authenticates agent requests (signature, skew, single-use nonce).
- `services/agent.py`: enrolment, claim, verified result intake. `services/listing_rules.py`: rules shared by the provider and agent services.
- Inventories exist only as the result of a completed platform scan (append-only; the newest is current). A new scan that no longer supports an existing listing (capacity, price band or tier requirements) pauses the machine automatically. Full scan design: [SCAN.md](SCAN.md).
- Every machine query is scoped by `owner_user_id`; another user's machine returns the same 404 as a missing one.
- Machine mutations lock the machine row (`SELECT ... FOR UPDATE`); the per-provider machine limit locks the owner row so concurrent creates cannot exceed it.

Only machines with status `listed` may ever be offered to buyers. No buyer-facing discovery exists yet.

## Dependency injection

`main.create_app` builds a frozen `Container` (settings, DB engine, session factory, Redis, HTTP client, token verifier, rate limiter) during lifespan. Routes obtain it through FastAPI dependencies in `api/deps.py`. Tests replace container members with `dataclasses.replace`.

## Request flow

1. `SecurityHeadersMiddleware` (outermost) -> CORS -> `RequestContextMiddleware` (request id, access log, converts crashes to a generic 500) -> `BodySizeLimitMiddleware`.
2. Router-level IP rate limit (`anonymous` policy) on all `/v1` routes.
3. `get_principal`: verify bearer token, load/provision the user, load roles from PostgreSQL.
4. Per-user rate limit, then the handler, which calls a service.

Health endpoints are outside `/v1`, unauthenticated and not rate limited.

## Authentication flow

1. The SPA signs the user in with Clerk and obtains a session JWT.
2. The SPA sends `Authorization: Bearer <jwt>` (no cookies; `credentials: "omit"`).
3. The API verifies RS256 signature against Clerk's JWKS (cached, refresh throttled), `iss`, `exp`, `nbf`, `iat`, `sub`, `azp` against `AUREN_CLERK_AUTHORIZED_PARTIES`, and `aud` when configured.
4. The verified `sub` maps to a `users` row (created on first use with role `buyer`).

Authorisation is separate: `require_roles(...)` denies unless the stored roles intersect the allowed set.

## Planned (not implemented)

These sections describe intended design so contributors build toward one model. None of it exists in code yet.

- **Provider agent communication, remaining parts:** today the agent polls over signed HTTPS (claim a scan, submit a result). Workload commands (start/stop sandbox, usage reports) and a push channel (WebSocket or gRPC stream) are not implemented; every command must remain a typed, allow-listed message, never a shell string, with the schema defined by the backend owner in `docs/` first.
- **Execution lifecycle:** requested -> matched -> provisioning -> running -> terminating -> terminated/failed, persisted with explicit state-transition rules and a unique active allocation per resource.
- **Queue architecture:** tickets for unmatched requests, queue positions with estimates only (no guarantee), offers with expiry that a buyer accepts or rejects; allocation in a single database transaction with row locking.
- **Billing architecture:** append-only double-entry wallet ledger in integer minor units, usage metering records, gateway transactions behind `PaymentProvider`, idempotency keys, signed-webhook verification, duplicate-event handling, refunds, provider settlements, platform commission, reconciliation. Invariants in [DATABASE.md](DATABASE.md).
