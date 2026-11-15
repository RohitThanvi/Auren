# Changelog

Meaningful project changes, newest first. Only shipped behaviour is listed.

## Unreleased: foundation

### Added (platform-run scan and tiers)
- Per-machine Ed25519 identity: one-time enrolment tokens (hashed, short-lived, single use), weak-key rejection, signed agent requests with replay protection (`AUREN-AGENT-V1`), shared signing test vector.
- Platform-run scans: provider requests, enrolled agent claims a server-generated challenge and submits a signed result; server-timed, server-verified CPU benchmark; one open scan per machine; results single use. Provider-submitted inventory removed.
- Standard and Confidential tiers with separate price bands (`AUREN_PRICING_CONFIDENTIAL_PREMIUM_BPS`); confidential listings gated on reported support, platform attestation (not yet obtainable) and no GPUs.
- Agent commands `enroll` and `run-scan`; private key stored with 0600 permissions; https required for the control plane (http for loopback only).
- Design document `docs/SCAN.md` (trust model, implemented protocol, attack table, planned verification layers).

### Added (provider marketplace foundation)
- Self-service provider role (`POST /v1/provider/enable`), machine registration with per-provider limit, append-only scan history, server-computed price range and listing inside the range, pause/resume/withdraw, automatic pause when a rescan invalidates a listing. Migration `0002`.
- Required pricing configuration (`AUREN_PRICING_*`) with no built-in defaults; `AUREN_PROVIDER_*` limits.
- (superseded by the platform-run scan above) Agent scan now also reports platform/kernel, KVM availability, hardware virtualization, confidential-computing CPU flags and physical network interfaces with link speed.
- Shared example scan `packages/contracts/examples/inventory.json` validated by both agent and API tests.
- Strict request validation (unknown fields and wrong types rejected).

### Added (foundation)
- Monorepo layout: `apps/api`, `apps/agent`, `apps/web`, `packages/contracts`, `infra`, `docs`.
- API: application factory with validated environment configuration; structured JSON logging; health (`/health/live`, `/health/ready`) endpoints; consistent error format; request ids; security headers; explicit CORS; request body size limit.
- API: Clerk JWT verification (RS256/JWKS, issuer, expiry, not-before, authorised party, optional audience) and role-based authorisation (`require_roles`, roles stored in PostgreSQL).
- API: `GET /v1/me`, which provisions the user (default role `buyer`) on first use.
- API: Redis-backed rate limiting with seven configurable policies, `429` + `Retry-After`, trusted-proxy-aware client IP, fail-closed by default.
- Database: SQLAlchemy 2 models, Alembic migration `0001` (`users`, `user_roles`) with constraint naming convention.
- `Money` value object (integer minor units) and the `PaymentProvider` protocol; no gateway selected.
- Provider agent: development mode with Linux hardware probe (CPU, memory, NVIDIA GPUs, storage) and `scan`/`run` commands.
- Web: Vite + React + TypeScript + Tailwind + shadcn-style Button, Clerk sign-in, TanStack Query, protected dashboard, validated environment and API responses.
- Contracts: OpenAPI export and generated TypeScript types with CI drift check.
- Docker Compose (PostgreSQL, Redis, one-shot migrations, API), API Dockerfile (non-root).
- Tooling: Ruff, Pyright strict, ESLint strict, Prettier, pytest, Vitest, Makefile.
- CI workflow definition at `docs/ci/ci.yml` (not yet active; see ADR-0012).
- Documentation set under `docs/`.
