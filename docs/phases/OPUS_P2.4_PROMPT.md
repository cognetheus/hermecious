# HERMECIOUS — Claude Opus 5.5 High — P2.4 Discovery Runs and Review UI

**Implement P2.4 ONLY. STOP after P2.4 is VERIFIED or truthfully BLOCKED.**

## Read and verify first

Read `AGENTS.md`/`CLAUDE.md` if present, accepted ADRs, `EXECUTION_LEDGER.md`, `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` (P1.4 account API, P1.5 jobs/outbox, P2.1 source policy), `docs/phases/HERMECIOUS_BATCH_04_P2.2-P2.4.md` §§0/P2.4/5.3 and actual backend/frontend code and P2.2/P2.3 implementations. Inspect the current tests/versions instead of inventing modules.

**Gate:** verify all required earlier subphases through P2.3 have executed acceptance evidence. P2.2 live canary marked BLOCKED is not automatically VERIFIED. If a required prerequisite is missing, STOP with exact blockers and no fake checks.

## Execution sequence

1. **Preflight:** branch/SHA/status, migration heads, baseline API/UI tests, source registry rights/areas/candidates, P1.5 durable job and P2.3 reviewed identity associations; propose touched files and 10 RUN acceptance tests before coding.
2. **Schema with proof:** minimal `discovery_runs` and `discovery_run_candidates` linkage scoped to organization; do not clone P2.2 candidates or P2.3 associations. Status state machine `pending→running→{completed,partial,failed,cancelled}`; budgets and provider-rights **snapshotted at enqueue but re-evaluated at execution**. Distinct counters for examined/staged/displayed/rejected, a `truncated` flag and honest partial reason. Migrate and prove forward/back on disposable database.
3. **API:** implement authenticated, CSRF-protected `POST /api/v1/discovery/runs` (202 accepted), list/detail/candidates GET, cancel POST, review decision POST. Match the blueprint's DTO and existing route conventions. Server resolves allowed Lahore area/source; never accept arbitrary endpoint/URL, raw OverpassQL or guessed bbox via browser. Enforce max 30 candidates initial run, downward-only policy budgets, scoped access, cursor pagination and typed safe errors.
4. **Jobs:** atomically commit run + versioned `discovery.run.v1` job + outbox using P1.5; worker invokes registered P2.1/P2.2 adapters with actual rights, calls/count/timeout quotas and P2.3 identity suggestions. No claim of exhaustive coverage. Handle 429, missing terms, empty, upstream overlimit, restart, at-least-once retries, fencing and cooperative cancellation. Source change/revocation stops new attempts. Never directly send messages.
5. **Reviewer admission:** only explicit operator action `accept_new`, `attach_existing` after reviewed same-campus confirmation, `reject`, `defer`, `mark_distinct`. Under one transaction reuse P1.4 account creation and P2.3 association audit. Revalidate permitted source evidence, org, expiry and row version. Duplicated requests => same accepted account; collision and cross-org => 409/403/404 with no side effects. Mark new accounts **unverified / research pending**, not qualified; no inferred phone/owner/software/consent.
6. **Next.js UI:** new run form showing only actual permitted sources, Lahore area and budget; rights/attribution notice; run list/status; detailed candidate cards with provenance, reason for duplicate suggestions, manual actions and uncertain status. Use established auth/design; observer is read-only. Accessible keyboard/labels, Urdu names, sanitized URLs, partial/cancelled/empty states, no risky client-side rendering.
7. **E2E & regressions:** build deterministic fixture journey: owner/operator logs in → starts ≤30 candidate run → job runs even if Redis disabled → reviews source and identity explanation → accepts a distinct Lahore campus → reloads P1.4 detail → has correct audit. Include crash/duplicate worker, concurrent review, rights revoke, cancelled late worker and zero outbound sends. No fake live network proof.
8. **Document and close:** update OpenAPI/contracts/readme/ops workflow, `EXECUTION_LEDGER.md` per gate, migration and rollback, screenshots/artifacts if test suite supports, security review and truthful disposition.

## Ten acceptance gates

- **RUN-01** allowed operator start, job/outbox transaction, snapshot and 202.
- **RUN-02** observer/anon/CSRF/org denials with zero writes.
- **RUN-03** correct durable worker progress, counts, rights and UI reload.
- **RUN-04** 31+ candidates, 429, stale permission, empty, partial and no fabricated records.
- **RUN-05** job/create replay and race, same-key replay vs payload conflict.
- **RUN-06** manual accept-new exactly once with source proof, P1.4 account and audit.
- **RUN-07** reviewed attach/distinct and cancel-after-worker race without status resurrection.
- **RUN-08** stale source/rights, version mismatch, cross-org link rejected.
- **RUN-09** accessible observer/Urdu/long text and persistence after restart.
- **RUN-10** full UI → API → job → source → reviewed account E2E, all old gates green, **no sends**.

For each gate show commands, exit codes, observed final DB/job/UI state, screenshots when available, and mark VERIFIED / FAILED / BLOCKED / NOT-RUN. Run lint/typecheck, API contracts, pytest/DB/worker integration, migration, frontend test, Playwright E2E and failure simulations as supported. A compiled frontend is not E2E evidence.

## Do not implement

No P3 research/fact extraction, scoring, offer matching, campaigns, WhatsApp/SMS/email, auto-enrollment, unrestricted geographic crawling, forced source rights override, LLM tool calls, SaaS expansion or new workflow engine. This slice ends with a **human-reviewed account**, not a sales-qualified lead.

## Final output and STOP

Return changed paths, migration/version, APIs/UI, `RUN-01…RUN-10` verdict table with observed proof, negative failures and safeguards, old-suite regressions, rollback, outstanding blockers and whether **P3.1** is unblocked. Update ledger. **STOP. DO NOT START P3.1.**
