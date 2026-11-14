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

## ADR-0014: Self-service providers (no approval gate)
Context: the product is an open market; a provider's device is scanned and the provider lists it. Decision: any signed-in user can enable the provider role. Trade-offs: no vetting, so trust must come from the platform: verified scans (benchmarks), isolation, reputation and limits (machines per provider, rate limits). Until those exist, self-reported hardware claims are not trustworthy and must be labelled so (`verification: self_reported`). Alternative considered: admin approval; rejected by product decision.

## ADR-0015: Platform-computed price band, provider-chosen price
Decision: the platform computes a base price from an operator-configured rate card (no built-in defaults) for the offered allocation, and permits any price between `floor` and `ceiling` basis points of it. GPUs are priced by selected VRAM, a deliberate simplification (no per-model pricing yet). Money is integer minor units; whole GiB only. Alternatives: fully free pricing (no guard against absurd or abusive prices); fixed prices (no market). Revisit GPU pricing when real market data exists.

## ADR-0016: No privacy claim against the provider without attested confidential computing (PROPOSED: needs product decision)
Context and analysis: SECURITY.md, section "Provider cannot see the buyer's work". Containers and microVMs protect the host from the workload, not the workload from the host. A provider with root can read guest memory and disk. Decision proposed: (a) offer a Standard tier with no confidentiality guarantee against the provider and say so in the UI; (b) offer a Confidential tier only on hosts that pass remote attestation (AMD SEV-SNP or Intel TDX, and a confidential-capable GPU for GPU jobs); (c) never use copy such as "your provider cannot see your work" for the Standard tier. Status: proposed, pending owner decision.
