# API contracts

## Ownership and source of truth

The backend owner owns every contract. The API's OpenAPI document is the source of truth:

1. Change schemas/routes in `apps/api` (owner only).
2. Run `make contracts` (exports `packages/contracts/openapi.json`, regenerates `packages/contracts/src/schema.d.ts`).
3. Commit the regenerated files in the same change. CI fails if they differ from the code.

Frontend and agent contributors consume contracts; they never edit `packages/contracts` or redefine a type locally. Zod validators in `apps/web/src/lib/api/schemas.ts` are type-checked against the generated types (`satisfies z.ZodType<...>`), so a drift breaks `npm run typecheck`.

## Conventions

- **Versioning:** public routes live under `/v1`. Additive changes (new optional fields, new endpoints) stay in `v1`. Breaking changes require `/v2`, a migration note in CHANGELOG, and a deprecation window. Health endpoints (`/health/*`) are unversioned.
- **Format:** JSON, UTF-8, `snake_case` fields, UUID identifiers, UTC ISO-8601 timestamps, money as integer minor units with an explicit currency code (never floats).
- **Authentication:** `Authorization: Bearer <Clerk session JWT>`. Missing/invalid token -> `401` with `WWW-Authenticate: Bearer`. Insufficient role -> `403`.
- **Request id:** every response has `X-Request-ID`; a client-supplied value matching `[A-Za-z0-9._-]{8,64}` is echoed, anything else replaced.
- **Rate limiting:** `429` with `Retry-After` (seconds).
- **Limits:** request bodies above `AUREN_MAX_REQUEST_BODY_BYTES` -> `413`.

## Error format

All errors, including framework errors (404, 405, 422) and unexpected failures:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests.",
    "request_id": "9f2c...",
    "details": []
  }
}
```

`code` is a stable machine-readable string; `message` is human-readable and safe to display; `details` carries validation entries `{location, message, type}` (never the submitted values). Codes in use: `unauthorized`, `forbidden`, `not_found`, `method_not_allowed`, `validation_error` (422), `bad_request`, `payload_too_large`, `rate_limited`, `service_unavailable`, `internal_error`, `http_error`.

## Pagination (convention for the first list endpoint)

No list endpoints exist yet. When one is added it must use cursor pagination: query `limit` (server default and maximum configured via environment) and `cursor` (opaque); response `{ "items": [...], "next_cursor": string | null }`. Offset pagination is not used on mutable data.

## Current endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health/live` | none | Process is up. |
| GET | `/health/ready` | none | PostgreSQL and Redis reachable; `503` with per-check status otherwise. |
| GET | `/v1/me` | Bearer | Current user `{id, roles}`; provisions the account on first call. |
| POST | `/v1/provider/enable` | Bearer | Self-service: add the `provider` role (idempotent, strict rate limit). |
| POST | `/v1/provider/machines` | Provider | Register a machine `{name}` (limit per provider). |
| GET | `/v1/provider/machines` | Provider | List own machines with latest scan summary and listing (bounded list, not paginated). |
| GET | `/v1/provider/machines/{id}` | Provider | One own machine. |
| PUT | `/v1/provider/machines/{id}/inventory` | Provider | Submit a hardware scan (strict schema, see below). |
| POST | `/v1/provider/machines/{id}/price-range` | Provider | Price band `{base, floor, ceiling}` for an offered allocation. |
| PUT | `/v1/provider/machines/{id}/listing` | Provider | List at a price inside the band. |
| POST | `/v1/provider/machines/{id}/pause` `/resume` `/withdraw` | Provider | Lifecycle. |

Provider endpoints return `404 machine_not_found` for machines the caller does not own.

### Provider-specific error codes

`machine_name_taken` (409), `machine_limit_reached` (409), `invalid_state_transition` (409), `machine_withdrawn` (409), `machine_not_found` (404), `inventory_required` (422), `allocation_exceeds_capacity` (422), `price_out_of_range` (422), `max_hosting_hours_exceeded` (422), `listing_required` (422).

### Scan contract

The scan body is exactly the JSON printed by `python -m auren_agent scan`. Request models are **strict**: unknown fields and wrongly typed values (e.g. a price sent as a string) are rejected, and free-text fields reject control characters. `packages/contracts/examples/inventory.json` is a shared example: the agent test suite and the API test suite both must accept it, so neither side can change the shape alone. Money amounts are integer minor units. Capacity facts are labelled `verification: "self_reported"`.
