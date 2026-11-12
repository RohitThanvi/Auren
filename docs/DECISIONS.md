# Architecture decision records

Format: context, decision, alternatives, rationale. New decisions are appended; superseded ones are marked, not deleted.

## ADR-0001: Modular monolith
Decision: one FastAPI application with enforced package boundaries (see ARCHITECTURE.md). Alternatives: microservices. Rationale: three contributors, no proven scaling boundary, transactional allocation and billing need one database. Boundaries permit later extraction.

## ADR-0002: Pyright strict as the single Python type checker
Alternatives: mypy. Rationale: the brief allows either; one choice avoids divergent configs. Pyright's strict mode is fast and catches unknown-type leaks; the same setting is used in API and agent.

## ADR-0003: OpenAPI is the source of truth for shared contracts
Decision: the API exports `openapi.json`; TypeScript types are generated from it; CI fails on drift. Alternatives: hand-maintained shared Zod package; a shared schema language. Rationale: removes the possibility of two contributors defining the same contract differently, and keeps ownership with the backend. Zod validators in the web app are checked against generated types.

## ADR-0004: Bearer tokens, no authentication cookies
Decision: the SPA sends the Clerk JWT in `Authorization`; `credentials: "omit"`. Rationale: no ambient browser credentials, so CSRF does not apply; CORS credentials stay disabled. Trade-off: the token is reachable from JavaScript, so XSS prevention is critical (lint ban on raw HTML, CSP planned).

## ADR-0005: Roles live in PostgreSQL, not in Clerk claims
Rationale: authorisation must be revocable and auditable server-side and must not depend on token contents. Cost: one query per authenticated request (roles are loaded with the user).

## ADR-0006: Payment gateway not yet selected
Context: India-compatible UPI via a gateway such as Razorpay or Cashfree; the brief requires verifying API and account requirements first. Decision: define only the `PaymentProvider` protocol and `Money`; pick a gateway after verification (marketplace/provider payouts, UPI support, webhook signing, KYC for the account holder). No adapter and no fake success path exist.

## ADR-0007: Redis fixed-window rate limiter, fail closed
Decision: atomic Lua `INCR`+`PEXPIRE`; policies configured by environment; 503 when Redis is unreachable unless `AUREN_RATE_LIMIT_FAIL_OPEN=true`. Alternatives: sliding window/token bucket (more precise, more complex). Revisit when abuse patterns are measured.

## ADR-0008: Minimal personal data
Decision: store only the Clerk subject; no email or name. Rationale: smaller breach and compliance surface.

## ADR-0009: Hardware detection behind an interface; Python first
Decision: `HardwareProbe` protocol, `LinuxHardwareProbe` implementation reading `/proc`, `shutil`, and `nvidia-smi` (fixed argv, timeout). A Go agent can replace the implementation later without changing the contract.

## ADR-0010: Privileged host operations separated (planned)
Decision: container/VM lifecycle will live in a separate minimal privileged component; the agent process is unprivileged. Not implemented: no workload execution exists. The interface will be designed with the first workload feature and recorded here.

## ADR-0011: shadcn/ui components added by hand
Context: the shadcn registry was not reachable from the authoring environment. Decision: `components/ui/button.tsx` and `components.json` follow shadcn conventions and were written manually. New components should be added with `npx shadcn@latest add <name>`.

## ADR-0012: CI workflow staged under `docs/ci`
Context: the push token lacked the `workflow` scope. Decision: the workflow is committed at `docs/ci/ci.yml` and must be moved to `.github/workflows/ci.yml` by someone with a token that has the scope. It has not been executed on GitHub.

## ADR-0013: Docker only for the first (trusted) phase; microVM before untrusted workloads
Decision: Docker packaging first; VM/microVM isolation is a release gate for running untrusted buyer code (SECURITY.md).
