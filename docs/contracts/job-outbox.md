# Jobs and outbox contract (P1.5)

Decision record: [ADR-011](../adr/ADR-011-postgres-jobs-and-outbox.md). Code: `apps/api/app/jobs/{models,registry,service,runner,routes}.py`, `apps/api/app/workers/worker.py`. Migration `0006`.

## Producer API (inside the caller's transaction, never commits)

```python
enqueue_job(db, *, organization_id, environment, job_type, schema_version, payload, idempotency_key,
            clock, available_at=None) -> JobReceipt(job_id, status, created)
record_outbox_event(db, *, organization_id, aggregate_type, aggregate_id, event_type, event_version,
                    payload, idempotency_key, clock) -> event_id
```

- **Atomicity:** the caller's commit makes the domain change, the job and its `job.enqueued` outbox event durable together. A rollback leaves none of them.
- **Idempotency:** `(organization_id, job_type, idempotency_key)`, where the key matches `[A-Za-z0-9._:-]{1,200}`.
  - An exact replay (same canonical payload digest and schema version) returns the **same receipt** with `created=False` and writes no second event.
  - The same key with a different payload or version gives `Conflict` (409).
  - Concurrent identical enqueues produce one row.
- **Correlation:** `correlation_id` is the request ID at enqueue time. The runner binds it, after validation, while the job runs, so logs correlate HTTP and worker activity.

### HTTP producer

`POST /api/v1/accounts/{id}/snapshots` (owner or operator, with CSRF) requires an `Idempotency-Key` header. It returns **202** `{job_id, status, created}`.
- Writes the audit `account.snapshot_requested`, the job and the outbox event in one transaction.
- Replays return the same receipt; a key reused for another account gives 409; a missing or malformed key gives 422.
- Another organization's account gives 404.

`GET /api/v1/jobs/{id}` (any role, organization-scoped) returns status, attempts, timestamps and `last_error_class`, **never the payload**. `GET /api/v1/ops/jobs` (**owner**) returns per-organization counts by status, the oldest due age, the undispatched-event count and the last 50 dead jobs.

## Registry (the only executable work)

| `job_type` | version | payload | environments | effect |
|---|---|---|---|---|
| `diagnostic.noop` | 1 | `{note?: ≤100 chars}` | development, test | none |
| `account.audit_snapshot` | 1 | `{account_id: uuid}` | all | inserts one `account_audit_snapshots` row (version and fact counts) with `UNIQUE(organization_id, job_id)`; another organization's account gives permanent `account_not_found` |

Enqueue is refused (400) for an unknown type or version (class names and function paths have no meaning), a disallowed environment, invalid or extra fields, a payload over 16 KiB, credential-named fields, or values containing credentials, emails or phone numbers.

## Lifecycle

```text
pending ──claim──▶ running ──effect + fenced complete (1 tx)──▶ succeeded
   ▲                  │
   │ backoff          ├─ transient error, attempts < max ──▶ retry_wait ──due──▶ (claimable)
   └──────────────────┤
                      ├─ permanent error / invalid payload ──▶ dead (error class)
                      ├─ transient, attempts exhausted ──▶ dead (retries_exhausted)
                      └─ lease expired ──▶ reclaimed (attempts+1) or dead (lease_expired)
```

- **Claim:** `FOR UPDATE SKIP LOCKED`, batch of 5 by default. `attempts+1`, a new `lease_token` and a 60s lease, all from **DB time**.
- **Fencing:** `complete_job` and `fail_job` require the current `lease_token`. A stale worker gets `LeaseLost` or `None`, and its transaction, including its effect, rolls back.
- **Backoff:** `2s·2^(attempt−1)`, capped at 5 min, with ±20% jitter.
- **Error taxonomy** (`last_error_class` only; messages and tracebacks never reach the DB): `transient_error`, `upstream_timeout`, `database_unavailable`, `unexpected_error` (retryable, bounded), `permanent_error`, `invalid_payload`, handler-specific permanent classes (e.g. `account_not_found`), `retries_exhausted`, `lease_expired`.

## Outbox

- **Undispatched events** (`dispatched_at IS NULL AND next_attempt_at <= now`) are leased for 30s with `SKIP LOCKED` and delivered to the sink.
- **Success:** `dispatched_at` and `dispatch_sink` are set, where the sink is `redis` or `none`. **This means only that the notification was delivered**; job state is tracked separately.
- **Failure:** `attempts+1`, `last_error_class = sink_unavailable`, and `next_attempt_at` backs off exponentially. Events are never dropped.
- **A crashed publisher's** lease expires after 30s and another publisher takes over. Duplicate notifications are harmless: consumers dedupe by event UUID, and a wake-up is idempotent.
- **The Redis sink** pushes only the event UUID onto `hermecious:jobs:wake` (trimmed to 1000), never payloads.

## Worker process

`python -m app.workers` (Compose service `worker`) loops: publish outbox, claim and execute jobs, write the heartbeat, then wait on `BLPOP` (Redis) or sleep 2s (poll). It logs `jobs.metrics` (counts, oldest due age, undispatched events) every 30s.

The health check (`python -m app.workers.healthcheck`) passes only when the **loop heartbeat is under 60s old and Postgres is reachable**. A Redis outage does not affect it. Before migrations exist, the loop waits **without** heartbeating (`worker.schema_not_ready`).

## Guarantees and non-guarantees

- **Guaranteed:** a committed job is never lost, whether the producer crashes before notification, Redis is down, or the worker crashes. Each job is claimed by at most one live lease at a time. Local DB effects happen once logically.
- **Not guaranteed:** exactly-once execution of handler code (it is at-least-once). **No exactly-once for external side effects.** Future adapters must use provider idempotency keys and reconciliation (P5).

## Operations

See [docs/runbooks/jobs.md](../runbooks/jobs.md).
