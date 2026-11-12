# Contributor 1: Frontend

## Ownership

Buyer UI, provider dashboard UI, shared frontend components, frontend integration with the API.

## Files owned

- `apps/web/**` (source, tests, configs, `components.json`, `.env.example`)
- Frontend sections of docs that describe `apps/web` behaviour

## Not owned (request changes from the backend owner)

`packages/contracts/**`, `apps/api/**`, database schema, `docker-compose.yml`, CI, other `docs/` files.

## Boundaries

- Talk to the backend only through `apps/web/src/lib/api` using types from `@auren/contracts`. Add a Zod schema for each response you consume, with `satisfies z.ZodType<...>` against the generated type.
- Never redefine an API type, status code or error shape locally. If the contract is missing something, ask the backend owner.
- No business or pricing logic in the browser: amounts, charges, eligibility and allocation are decided server-side and only displayed.
- No database access, no secrets (`VITE_*` values are public), no `dangerouslySetInnerHTML`, no tokens in URLs or storage you control.
- Treat every API string as untrusted text; render through React only.
- Authentication UI uses Clerk; the API re-verifies everything, so UI gating is convenience, not security.

## Integration rules

- Server state with TanStack Query (`features/<name>/` hooks); routing with React Router; styling with Tailwind and shadcn/ui (`npx shadcn@latest add <component>`).
- Handle `401` (sign in again), `403`, `429` (respect `retryAfterSeconds`) and `503` explicitly in UI.
- Run `make web-check` before every PR (eslint, prettier, tsc, tests with coverage, build). Report the results.
- Backend not ready for your feature? Build against the documented contract and stop; do not add fake API responses to production code.

## Currently available API

`GET /v1/me` only. See [API_CONTRACTS.md](API_CONTRACTS.md).
