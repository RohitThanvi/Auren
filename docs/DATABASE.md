# Database

PostgreSQL 16 (`gen_random_uuid()` requires 13+) is the only authoritative datastore. Redis holds only disposable state (rate-limit counters).

## Schema conventions

- Tables plural `snake_case`; UUID primary keys with a server-side default; no sequential ids exposed.
- Every mutable table has `created_at`/`updated_at` as `timestamptz`; sessions run with `timezone=UTC`.
- Constraints are explicit and named through the metadata naming convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`). Foreign keys default to `ON DELETE RESTRICT`. Enumerations are `VARCHAR` plus `CHECK` (no native enums; easier migrations).
- Data minimisation: store identifiers, not personal data. Users hold only the Clerk subject.
- ORM objects are never returned from APIs; repositories return models, services return plain dataclasses, routes return Pydantic schemas.

## Current schema

`users(id, clerk_user_id UNIQUE, created_at, updated_at)` and `user_roles(user_id FK RESTRICT, role CHECK IN (buyer, provider, admin), PK(user_id, role))`.

## Migration policy

- Alembic only. The application never creates or alters schema at startup; in Compose the one-shot `migrate` service runs `alembic upgrade head` before the API starts.
- Every model change ships with a migration in the same commit. CI runs `alembic upgrade head` and `alembic check` (fails on model/migration drift).
- The test suite rebuilds the schema from migrations (`downgrade base` then `upgrade head`), so both directions are exercised.
- Migrations are reviewed by hand after autogeneration. Destructive changes (drop column/table) require an expand/contract sequence across releases.
- Revision ids are sequential (`0001`, `0002`, ...).

## Transaction rules

Services own transaction boundaries and commit explicitly. Allocation- and money-critical operations run in one transaction, with row locks (`SELECT ... FOR UPDATE`) or unique constraints that make the invariant enforceable by the database rather than application checks. Concurrency tests against real PostgreSQL are required for these paths (see `test_concurrent_first_requests_create_one_account`).

## Financial invariants (required for tables not yet created)

1. Money is `BIGINT` minor units plus a currency code; no floating point anywhere in storage or code (`domain/money.py` enforces integers; commission uses integer basis points, rounded half up).
2. The wallet ledger is append-only and double-entry: entries are never updated or deleted; corrections are new reversing entries; each transaction's entries sum to zero per currency.
3. Balances are derived from, or reconciled against, ledger entries; a `CHECK` prevents negative buyer balances where overdraft is not allowed.
4. Every external payment request carries a unique idempotency key stored under a `UNIQUE` constraint; every gateway webhook event id is stored under a `UNIQUE` constraint so replays are no-ops.
5. Webhooks are processed only after signature verification over the raw body.
6. Charged amounts are computed server-side from stored pricing and metered usage, never from client input.
7. Financial rows are never silently deleted; use status columns and reversing entries.
8. Provider settlements and platform commission are ledger entries, reconciled periodically against gateway reports.

## Allocation invariants (required for tables not yet created)

1. A resource unit (CPU cores, RAM, GPU, storage) is never allocated beyond a provider machine's declared allocatable capacity; enforced by a transactional check with a lock on the machine row.
2. A GPU is assigned to at most one active session (partial unique index on active allocations).
3. Allocation state transitions follow a fixed state machine; illegal transitions are rejected in the domain layer and constrained by `CHECK`.
4. Offers expire; an expired or already-accepted offer cannot be accepted again.
5. Queue tickets carry no allocation guarantee; a ticket becomes a session only through the same transactional allocation path as an immediate rental.
