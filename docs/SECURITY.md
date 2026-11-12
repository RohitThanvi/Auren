# Security

## Threat model (summary)

| Actor | Threat | Mitigation status |
| --- | --- | --- |
| Anonymous internet user | Brute force, scraping, request floods | Redis rate limits per IP; body size cap; deny-by-default auth. **Implemented.** |
| Authenticated buyer | Access another user's data (IDOR/BOLA) | Authorisation from stored roles; ownership checks required on every resource query. **Pattern defined; no user-owned resources exist yet.** |
| Malicious buyer workload | Escape sandbox, attack host or other tenants | Not applicable until workloads exist. Design requirements below. **Not implemented.** |
| Malicious provider | Read buyer data, fake capacity | Hardware attestation, benchmark verification, encrypted data paths. **Not implemented; acknowledged limitation.** |
| Network attacker | Token theft, tampering | TLS required at the edge; HSTS in production; bearer tokens short-lived (Clerk). |
| Compromised frontend (XSS) | Token theft | No `dangerouslySetInnerHTML` (ESLint-enforced); React escaping; CSP pending (see limitations). |

## Trust boundaries

1. Browser <-> API: untrusted client. The API trusts only a verified JWT, then re-derives roles from PostgreSQL.
2. API <-> provider agent: providers are untrusted third parties. (Protocol not yet built.)
3. Buyer workload <-> provider host: buyer code is untrusted and must never run on the provider's host OS.
4. API <-> payment gateway: gateway events are untrusted until the signature is verified.

## Authentication (implemented)

Clerk issues the JWT; the API verifies it on every request (`auth/clerk.py`): RS256 only (`none`/HS256 rejected), `kid` required, signature via JWKS, issuer, expiry, not-before, issued-at, subject, `azp` allow-list (required in production), optional audience. JWKS responses are cached; unknown `kid` refreshes are throttled so attackers cannot force fetch storms; stale keys are served if Clerk is briefly unreachable. Failures return a generic 401; the reason is logged, never returned.

## Authorisation (implemented)

Deny by default. Roles live in `user_roles`, never in token claims (a test asserts a token claiming `admin` stays `buyer`). Handlers requiring a role use `require_roles`. **Rule for all future resources:** every query for a user-owned object must filter by owner or check an explicit permission in the repository; UUID secrecy is never authorisation.

## Input, web and infrastructure controls (implemented)

- Pydantic validation on all inputs; Zod validation of environment and API responses on the frontend.
- SQL only through SQLAlchemy expressions (parameterised); no string-built SQL; no shell use with API input.
- CORS: explicit origins only, wildcards rejected at startup, credentials disabled.
- Headers: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, API CSP `default-src 'none'`, `Cache-Control: no-store`, HSTS in production. Applied to error responses too.
- No cookies are used for authentication, so CSRF does not apply. If cookie auth is ever introduced, CSRF protection becomes mandatory first.
- OpenAPI endpoint is disabled in production. Secrets only via environment; settings use `SecretStr`; `.env` is git-ignored.
- Rate limits: configurable per policy via `AUREN_RATE_LIMIT_*`; 429 with `Retry-After`; fail-closed when Redis is down unless `AUREN_RATE_LIMIT_FAIL_OPEN=true`. Client IP honours `X-Forwarded-For` only up to `AUREN_TRUSTED_PROXY_COUNT`.
- API container runs as non-root, read-only filesystem, all capabilities dropped.

## Host-agent security (requirements; agent currently makes no network calls)

- Outbound authenticated TLS only; no inbound ports on provider machines.
- The agent exposes no generic execution; the backend can request only typed, allow-listed operations.
- Privileged operations (container/VM lifecycle) must live in a separate, minimal component with its own least-privilege boundary; the unprivileged agent cannot reach the host Docker socket directly.
- Hardware detection runs `nvidia-smi` with a fixed argument list and timeout, never a shell.

## Workload isolation (requirements)

Docker for the first trusted phase; **untrusted customer workloads require VM/microVM isolation before general availability**. Never privileged containers, never the Docker socket in a workload, resource limits on every workload, workloads separated from control-plane software, no provider host terminals.

## Data handling

Only the Clerk subject is stored per user (no email, name or payment data). Card numbers, UPI PINs and gateway secrets are never stored. Logs exclude query strings, tokens and request bodies.

## Known limitations

- No workload execution, isolation, agent protocol or marketplace code exists; their security properties are unverified by construction.
- The `AUTH` and other reserved rate-limit policies are configurable but not yet attached to endpoints; failed-authentication throttling is not implemented.
- Fixed-window limiting allows up to 2x burst across a window boundary.
- Provider/admin roles can only be granted directly in the database; there is no audited admin workflow yet.
- The frontend ships no Content-Security-Policy yet: Clerk requires allow-listing the instance's frontend API domain, which must be done per deployment.
- The Docker/Compose stack and CI workflows have not been executed in the authoring environment (no Docker, push token lacked `workflow` scope).
- No dependency vulnerability scanning in CI yet.
