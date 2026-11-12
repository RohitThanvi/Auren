# Auren

A distributed compute marketplace: providers offer idle CPU, RAM, GPU and storage; buyers rent it. Auren orchestrates third-party machines and owns no datacentre.

> **Status: foundation.** The platform skeleton is implemented and tested. Marketplace, scheduling, queues, workload execution and billing are not built yet. [docs/PROJECT.md](docs/PROJECT.md) lists exactly what exists; [docs/ROADMAP.md](docs/ROADMAP.md) lists what comes next.

## Layout

| Path | Contents |
| --- | --- |
| `apps/api` | FastAPI modular monolith: Clerk auth, roles, rate limiting, health, Alembic migrations |
| `apps/agent` | Provider host agent (development mode: hardware inventory only) |
| `apps/web` | React + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query + Clerk |
| `packages/contracts` | OpenAPI document and generated TypeScript types (backend-owned) |
| `infra/`, `docker-compose.yml` | Development PostgreSQL, Redis, migrations, API container |
| `docs/` | Architecture, security, contracts, standards, workflow, roadmap, ADRs |

## Quick start

```bash
cp .env.example .env && cp apps/web/.env.example apps/web/.env.local   # fill in values
make install
docker compose up -d postgres redis
make migrate
make api-run        # terminal 1
make web-dev        # terminal 2
make check          # lint, types, tests, build for every component
```

Full instructions, environment variables and troubleshooting: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Collaboration

Three owners work in parallel with strict boundaries: backend/architect (API, database, contracts, infrastructure), Contributor 1 (frontend), Contributor 2 (provider agent). Read [docs/AGENT_WORKFLOW.md](docs/AGENT_WORKFLOW.md) before changing anything.

## Security

See [docs/SECURITY.md](docs/SECURITY.md), including its list of known limitations. Never commit `.env` files or credentials.
