# Changelog

Meaningful project changes, newest first. Only shipped behaviour is listed.

## Unreleased: foundation

### Added
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
