# Hermecious — Batch 01: P0.2–P0.4

**Execution:** Opus 5.5 High; exactly one subphase per run. P0.1 must be merged, reviewed and verified before P0.2. P0.2 must be verified before P0.3; P0.3 before P0.4.

**Authority:** committed code and accepted ADRs > `HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` > this implementation package. If there is a discrepancy, report it before doing irreversible work. Follow `AGENTS.md` / `CLAUDE.md` from P0.1.

**Rules for every task:** inspect actual Git state, file tree, manifests, locks, ADRs and tests first; list scoped modifications; avoid overwriting uncommitted work; write acceptance tests before/alongside implementation; run checks; update `EXECUTION_LEDGER.md` with real command results; STOP after assigned task. Do not assume suggested file paths exist. No production credentials, WhatsApp messages, scraping, or P1 domain work. Never claim an unrun test has passed.

---

## P0.2 — Docker development stack and readiness

**Goal:** A contributor can bring up API, Next.js web, Postgres, Redis and worker using documented reproducible Compose commands; inspect health; recover from restarts without losing Postgres data.

**Dependencies:** Verified P0.1. Inspect exact dependency manager/lockfiles and relevant ADRs. Select one worker mechanism (RQ or Dramatiq) if not already fixed in ADR; document the decision, do not install both.

**Within scope:** Compose configuration, Dockerfiles and `.dockerignore`, minimal FastAPI/Next.js/worker entrypoints if absent, live/ready endpoints, Compose healthchecks, named Postgres volume, `.env.example` safe placeholders, local development runbook and smoke script. **Not in scope:** production deployment, business tables, auth, agents, scraping, messaging, job outbox, CI, comprehensive logs.

**Suggested modules (use repo reality):** `compose.yaml` or `infra/compose/compose.dev.yaml` (one canonical startup), `apps/api/Dockerfile`, `apps/web/Dockerfile`, `apps/api/app/api/health.py`, worker bootstrap, `docs/runbooks/local-development.md`, `scripts/smoke-local.sh`.

**Contracts:**
- `GET /health/live`: 200 `{"status":"alive"}` when API process runs, independent of Postgres/Redis.
- `GET /health/ready`: 200 with safe dependency statuses when both Postgres and Redis reachable; 503 with sanitized statuses when either unavailable. Bounded timeouts, no connection URLs or credentials.
- Web health path returns HTTP 200 if the web server is responsive; do not mislabel it as dependency readiness.
- Worker process health includes meaningful runtime/broker check; mere Redis health must not report a dead worker healthy.
- Internal networking; DB/Redis **not publicly exposed by default**. If local access essential, bind host ports to `127.0.0.1` only.
- API and worker use shared, env-driven `DATABASE_URL`, `REDIS_URL`. Startup order alone must not replace dependency recovery.

**Implementation:** inventory current files; create minimal lockfile-based image builds (nonroot where feasible); configure services, volumes and probes; add liveness/readiness routes; make missing config fail cleanly; document one-command startup, restart, logs, non-destructive stop and explicitly warned destructive cleanup; run real smoke and failure/recovery tests.

**Acceptance evidence:**
- A1: `docker compose up --build -d` succeeds from documented local env; five services visible as expected.
- A2: API live/ready 200, web health 200; response fields match contract.
- A3: Stop Postgres: API live remains 200, ready becomes 503; restore DB: ready returns 200.
- A4: Stop/restart Redis: API readiness reflects change and worker eventually recovers; no false worker-healthy report.
- A5: Save test row in disposable Postgres, restart stack without removing volumes, verify row survives.
- A6: Missing required settings yield sanitized error and failed startup (no hidden production fallback).
- A7: Inspect `docker compose ps`, image contexts and logs for unexpected public ports, baked `.env`, plaintext secrets.

**Negative paths:** port collision, dependency delayed or returns error, container crash, missing runtime, volume permissions. Record observed outcomes, not assumptions. If Docker is inaccessible, mark runtime gate BLOCKED, not VERIFIED.

**Rollback:** scoped Git revert of containers/entrypoints, preserve volume; never use `down -v` as default rollback. **Stop** after P0.2 evidence and ledger entry.

---

## P0.3 — CI, deterministic tests and migration harness

**Goal:** Local and CI checks reliably enforce lint/types/tests/build; disposable DB migration checks work; a deliberately failing test demonstrably breaks the pipeline.

**Dependencies:** P0.2 VERIFIED. Inspect existing CI, package managers, lockfiles, tests, DB wiring. Prefer existing test tools; Python pytest/ruff/mypy, web TypeScript/ESLint with the project's selected web test framework, Alembic.

**Within scope:** CI workflow, canonical local validation commands, disposable integration DB/Redis, minimal migration harness, deterministic time and data fixtures, basic API/web/DB contract tests, test runbook. **Not in scope:** production account schema P1.2, job/outbox P1.5, browser E2E P7.5, performance suites, unrelated refactors.

**Suggested modules:** `.github/workflows/ci.yml`, `apps/api/alembic/`, `tests/conftest.py`, `tests/unit/`, `tests/integration/`, `tests/contracts/`, existing web tests, `scripts/check.sh`, `docs/runbooks/testing.md`.

**Contracts:**
- CI uses pinned lockfiles and reports nonzero exit when any required check fails.
- Alembic owns schema migrations; no ORM `create_all()` on production application startup.
- Migration smoke only against isolated disposable DB; `alembic upgrade head` repeatable. Do not create P1 business tables prematurely.
- Tests use fixed UTC-aware clock fixture; `Asia/Karachi` is the market timezone when a test needs local time. No uncontrolled sleeps for date-dependent assertions.
- CI must not access developer/production databases. Invalid test config fails closed.

