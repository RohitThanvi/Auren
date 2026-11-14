# Security

## Threat model (summary)

| Actor | Threat | Mitigation status |
| --- | --- | --- |
| Anonymous internet user | Brute force, scraping, request floods | Redis rate limits per IP; body size cap; deny-by-default auth. **Implemented.** |
| Authenticated buyer | Access another user's data (IDOR/BOLA) | Authorisation from stored roles; ownership checks required on every resource query. **Pattern defined; no user-owned resources exist yet.** |
| Malicious buyer workload | Escape sandbox, attack host or other tenants | Not applicable until workloads exist. Design requirements below. **Not implemented.** |
| Malicious or curious provider | Read the buyer's code, data and results; tamper with results; lie about hardware; abandon sessions | Not mitigated today (no workloads exist). Reading buyer data cannot be prevented by containers or microVMs: see the next section. Scans are labelled `self_reported`; benchmark verification, attestation and redundancy are planned. |
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

## Provider cannot see the buyer's work: what can honestly be promised

This is the product's central security goal, so the limits of each technology matter. Whoever controls the host operating system controls what runs on it.

| Isolation | Protects | Does **not** protect |
| --- | --- | --- |
| Docker/containers | Host from a normal workload (with hardening) | Workload from the provider: root on the host can read container files and process memory. |
| gVisor, Kata, Firecracker microVMs | Host and other tenants from a malicious workload (stronger boundary) | Workload from the provider: the provider runs the hypervisor and can dump guest memory and inspect disk images and network traffic. |
| Confidential VMs (AMD SEV-SNP, Intel TDX) with remote attestation | Guest memory is encrypted against the host and hypervisor; the buyer can verify what is running before releasing keys | Side channels, timing and traffic metadata; requires encrypted storage and I/O keyed only after attestation. |
| Confidential GPUs (NVIDIA Hopper/Blackwell confidential mode) | GPU memory and PCIe traffic against the host | Consumer GPUs (e.g. GeForce) have no such mode: data in VRAM is visible to the host. |

Consequences for the product:

1. Only the confidential row can deliver "the provider cannot see your work", and only on hosts that pass attestation. Consumer hardware, which a free market of individual providers will mostly be, cannot offer it today.
2. The agent scan reports CPU flags such as `sev_snp` and `tdx_host_platform` and `/dev/kvm`. These are **indicators of possible support**, not proof that a workload is protected. Nothing may be advertised as confidential from a scan alone.
3. Proposed policy (ADR-0016, pending decision): a Standard tier with an explicit "the provider may be able to access your workload" notice, and a Confidential tier available only on attested hosts. Until then, user-facing text must not promise provider-proof privacy.
4. Measures that reduce exposure without guaranteeing privacy: ephemeral disks, per-job encryption keys held by the buyer, no host mounts into the workload, minimal metadata sent to providers, redundancy or spot verification for integrity.
5. Integrity is separate from confidentiality: a provider can return wrong results. Verification (redundant execution, sampling) is a later milestone.

## Workload isolation (requirements)

Docker for the first trusted phase; **untrusted customer workloads require VM/microVM isolation before general availability**. Never privileged containers, never the Docker socket in a workload, resource limits on every workload, workloads separated from control-plane software, no provider host terminals.

## Data handling

Only the Clerk subject is stored per user (no email, name or payment data). Card numbers, UPI PINs and gateway secrets are never stored. Logs exclude query strings, tokens and request bodies.

## Known limitations

- No workload execution, isolation, agent protocol or marketplace code exists; their security properties are unverified by construction.
- The `AUTH` rate-limit policy protects only `POST /v1/provider/enable`; the other reserved policies (`ticket_creation`, `session_creation`, `upload`, `expensive`) are configurable but not yet attached to endpoints; failed-authentication throttling is not implemented.
- Fixed-window limiting allows up to 2x burst across a window boundary.
- Providers are self-service by design (ADR-0014), so there is no vetting: capacity claims are self-reported and unverified (price bands derived from a falsified scan would be wrong), and nothing stops one person registering many accounts. The `admin` role can only be granted directly in the database; there is no admin workflow.
- A scan is submitted with the provider's own user session, not a per-machine credential, so the platform cannot yet tell a real agent from a hand-written request.
- No benchmark verification, attestation, or result-integrity checking exists.
- The frontend ships no Content-Security-Policy yet: Clerk requires allow-listing the instance's frontend API domain, which must be done per deployment.
- The Docker/Compose stack and CI workflows have not been executed in the authoring environment (no Docker, push token lacked `workflow` scope).
- No dependency vulnerability scanning in CI yet.
