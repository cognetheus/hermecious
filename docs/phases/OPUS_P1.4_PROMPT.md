# Hermecious — Opus 5.5 High — P1.4 Account Management & Evidence UI

**Run ONE subphase only: P1.4. STOP after verified or blocked.**

## Mandatory source material

Read completely, in this order:
1. `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`
2. `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` — specifically P1.4, shared invariants, test matrix and close-out contract
3. `docs/phases/HERMECIOUS_BATCH_02_P1.1-P1.3.md` — accepted P1.1–P1.3 API/schema/offer contracts
4. `AGENTS.md` and/or `CLAUDE.md`, accepted ADRs, `EXECUTION_LEDGER.md`
5. Actual current repository source, migrations, API routes, auth/session tests and Next.js UI conventions

Do not assume example paths exist. Use actual code organization. Never edit files unrelated to P1.4 without explaining a required dependency.

## Preflight — STOP on failure

1. Inspect `git status`, SHA, repo tree, migration head, P1.2 model definitions, P1.1 RBAC/CSRF and existing P1.3 UI. Preserve local work.
2. Locate actual executed evidence proving **P0.1–P0.4 and P1.1–P1.3 VERIFIED**. If incomplete, report exact missing task and **STOP**; do not backfill foundation speculatively.
3. Propose scoped file list, existing/needed migration, account projection/API types, correction-history approach and tests **ACCOUNT-01 through ACCOUNT-10**. Note any contradiction with existing schema; prefer smallest reversible ADR-consistent decision.

## Implement P1.4 ONLY

- Authenticated org-scoped account create/list/detail/patch/archive APIs with typed errors, bounded keyset cursor pagination, role enforcement and session-bound CSRF on writes.
- Reuse actual P1.2 accounts, sources, aliases and facts. No school-name unique constraint or automatic fuzzy merging. Two schools can share a name.
- Enforce optimistic account version (`expected_version` or `If-Match`) atomically; stale updates return 409 and preserve old state.
- Source evidence workflow: add permitted source-supported facts and hypotheses; rights/TTL/schema validation remains in P1.2 service. The UI must show source/observed time/freshness/verification distinctly; never equate no evidence with no ERP.
- Correction is atomic, append-only/audited, linked to prior fact, with reason/actor/time. No silent overwrites. If an additional column/table is actually needed, implement one reviewed Alembic migration and disposable-DB tests.
- Build ONLY list/create/detail/evidence/correction operator pages inside existing Next.js protected shell; owner/operator editing, observer read-only; long text/XSS, pagination, keyboard and loading/error states.
- Implement test fixtures with fictional Lahore school names, zero real contacts. Log identifiers but not raw fact contents.
- Document the account/evidence contract and record exact verification in `EXECUTION_LEDGER.md`.

## Prohibited

No source crawling, search engine adapters, worker jobs, WhatsApp, campaigns, qualification/AI, hard delete API, bulk imports, bypassed CSRF/org checks, guessed facts, invented test results, `docker compose down -v`, or implementation of P1.5.

## Verification and stop gate

Execute **ACCOUNT-01…ACCOUNT-10** from Batch 03. Include API+UI route tests, two-actor concurrency, cross-org reads/links, source-rights denial, correction historical integrity, real DB persistence after process restart and P1.1–P1.3 regressions. Run repo-standard lint, formatting, typing, tests, and migration upgrade/downgrade on disposable DB if schema changed. Record precise executed command/exit/status and observed DB/UI state; label not-run tests NOT-RUN, never PASS.

Return **Section 4.2 close-out report** from Batch 03 including all 10 gate IDs and explicit `VERIFIED`, `PARTIALLY VERIFIED`, or `BLOCKED` verdict. Then **STOP. DO NOT START P1.5**.
