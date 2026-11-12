# Coding standards

## Python (apps/api, apps/agent)

- Python 3.12, full type annotations, **Pyright in strict mode** (`pyproject.toml`). `# pyright: ignore[rule]` only with the rule named and a reason.
- Ruff for lint and format (line length 100). Relative imports are banned; use absolute `auren_api.*` imports.
- Naming: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`, no abbreviations that are not industry standard.
- No business logic in route handlers; no SQL outside repositories; no I/O in `domain/`.
- No broad `except Exception` that swallows errors. The only places allowed to catch broadly are the readiness probes and the request-context middleware, which log with traceback and return a safe failure.
- No magic numbers: operational limits come from `Settings`; protocol constants get a named constant.
- No unexplained TODOs: a TODO must name an issue or ADR.
- No fake data or mock behaviour in production paths. Test doubles live under `tests/` only.
- Logging: `structlog`, key/value events (`logger.info("event_name", key=value)`); never log tokens, secrets, request bodies or query strings.
- Subprocesses: fixed argv, no shell, timeout (see `LinuxHardwareProbe`).

## TypeScript (apps/web)

- `strict` plus `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`; ESLint `strictTypeChecked`; Prettier.
- No `any`, no `dangerouslySetInnerHTML` (lint error). Components render text through React.
- Validate every external input with Zod (environment, API responses). No database or business rules in components; data access goes through `features/*` hooks and `lib/api`.
- Server state through TanStack Query; no secrets in `VITE_*` variables.
- UI primitives follow shadcn/ui conventions (`components/ui`, `cn`, `cva`).

## Testing

- API tests use real PostgreSQL and Redis; only Clerk's JWKS endpoint is faked (it is an external service). The suite refuses to run against a database whose name does not end in `_test`.
- Every behaviour change needs tests, including failure paths and security cases (forged/expired tokens, spoofed headers, concurrency).
- Coverage gates: API and agent 90% (`fail_under`), web thresholds in `vite.config.ts`.
- A bug fix starts with a failing test.

## Error handling

Raise `AppError` subclasses for expected client-visible failures; they map to the documented error format. Unexpected exceptions become a generic 500 with a request id; internal text is never returned.

## Security conventions

See [SECURITY.md](SECURITY.md). In review, check: authorisation on every new route, owner filter on every user-owned query, input limits, no secrets in code or logs, rate-limit policy chosen for every new endpoint.

## Commits

Conventional style (`feat(api): ...`, `fix(web): ...`, `docs: ...`), one logical change each, documentation updated in the same commit as the behaviour.
