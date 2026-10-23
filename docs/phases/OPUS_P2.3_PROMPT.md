# HERMECIOUS — Claude Opus 5.5 High — P2.3 Conservative Campus Identity Resolution

**Implement P2.3 ONLY. STOP after P2.3 is VERIFIED or truthfully BLOCKED.**

## Required reading

Read the project's `AGENTS.md`/`CLAUDE.md` if present, ADRs, `EXECUTION_LEDGER.md`, master blueprint P2, Batch 03 P1.2/P1.4/P2.1 contracts, Batch 04 `docs/phases/HERMECIOUS_BATCH_04_P2.2-P2.4.md` §§0/P2.3/5.3, and the actual code/migrations/fixtures from P2.2. Do not overwrite decisions or write duplicate tables. P2.3 may be started only after **P2.2 is actually VERIFIED** (or a formally accepted, explicit source-compatible fixture-only exception documented as a changed prerequisite—not a fake live result).

## Preflight

1. Print branch/SHA/dirty status; run baseline lint, tests, migrations and inspect existing accounts, source identifiers, aliases, candidate staging and role/CSRF policy.
2. Confirm ledger `LIVE-01…LIVE-10` and earlier SOURCE gates, including external canary status. Missing required dependencies => STOP with blocker, no speculative recovery edits.
3. Draft feature and decision policy before implementing: what is a single **physical campus**, which checks are deterministic, and which pairs require manual review? Assign every `IDENTITY-01…IDENTITY-10` a test.

## Implement only school identity resolution

- **Identity boundary:** a campus/site is the record, not brand/group. Multiple Lahore branches and chain franchises are distinct until directly supported otherwise. Same website/domain does NOT prove same campus or local buying authority.
- **Exact key:** `(organization_id, provider, external_key)` denotes a repeated observation; re-observation is idempotent and may update permitted source metadata with history.
- **Candidate comparison:** deterministic explainable normalization (Unicode/English punctuation/whitespace, original Urdu aliases retained), location/campus disqualifiers, and optional licensed real coordinates if present. Separate exact reobservation, human-review suggestion, distinct, insufficient evidence. **Never auto-merge two different source identifiers based on fuzzy similarity or an LLM.**
- **Fixtures first:** create >=20 labeled identity comparisons including same-name different areas, different campuses, same brand/domain, franchise operator difference, Urdu/English spellings, ambiguous addresses, renamed school, long malicious strings, source revisions and concurrent duplicates. Include explicit gold decision and reason codes. Measure false positive automatic merges (must be zero on these fixtures); don't falsely claim generalized accuracy.
- **Persistence:** reuse P1.2/P1.4 models or add minimal org-scoped suggestion/decision/link records. Enforce uniqueness of canonical ordered candidate pairs by org and algorithm version. Record versioned feature explanations, allowed source IDs, actor, reviewer decision, reason, old and new states. Review/confirm/defer/mark distinct/undo as typed service/API using actual RBAC, CSRF and optimistic concurrency. Prevent cross-org FK association and stale-version writes. Retain all original source records and history; never destructive auto-merges.
- **Reversal:** undo a reviewed association without deleting source records/accounts/facts. If new evidence makes naive undo unsafe, queue explicit corrective review and mark blocked rather than silently moving claims. Repeat decisions are idempotent and reused key with different payload is 409.
- Docs: update identity rules, evidence thresholds, migration and application-level rollback; log actual fixture scores, decision effects and command results to `EXECUTION_LEDGER.md`.

## Required gates

`IDENTITY-01` exact source-key replay; `IDENTITY-02` cross-source similar name human suggestion; `IDENTITY-03` distinct city/campus; `IDENTITY-04` franchise/chain/domain distinction; `IDENTITY-05` unknown area/Urdu alias; `IDENTITY-06` reviewed same-campus association with replay+audit; `IDENTITY-07` stale double-review and undo with later facts; `IDENTITY-08` cross-org and observer/CSRF access; `IDENTITY-09` >=20 golden fixtures and malicious payload; `IDENTITY-10` restart/migrations and old LIVE/SOURCE suites. All require observed evidence and correct persisted state.

Run static checks, pure matcher unit, contract, DB integration, migration rehearsals on disposable DB, concurrency tests and security/regression. No network or model calls for resolution. Record mismatches honestly; do not redefine test labels to make results green.

## Hard exclusions

No discovery-run UI (P2.4), no automatically creating P1.4 accounts, no AI extraction/scoring, no contact or WhatsApp enrichment, no unreviewed fuzzy merge, no account deletion, no campaigns. Do not switch the CRM's identity to chain-level just because some schools share branding.

## Final reporting and STOP

List changed paths, model/API contracts, golden fixture summary, `IDENTITY-01…10` verdict+command evidence, migrations, negative-path DB inspections, reversibility demo, existing regression results, blocker/rollback and readiness for P2.4. Update ledger. **STOP. DO NOT START P2.4.**