**Implementation:** inventory baseline; standardize check commands; wire existing project static checks/build; add Alembic config and minimal harmless baseline migration if needed; create deterministic test DB and clock fixtures; write API/health and DB migration tests; add web smoke test; configure CI jobs; deliberately fail a test in temporary local change, observe nonzero and restore; record exact evidence.

**Acceptance evidence:**
- A1: All required API and web lint, type, test and build commands complete with reported exit codes.
- A2: GitHub Actions run verifies equivalent checks when remote CI is accessible; otherwise flag remote status NOT RUN.
- A3: Intentionally broken test fails local CI-equivalent and/or actual CI; restored test passes.
- A4: Migration `upgrade head` twice passes on disposable database.
- A5: Invalid DB URL prevents migration and never silently uses non-test DB.
- A6: Fixed-time fixture produces reproducible results in repeated runs.
- A7: Tests pass from clean disposable DB with no developer data dependence.
- A8: FastAPI imports/starts and Next.js builds in the test environment.

**Negative paths:** failing migration, missing DB, broken code, parallel/duplicate test invocations, GitHub permissions missing, flaky date tests. Don't suppress failing tests to create green CI.

**Rollback:** revert scoped workflow/scripts/dependencies; remove disposable resources only. Never touch existing application data. **Stop** after P0.3 evidence and ledger entry.

---

## P0.4 — Structured logs, typed errors, validated config and redaction

**Goal:** Reliable diagnostics and correlation across HTTP + workers, without emitting secrets, tokens, contacts, messages or raw provider payloads.

**Dependencies:** P0.3 VERIFIED and baseline checked. Use existing logging/settings framework if available; no third-party observability backend required.

**Within scope:** single validated settings component, structured JSON logs, HTTP request IDs, worker trace propagation/context clearing, typed error envelope, exception/status mapping, PII/secret redaction, contract tests and troubleshooting docs. **Not in scope:** Sentry/OTel infrastructure, production alerts, data analytics, real message handling.

**Suggested modules:** `apps/api/app/core/config.py`, `logging.py`, `errors.py`, `request_context.py`, middleware/exception handlers, worker entrypoint, `tests/unit/test_redaction.py`, `tests/contracts/test_error_envelope.py`, `tests/integration/test_trace_context.py`, `docs/runbooks/observability.md`.

**Error contract:**
```json
{"error":{"code":"VALIDATION_ERROR","message":"Request could not be processed","request_id":"req_opaque","retryable":false}}
```
Stable categories: VALIDATION_ERROR (400/422), UNAUTHENTICATED (401), FORBIDDEN (403), NOT_FOUND (404), CONFLICT (409), RATE_LIMITED (429), DEPENDENCY_UNAVAILABLE (503), INTERNAL_ERROR (500). Preserve framework semantics and use one documented contract. No traceback or raw submitted data in response.

**Logging contract:** UTC timestamp, level, service, environment, event, safe request/trace ID, duration, safe error code, sanitized context. Validate or replace client-supplied request IDs (size/charset). Keep request IDs distinct across concurrent requests and worker jobs, clear context after each. Logs omit credentials, auth/cookie headers, connection strings, phone numbers, message bodies and query parameters by default. Allowlist safe fields and redact nested structures.

**Implementation:** inspect current config/logging and errors; centralize validated settings, ensure safe development values and fail-closed production config; implement FastAPI middleware/contextvars, JSON log format and exception handlers; wire worker context to validated metadata; implement boundary redaction; test malicious newlines, nested secrets, invalid IDs, concurrency, temporary dependency failures and safe startup error reporting; document request-ID troubleshooting.

**Acceptance evidence:**
- A1: Real API request gets correlation header matching JSON log ID.
- A2: Invalid input returns documented 400/422 safe envelope, `retryable=false`.
- A3: Injected unhandled error produces 500 INTERNAL_ERROR without stack trace to client.
- A4: Dependency failure mapped to sanitized 503 with retryable value where applicable.
- A5: Missing/invalid config fails startup and logs names of settings, not their raw values.
- A6: Seed nested fake password, API key, cookie, DB URL, phone, message body; captured logs contain none of these values.
- A7: Concurrency and sequential worker jobs exhibit no correlation-context leakage.
- A8: Malicious/excessively long request IDs cannot forge logs or expand payload indefinitely.

**Negative paths:** 3rd-party noisy library logs, malformed exception, sink errors, cancellation, worker failure before cleanup, validation exceptions. Preserve safe request handling and document limitations.

**Rollback:** revert scoped logging/config changes; do not disable redaction as a fix. Rerun P0.2 health and P0.3 CI tests after integration. **Stop** after P0.4 evidence and ledger entry.

---

## Cross-subphase release gates

P0.2 gives canonical service names/endpoints/compose commands. P0.3 reuses these without defining a second stack/toolchain. P0.4 integrates into existing API+worker and must not regress health, CI or migration functionality. All subphases must update the execution ledger with commands, results, changed files, failures, rollback and next authorized task. Next phase after P0.4 is P1.1, not included here.

**Required close-out from Opus:**

```text
Subphase and Git SHA:
Scoped files changed:
Acceptance ID | test/command | observed output | PASS/FAIL/BLOCKED/NOT RUN
Negative cases observed:
Security/privacy checks:
ADRs/deviations:
Rollback and migration effects:
EXECUTION_LEDGER.md update:
VERDICT: VERIFIED / PARTIALLY VERIFIED / BLOCKED
STOP — do not implement next subphase.
```
