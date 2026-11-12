# Working with AI agents and contributors

Three contributors (human or AI) work in parallel. These rules prevent conflicting changes.

## Required reading before any task

1. [PROJECT.md](PROJECT.md): scope and what is implemented.
2. [ARCHITECTURE.md](ARCHITECTURE.md) and [SECURITY.md](SECURITY.md).
3. [CODING_STANDARDS.md](CODING_STANDARDS.md).
4. [API_CONTRACTS.md](API_CONTRACTS.md) and [DATABASE.md](DATABASE.md) if the task touches an interface or data.
5. Your contributor file: [CONTRIBUTOR_1.md](CONTRIBUTOR_1.md) (frontend), [CONTRIBUTOR_2.md](CONTRIBUTOR_2.md) (provider agent). The backend/architect owner has no separate file: they own everything not assigned there.
6. [DECISIONS.md](DECISIONS.md) so you do not reverse an accepted decision.

## Ownership

| Area | Owner |
| --- | --- |
| `apps/api`, `packages/contracts`, `docker-compose.yml`, `infra/`, CI, `docs/` (except contributor files), database schema and migrations | Architect/backend |
| `apps/web` | Contributor 1 |
| `apps/agent` | Contributor 2 |

Do not edit files you do not own. If you need a change there, open an issue or message the owner with: what you need, why, and the proposed shape. Documentation about your own area is yours to update.

## Shared contracts

- Only the backend owner changes API schemas, the agent protocol and the database schema.
- Contracts are versioned (`/v1`). Never change a released contract incompatibly; request a new version.
- After any API change the owner runs `make contracts` and commits the output; consumers pull and adapt.

## Task boundaries

- One task = one branch = one pull request, small and reviewable. Branch names: `feat/<area>-<topic>`.
- Do not add dependencies on another area's internals. Frontend talks to the API only through generated contracts; the agent talks to the backend only through the (future) documented protocol.
- Do not silently make decisions that affect others. Add an ADR in `docs/DECISIONS.md` (via the architect) for anything cross-cutting.
- Do not mark work complete without running the checks (`make check` or the area's check target) and reporting real results.

## Conflict prevention

- Rebase on `main` before opening a PR. Resolve conflicts in your own files only; if a conflict touches someone else's file, stop and ask.
- Generated files (`openapi.json`, `schema.d.ts`, lock files) are regenerated, never hand-merged.
- Do not reformat files you do not own.

## Handoff procedure

When finishing a task, report in the PR description or message:

1. **Changed:** files and behaviour.
2. **Validation:** commands run and their actual results.
3. **Docs updated:** which files.
4. **Contract impact:** none, or what the owner must do.
5. **Not done / known gaps:** stated plainly; nothing aspirational in docs.
6. **Next steps** for whoever continues.

Add a line to [CHANGELOG.md](CHANGELOG.md) for meaningful changes (the architect merges changelog edits to avoid conflicts).
