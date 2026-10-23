# Hermecious — Opus 5.5 High — P1.1 (Authentication)

**MANDATORY INPUTS:** Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_02_P1.1-P1.3.md`, `AGENTS.md` or `CLAUDE.md`, accepted ADRs, and `EXECUTION_LEDGER.md`. Inspect existing actual repository and Docker/test setup. Resolve paths from the repository rather than guessing.

**EXECUTE EXACTLY P1.1. STOP when P1.1 is verified or blocked.**

### Preflight gate

1. Run `git status` and inspect the repository, P0.4 error envelope, P0.3 testing/migration harness, session/proxy/config conventions and current migrations.
2. Verify P0.1, P0.2, P0.3, P0.4 are `VERIFIED` with actual evidence in `EXECUTION_LEDGER.md`. If missing/unverified: **STOP and report the precise gap**, do not pretend completion.
3. Present a brief file-level plan, acceptance cases `AUTH-01` to `AUTH-10`, failure scenarios, constraints and rollback. Preserve unrelated work.

### Implement only the P1.1 specification

- Persist minimal `organizations`, `users`, `auth_sessions` through Alembic. P1.2 must reuse organizations/users; record this sequencing correction.
- Password verification via tuned Argon2id. Interactive idempotent owner bootstrap: no default credentials/password CLI args/logging.
- Server-owned opaque sessions (high-entropy verifier, hash at rest), cookie hardening and same-origin architecture, idle/absolute expiry, revocation, rotation.
- `/api/v1/auth/login`, `/me`, `/logout`, session-bound CSRF issuance as specified; login abuse defenses and indistinguishable incorrect-credential responses.
- Deny unauthorized API access by default, with explicit public health/login allowlist. Owner/operator/observer authorization guard for future uses; enforce backend, not only UI.
- Minimal Next login/protected shell, no dashboards/accounts/offer UI. Reuse P0 logs/config/error format and Docker environment.
- Tests MUST prove cookie tampering, expired sessions, logout revocation, CSRF mutation absence, role denial, suspicious login attempts, persistence across restart and invalid production cookie config. Include DB/Redis failure behavior.

### Non-negotiable prohibitions

No JWT or token in browser localStorage; no hardcoded owner login; no permissive wildcard credential CORS; no CSRF exemption for authenticated mutations; no second DB/config/logging stack; no P1.2/P1.3 entity work except P1.1 minimum org/user tables; no external messaging/lead discovery; no passing report for unrun tests.

### Verification and close-out

Run repo-standard lint, typecheck, unit/contract/integration tests, migration upgrade/downgrade (disposable DB), API auth/CSRF flows, and Compose smoke/restart checks where available. Verify observed state after failures and document blocked tests. Update `EXECUTION_LEDGER.md`, auth runbook and ADR when warranted. Produce the **Section 5 close-out table** in the Batch 02 document with concrete command results and file paths. **STOP. Do not implement P1.2.**
