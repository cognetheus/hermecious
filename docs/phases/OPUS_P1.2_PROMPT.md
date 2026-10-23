# Hermecious — Opus 5.5 High — P1.2 (Core Domain Data)

**MANDATORY INPUTS:** Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_02_P1.1-P1.3.md`, accepted ADRs, `AGENTS.md`/`CLAUDE.md`, and `EXECUTION_LEDGER.md`. Inspect actual P1.1 schema/auth/session implementation and P0 test/migration conventions.

**EXECUTE EXACTLY P1.2. STOP when P1.2 is verified or blocked.**

### Preflight gate

1. Inspect `git status`, current migrations/models and organization/role access patterns. Protect unrelated changes.
2. Require `VERIFIED` ledger evidence for all P0 and P1.1. If not verified: **STOP** with blockers.
3. Outline scoped file plan, data model delta, test plan `DATA-01` to `DATA-10`, negative paths and rollback; do not create a second org/users table.

### Implement only the P1.2 specification

- Alembic + SQLAlchemy 2 models for `verticals`, `areas`, `accounts`, `source_records`, `account_aliases`, `account_facts` with CHECK/unique/index/composite organization-scoped FK constraints.
- Preserve uncertainty, evidence freshness and source-rights classification; never treat an absent website/ERP claim as proven absence.
- Scoped repository/service functions from authenticated actor, typed fact validators, rights/permitted-storage restrictions, bounded safe evidence snippets and source URL screening.
- Seed only synthetic Lahore-style test records and `schools` vertical; no scraped real school or personal data.
- Test duplicate source keys, same-name distinct campuses, invalid facts, expired/rights-restricted sources, malicious URLs, concurrent inserts, cross-organization DB foreign keys **and** repository reads.
- Provide schema/data-contract documentation, reversible disposable migrations, tests and ledger entries.

### Non-negotiable prohibitions

No accounts list/detail UI or production CRUD API (P1.4), no real-source adapter (P2), no account matching agent (P3), no offers (P1.3), no contacts/consent/WhatsApp, no implicit cross-org trust or destructive migration on production data. Don't log raw payloads.

### Verification and close-out

Execute `DATA-01`–`DATA-10`, migration upgrade/re-upgrade/downgrade on disposable DB, FK violations and P1.1 auth/CSRF regression suites. Record actual commands, result states and any dangerous data migration implications. Update `EXECUTION_LEDGER.md`, schema docs and any ADR; use **Section 5 report** of Batch 02. **STOP. Do not implement P1.3.**
