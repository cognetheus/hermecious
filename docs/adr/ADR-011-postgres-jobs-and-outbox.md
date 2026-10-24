# ADR-011: PostgreSQL-authoritative jobs and transactional outbox; Redis as optional wake-up

- **Status:** Accepted. Directed by Batch 03 §P1.5.1. **Supersedes the runtime role of ADR-009** (the RQ worker loop); the RQ library remains installed but dormant.
- **Date:** 2026-10-24
- **Source:** `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` §P1.5; blueprint §1 runtime boundaries and P1.5 gate

## Context

The blueprint requires that a crash between a transaction commit and dispatch never loses a job, and that a replay never duplicates work. RQ keeps its queue in Redis, so RQ jobs are lost if Redis loses them, and an enqueue cannot be atomic with a Postgres domain change. Running both RQ and a Postgres job table would create two authoritative queues.

## Decision

1. **PostgreSQL is the only authority** for durable work: `jobs` and `outbox_events` (migration `0006`).
2. **The producer writes the domain change, the job and its outbox event in its own single transaction.** `enqueue_job` and `record_outbox_event` never commit. Idempotency is `UNIQUE(organization_id, job_type, idempotency_key)` with a canonical payload digest: an exact replay returns the same receipt, and a mismatched payload or schema version is a 409.
3. **The worker process is a small bounded Postgres runner** (`app/jobs/runner.py`) rather than an RQ worker:
   - **Claims:** `SELECT … FOR UPDATE SKIP LOCKED` in small batches.
   - **Leases:** take their time from the **database clock**, with a new **fencing token** (`lease_token`) on every claim.
   - **Execution:** each handler's DB effect and the fenced completion (`… WHERE lease_token = :token AND status = 'running'`) commit in **one transaction**.
   - **Failures:** classified transient or permanent. Transient failures retry with exponential backoff (2s base, 5 min cap, ±20% jitter) up to `max_attempts` (≤10), then become `dead` with a sanitized `last_error_class`. Expired leases are reclaimed, and become `dead` (`lease_expired`) once their attempts are exhausted.
4. **The outbox publisher** (in the worker loop) delivers undispatched events to a sink. `dispatched_at` means only **notification delivered** (`dispatch_sink` is `redis`, or `none` when no sink is configured). It never means the job ran. Failed deliveries retry with exponential backoff, and events are never lost.
5. **Redis is optional.** It carries wake-up notifications (`LPUSH hermecious:jobs:wake <event id>`, which the runner waits on with `BLPOP`). If Redis is down, the runner falls back to plain DB polling (2s). Worker health is therefore **runner heartbeat + Postgres reachable**, not Redis.
6. **Only allowlisted typed handlers can run:**
   - `diagnostic.noop` (development and test only);
   - `account.audit_snapshot`, a DB-only effect with an independent `UNIQUE(organization_id, job_id)` guard.

   Payloads are Pydantic-validated, at most 16 KiB, and rejected if they contain credential fields or anything the log scrubber would redact (URL credentials, tokens, emails, phone numbers).

## What is and is not guaranteed

- **Execution is at-least-once.** A job may run more than once: after a crash, or after a lease expires while a slow worker is still running.
- **Exactly-once holds for *local DB effects* only.** The effect and the fenced acknowledgement are one transaction, a stale owner's completion matches 0 rows and rolls back, and handler effects carry their own unique keys.
- **No exactly-once guarantee for external side effects** (future WhatsApp, email, HTTP). Those adapters must add provider-side idempotency keys and reconciliation (P5). This phase has **no external-effect handlers**.

## Consequences

- One queue authority, which is backed up with the database. The work queue survives Redis loss.
- Polling adds up to a 2s latency when Redis is down; it is near-immediate when Redis is up.
- The worker no longer depends on Redis to start or to be healthy. The P0.2 recovery checks were updated: a Redis outage keeps the worker healthy, and a Postgres outage makes it unhealthy.
- Before migrations are applied, the worker waits without heartbeating (unhealthy) instead of crash-looping.
- RQ (ADR-009) remains a dependency, and `app/workers/tracing.py` is dormant. Re-introducing RQ needs a new ADR that keeps Postgres authoritative.

## Rollback

- **Code:** revert to the previous worker image. Durable rows stay intact. Old workers do not know the `jobs` table, so pending jobs wait (fail closed) rather than being lost.
- **Data:** never delete pending or dead jobs. A downgrade of `0006` on data-bearing databases needs the queue to be drained or exported first.
