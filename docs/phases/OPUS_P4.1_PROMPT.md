# Claude Opus 5.5 High — HERMECIOUS P4.1: Campaign Foundations and Candidate Enrollment

**ASSIGNMENT: IMPLEMENT P4.1 ONLY. NO OUTREACH DRAFTS, NO ELIGIBILITY ENGINE, NO SEND PROVIDERS. STOP AFTER PROOF.**

## 1. Read and verify

Read `CLAUDE.md`/`AGENTS.md`, accepted ADRs and `EXECUTION_LEDGER.md`, `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, and `docs/phases/HERMECIOUS_BATCH_06_P3.4-P4.2.md` sections **0, P4.1, 4**. Inspect actual P1.2 campaigns schema (if precreated), P1.3 published-offer catalog, P1.4 account/read model, P1.5 jobs/audit, P3.3 four-axis assessment and P3.4 evidence quality gate. Run baseline tests and report branch/SHA/migration head. Never assume docs prove earlier code exists.

**Prerequisite nuance:** Require verified P3.3 and an implemented P3.4 evaluator contract. If P3.4 live 30-account review is incomplete, permit only **draft configuration and clearly labeled synthetic/test-only preview**. Real candidate approval, production campaign activation and downstream drafting MUST be blocked by a durable evidence-quality gate. If prerequisites cannot safely be enforced, mark blocker; do not pretend live admission is approved.

## 2. Required outcome

Build the campaign planning domain and operator UI: a named Lahore-school campaign attached to a **current, published P1.3 offer revision**; typed filters/exclusions/area and local research/draft budgets; bounded deterministic candidate preview with reasons; manual approval **for drafting only** (quality-gated) or manual exclusion; pause/cancel; immutable audit; stale-input invalidation. **No campaign action is a message authorization.** A candidate's P3.3 `contact_now` is only a research priority.

## 3. Incremental steps, no detours

1. Inventory domain models and naming. Write `CAMPAIGN-01..10` executable test map and pure `campaign_rules_v1` filter contract before routes/UI. Adapt existing `campaigns`/`campaign_accounts` columns, not a duplicate schema or generic sales CRM.
2. Implement validated campaign name, school vertical, Lahore area, optional district, current published offer/version, strict allowlisted target/exclusion config and bounded preview. Never infer independent ownership from a single OSM pin, brand name or absence of a franchise notice. Include four ordinal assessment dimensions with distinct `unknown` handling.
3. Add additive migration only for missing metadata: immutable offer/rubric/input versions, campaign revision, quality gate reference/state, membership snapshots/review/audit and local bounded budgets. Scope all relationships to authenticated operator's organization.
4. Implement pure no-side-effect preview with current P3.3 and P3.4 quality state. Return per-account inclusion/rejection rationale and stable pagination/snapshot digest. **Preview must not enqueue, allocate a contact, or change campaign-account stages.**
5. Implement transactional `approve for drafting` and explicit `exclude`: row version and `expected_revision`, offer/source/assessment revalidation under lock, org-scoped `(campaign,account)` uniqueness, idempotency key+request digest and immutable audit. Exclusion and quality-gate failure always win over queued/planned work. Refuse real approval when 30-account evidence evaluation is unverified.
6. Add atomic DB-based local daily count limits using `Asia/Karachi` day boundaries for research approvals and future draft generation; retry/replay consumes quota exactly once. Defaults conservatively 30 candidates preview / 10 manual approvals / 10 drafts per day, configurable downward; these are **not WhatsApp limits**.
7. Implement `/api/v1/campaigns` CRUD and detail, preview, candidate approve/exclude, pause/cancel and optional activate, following existing auth/CSRF/error patterns. `active` means internal planning only and is forbidden for real campaigns until quality gate is valid; do not progress campaign accounts into `eligible`, `queued`, or `contacted`.
8. UI Campaigns: create, filter, preview, audit, manually select/exclude, paused/blocked explanations. Prominent label **“Channel permission not checked — do not contact from this screen.”** No Send, Launch, messaging enrollment, unsolicited WhatsApp or draft-generation action in this subphase.
9. Run `CAMPAIGN-01..10` with DB concurrency, stale offer/source/assessment, quality gate absent/expired, org/role/CSRF, exclusion-priority, nightly boundary, crash/replay and E2E UI tests. Regression P1.3/P3.3/P3.4. Assert zero `messages`, send-related outbox events/provider requests or `contact_permissions` created.
10. Perform security/concurrency review, test failed flows' final DB state, update ledger with commands/exit codes, feature rollback and genuine blockers. **STOP**.

## 4. Ten proof gates

- `CAMPAIGN-01`: draft school campaign with current published offer, version, auth scope and audit.
- `CAMPAIGN-02`: deterministic qualifying vs unassessed/stale/other-city/excluded/incompatible candidates with reasons.
- `CAMPAIGN-03`: bounded typed target config, invalid SQL-like operators rejected, stable pagination.
- `CAMPAIGN-04`: preview stale between read and selection => refusal/no write.
- `CAMPAIGN-05`: no real P3.4 evaluated gate => live approval/activation blocked; fixture-only mode explicit.
- `CAMPAIGN-06`: parallel approvals, duplicate ids, manual exclusion and replay converge safely.
- `CAMPAIGN-07`: durable local-day research/draft budgets exact under retry/concurrency/midnight.
- `CAMPAIGN-08`: pause/cancel, rules/offer edit, account/source invalidation preserve blocks.
- `CAMPAIGN-09`: role, CSRF, cross-org, source text injection/XSS negative tests.
- `CAMPAIGN-10`: UI create→preview→approved-for-drafting (fixture if real gate absent)→exclude→pause→restart; **zero sends**.

Use detailed acceptance requirements from the master plan. Must provide executed evidence or honest `BLOCKED/NOT-RUN`; API mock-only doesn't prove state.

## 5. Explicit forbidden scope

No P4.2 template/message generator, P4.3 contact consent/opt-out eligibility engine, P4.4 outbound draft approval, P4.5 sending simulator, P5 WhatsApp provider, bulk imports, scraping or LLM agent swarm. Do not implement message queues or HTTP clients to contacts. Even approved campaign candidates are **not contactable by this action**.

## 6. Final report

List exact changed modules/migrations, auth/routes/state transitions, test commands/exit status and actual DB/UI assertions. Include `CAMPAIGN-01..10` table, P3.4 current live gate status, rollback, known issues and `P4.2 READY/BLOCKED` verdict. Update `EXECUTION_LEDGER.md`. **STOP AFTER P4.1.**
