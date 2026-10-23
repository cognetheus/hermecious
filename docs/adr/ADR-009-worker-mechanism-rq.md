# ADR-009: RQ as the background worker mechanism

- **Status:** Proposed. Awaiting owner acceptance at the P0.2 review.
- **Date:** 2026-10-23
- **Source:** blueprint §1 ("Dramatiq or RQ: select one via ADR"), ADR-001 open decision, Batch 01 P0.2

## Context

The blueprint makes PostgreSQL authoritative for jobs. The `jobs` table (P1.5) owns `attempt_count`, `max_attempts`, `scheduled_at`, `lock_owner` and `idempotency_key`, and a transactional outbox feeds the worker. Redis acts only as a broker and wake-up channel (ADR-002 in the blueprint log). So the worker library has to deliver and execute work reliably. It does not need to be the source of truth for retries, scheduling or rate limits.

P0.2 also needs a meaningful worker health check: a healthy Redis must not make a dead or hung worker look healthy.

## Decision

Use **RQ**. Do not install Dramatiq.

- Redis-only and synchronous Python, so there is no extra broker abstraction. This matches "Redis for queue/broker only".
- Every job runs in a forked work-horse process. A crashing or leaking job cannot corrupt the long-lived worker.
- RQ keeps a per-worker registration with a `last_heartbeat` in Redis, and keeps refreshing it while idle and during jobs. The container health check reads this worker's own heartbeat, so it reports unhealthy when the worker is dead, hung or cannot reach Redis.
- RQ's connection handling retries Redis with backoff instead of exiting. This is verified empirically in the P0.2 ledger entry.

Dramatiq's extra features (retry middleware, rate limiters, priorities) would duplicate policy that the blueprint assigns to Postgres-backed jobs. Keeping that policy in one place is a correctness property, not just a convenience.

## Consequences

- Retry, backoff, scheduling and quotas are implemented against the Postgres `jobs` table (P1.5, P9.2), not with RQ features. RQ's own retry stays off.
- Redis runs without persistence. Losing queued RQ messages is acceptable because the outbox re-enqueues from Postgres (P1.5 gate).
- Fork-per-job adds per-job overhead. That is acceptable at pilot volume.
- RQ does not support Windows natively. Development runs inside Linux containers.

## Rollback

Replace this ADR with one that selects Dramatiq, and swap the worker entrypoint. No job data lives in Redis permanently.
