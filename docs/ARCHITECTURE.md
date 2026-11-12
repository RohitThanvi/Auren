# Architecture

## Components

```
Browser (apps/web) --HTTPS, Bearer Clerk JWT--> API (apps/api) --> PostgreSQL
                                                  |  \--> Redis (rate limits)
Provider host (apps/agent) --outbound TLS--> API   (protocol: NOT YET IMPLEMENTED)
```

| Component | Path | State |
| --- | --- | --- |
| API (modular monolith, FastAPI) | `apps/api` | Foundation implemented |
| Provider agent (Python) | `apps/agent` | Hardware inventory only; no network, no workloads |
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

- **Provider agent communication:** agent opens an outbound mTLS/TLS WebSocket or gRPC stream to the API; registration uses a one-time enrolment token exchanged for a per-machine credential; every command is a typed, allow-listed message (never a shell string). The message schema will be defined by the backend owner in `docs/` before either side implements it.
- **Execution lifecycle:** requested -> matched -> provisioning -> running -> terminating -> terminated/failed, persisted with explicit state-transition rules and a unique active allocation per resource.
- **Queue architecture:** tickets for unmatched requests, queue positions with estimates only (no guarantee), offers with expiry that a buyer accepts or rejects; allocation in a single database transaction with row locking.
- **Billing architecture:** append-only double-entry wallet ledger in integer minor units, usage metering records, gateway transactions behind `PaymentProvider`, idempotency keys, signed-webhook verification, duplicate-event handling, refunds, provider settlements, platform commission, reconciliation. Invariants in [DATABASE.md](DATABASE.md).
