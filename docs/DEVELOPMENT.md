# Development

## Prerequisites

Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+ (22 recommended), Docker with Compose v2, GNU Make.

## Local setup

```bash
cp .env.example .env                              # then edit (see below)
cp apps/web/.env.example apps/web/.env.local      # Clerk publishable key + API URL
make install                                      # uv sync (api, agent) + npm ci
docker compose up -d postgres redis               # infrastructure only
make migrate                                      # apply Alembic migrations
make api-run                                      # API on http://127.0.0.1:8000
make web-dev                                      # frontend on http://localhost:5173
```

Edit `.env`: set `POSTGRES_PASSWORD` (URL-safe characters only: it is embedded in connection URLs), replace `<POSTGRES_PASSWORD>` in `AUREN_DATABASE_URL` and `AUREN_TEST_DATABASE_URL`, and set `AUREN_CLERK_ISSUER` from your Clerk dashboard (Frontend API URL). The default `AUREN_CLERK_AUTHORIZED_PARTIES=http://localhost:5173` matches the Vite dev server.

Full stack in containers instead (PostgreSQL, Redis, one-shot migrations, API): `make up`. The frontend is always run with `make web-dev`.

## Environment variables

Configuration is validated at startup; the process refuses to start on invalid values. Authoritative list with defaults: `apps/api/src/auren_api/config.py` and `.env.example`.

| Variable | Purpose |
| --- | --- |
| `AUREN_ENVIRONMENT` | `development`, `test` or `production` (production hides OpenAPI, enables HSTS, requires authorized parties) |
| `AUREN_DATABASE_URL` / `AUREN_REDIS_URL` | Connections (`postgresql+asyncpg://`, `redis://`) |
| `AUREN_CORS_ALLOWED_ORIGINS` | Comma-separated explicit origins (no wildcards) |
| `AUREN_CLERK_ISSUER`, `AUREN_CLERK_AUTHORIZED_PARTIES`, `AUREN_CLERK_AUDIENCE` | Token verification |
| `AUREN_TRUSTED_PROXY_COUNT` | Reverse proxies in front of the API (0 = ignore `X-Forwarded-For`) |
| `AUREN_RATE_LIMIT_<POLICY>` | `<requests>/<window_seconds>` for `ANONYMOUS`, `AUTHENTICATED`, `AUTH`, `TICKET_CREATION`, `SESSION_CREATION`, `UPLOAD`, `EXPENSIVE` |
| `AUREN_RATE_LIMIT_FAIL_OPEN` | Allow requests when Redis is down (default `false`) |
| `AUREN_DB_*`, `AUREN_MAX_REQUEST_BODY_BYTES`, `AUREN_*_TIMEOUT_SECONDS` | Pool sizes, statement timeout, body cap, timeouts |
| `AUREN_TEST_DATABASE_URL` / `AUREN_TEST_REDIS_URL` | Used only by the test suite; database name must end in `_test` |
| `AUREN_AGENT_*` | Agent mode (`development` only), storage path, log level, GPU probe timeout |
| `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_API_BASE_URL` | Frontend build-time configuration (public values only) |

## Tests and checks

```bash
make check          # everything below
make api-check      # ruff, ruff format --check, pyright (strict)
make api-test       # pytest + coverage against real PostgreSQL/Redis
make agent-check    # ruff, pyright, pytest
make web-check      # eslint, prettier, tsc, vitest + coverage, build
make contracts      # regenerate shared contracts after API changes
```

CI definition: `docs/ci/ci.yml` (see [DECISIONS.md](DECISIONS.md), ADR-0012, for why it is not under `.github/workflows` yet).

## Provider agent

```bash
cd apps/agent
AUREN_AGENT_MODE=development AUREN_AGENT_STORAGE_PATH=/tmp uv run python -m auren_agent scan
AUREN_AGENT_MODE=development AUREN_AGENT_STORAGE_PATH=/tmp uv run python -m auren_agent run
```

`scan` prints the inventory as JSON; `run` logs it and exits (no network, no workloads in development mode).

## Troubleshooting

- **`pytest` exits with "AUREN_TEST_DATABASE_URL must be set"**: export the variables from `.env` (`make api-test` does this) and ensure the test database exists. The init script creates `<POSTGRES_DB>_test` only when the Postgres volume is first created; otherwise run `docker compose exec postgres createdb -U "$POSTGRES_USER" auren_test`.
- **API fails at startup with a validation error**: the message names the setting. Common causes: URL scheme (must be `postgresql+asyncpg://`), a wildcard in CORS origins, missing `AUREN_CLERK_ISSUER`.
- **`/health/ready` returns 503**: the body shows which dependency failed; check `docker compose ps`.
- **`401` from `/v1/me` with a valid Clerk login**: `AUREN_CLERK_AUTHORIZED_PARTIES` must contain the exact frontend origin (the token's `azp` claim), and `AUREN_CLERK_ISSUER` must be your instance's Frontend API URL.
- **Browser CORS error**: add the frontend origin to `AUREN_CORS_ALLOWED_ORIGINS`.
- **`429` during development**: raise the relevant `AUREN_RATE_LIMIT_*` locally or clear counters with `docker compose exec redis redis-cli flushdb`.
- **Compose fails with "set in .env"**: that variable is required; compose will not start with missing credentials by design.
