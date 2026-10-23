# Hermecious — Opus 5.5 High — P1.5 Durable Jobs & Transactional Outbox

**Run ONE subphase only: P1.5. STOP after verified or blocked.**

## Mandatory inputs

Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` (P1.5, shared invariants, gate matrix, close-out), `AGENTS.md`/`CLAUDE.md`, accepted ADRs, `EXECUTION_LEDGER.md` and current worker/Compose/persistence/auth implementation. Read P1.4 account API contract and P0-selected worker framework decision. Inspect actual code: do not fabricate paths.

## Preflight — hard stop if missing

1. Inspect `git status`, current SHA, migration head, worker/Redis usage, Postgres transactions, schema and existing retries/observability.
2. Verify ledger proves **P0.1–P0.4 and P1.1–P1.4 VERIFIED** with real commands/evidence. If any missing/unverified, **STOP**, return blockers, do NOT quietly implement missing phase.
3. Show your design for `jobs`, `outbox_events`, unique key scope, payload registry, transaction boundary, PG claim+lease fencing, Redis-independent DB polling, replay and rollout/rollback. Identify test fixtures for **JOB-01…JOB-10**. Explicitly explain that provider-side external effects are not exactly once.

## Implement ONLY P1.5

- Make **PostgreSQL authoritative** for jobs and outbox; optional Redis notification improves wake-up but outage cannot strand work. Reconcile existing RQ/Dramatiq ADR without duplicating durable job authority.
- Reviewed Alembic migrations using current schema, org-scoped FKs/keys and indexes. Durable idempotency scope `(organization_id, job_type, idempotency_key)` with canonical payload digest and version mismatch returning typed conflict.
- Typed, allowlisted job payload/handler registry; safe `diagnostic.noop` dev/test and one DB-only idempotent audit/snapshot action. Reject arbitrary code/class names, unknown versions, oversized payload and secrets.
- `enqueue_job` and `record_outbox_event` share **caller transaction**; rollback means neither survives. Exact duplicate returns same receipt and outbox identity; conflicting replays fail cleanly.
- DB polling, `FOR UPDATE SKIP LOCKED` claim, DB-clock lease with ownership/fencing token, bounded concurrent worker, transient retry with backoff+jitter, permanent `dead`, durable crash recovery, redacted metrics and trace.
- Outbox publisher's `dispatched_at` must mean notification successfully delivered to its sink, NOT job completed; publisher retries safely, and DB poller works with notification disabled.
- Only transactional/local DB test effects can be called logically once. DO NOT claim exactly-once external messaging. NO provider sends, source fetching, or agent orchestration.
- Document contracts, migration/rollback, failure taxonomy and operator runbook; update `EXECUTION_LEDGER.md` with evidence.

## Fault injection mandatory

Execute **JOB-01…JOB-10** in Batch 03, **including**: rollback-before-commit; terminate producer after commit and before Redis publish; Redis unavailable; two workers racing; worker crash after DB side effect and before ack; stale lease owner overwrite attempt; duplicate same idempotency key vs conflicting different payload; transient then permanent failures; outbox retry/replay; cross-org and malicious payload rejection. Assert final **database** state, not just API response. Run all prior P1.1–P1.4 regressions and disposable DB migration rehearsal. Never claim tests passed unless executed.

## Explicitly forbidden

No real WhatsApp/email sends, real web requests, general-purpose background code executor, workers that depend on Redis as sole queue truth, unbounded retries, raw payload secrets in logs, destructive volume reset, implementation of P2.1 or later.

Return **Section 4.2 close-out report** with all 10 JOB gates, exact commands/exit codes, failure observations, migration/rollback strategy and honest verdict. **STOP. DO NOT START P2.1.**
