# HERMECIOUS — Claude Opus 5.5 High — P3.2 School Operations Signals

**ASSIGNMENT: Implement P3.2 ONLY. STOP after independently verifying P3.2 or truthfully reporting a blocker.**

## Required reading and gate

Read actual repository before deciding files: `CLAUDE.md`/`AGENTS.md`, accepted ADRs, `EXECUTION_LEDGER.md`, `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_05_P3.1-P3.3.md` §§0, P3.2, 4, and current P1.3 published-offer catalog, P1.4 account fact/correction, P2.3 identity, P3.1 observation/evidence/rights/freshness services. Earlier specs are supporting history, not licenses to recreate current modules.

**Hard prerequisite:** P3.1 `RESEARCH-01..10` must have actual verified evidence (or legitimate explicit baseline deviations agreed in repo ADRs). Otherwise report blocked and stop. Do not implement prerequisite components casually inside this task.

## Objective

Transform current, supported P3.1 *claims* for one admitted Lahore school into a **versioned six-part, explainable school operations brief** with accurate observed/hypothesis/conflicting/unknown states and specific discovery questions. This is NOT four-axis qualification; no lead priority, contacts, campaigns or messages. The school might be an OSM listing only; every missing detail stays **unknown**.

## Ordered execution

1. **Preflight:** record SHA/branch/dirty status, migrations, P3.1 actual claim types/statuses and rights-controlled evidence projections, existing UI, auth. Run baseline and write `SCHOOL-01..10` acceptance tests or test design before edits. Identify evidence source staleness, corrections, confidence and campus association semantics from real code.
2. **Typed rubric and fixtures:** implement pure `school_signals_v1` with exactly six keys: `campus_footprint`, `operator_autonomy`, `admissions_workflow`, `fee_process`, `public_contact_route`, `operational_complexity`. Each key must have `state` (`observed|hypothesis|conflicting|unknown`), cautious statement, cited current `fact_ids`, conflicting ids, freshness, evidence timestamp and one answerable respectful discovery question. Pin rubric version; avoid runtime LLM verdict changes. Build >=18 synthetic evidence cases across ~10 fake schools (or reuse/extend P3.1 fixture corpus), including Urdu and no-website.
3. **Evidence selection:** only choose org-scoped admitted account P3.1 current reviewer-supported claims, their source evidence and P2.3 approved campus relationship. Rejected/hypothesized/expired/revoked/superseded claims can appear as gaps/history but cannot become affirmative observations. Metadata-only and unauditable citations must not silently certify operations.
4. **Safe interpretation:** a single OSM campus isn't proof of one-campus organization; school brand/franchise doesn't prove centralized buying; reception form notice isn't proof of no digital admissions; bank deposit notice isn't proof of manual reconciliation; public office phone/email isn't marketing consent or owner access; complexity signals aren't budget/need assertions. Preserve conflicts with all supporting references. Unknown remains unknown, not `weak` or “false.” Generate discovery questions based on gaps; no insulting/presumptive language.
5. **Snapshot persistence:** persist immutable org-scoped `school_signal_snapshots` (only if not already modeled), `claim_id@version` ordered input, rubric version, digest, created timestamp, version and needs-reassessment projection. Dedupe `(org,account,rubric,input_digest)` under concurrent generation; new/edited/expired claims produce new digest or mark stale; do not overwrite historical snapshots. Use smallest additive migration, verify on disposable DB, plan production forward repair.
6. **API and UI:** add protected generation (`POST /api/v1/accounts/{id}/school-signals:generate`, adapt convention), read latest/history, existing account detail's `School Research` section with six clearly labeled cards (observed vs hypothesis vs conflicting vs unknown), source links, staleness/attribution, and questions. Owner/operator may generate, observer reads only, CSRF on POST and no cross-org joins. Sanitize links/HTML/Unicode. UI must not show final four-axis priority here.
7. **Validation:** test `SCHOOL-01..10`, source-revoked mid-computation, correction race, unlicensed excerpt, two concurrent snapshot writes, Urdu, prompt-injection string, wrong campus association, session/auth denial, restart + migrations. Full path P1.4 account + P3.1 current claims -> six signal UI after reload. Assert **zero campaign, contact_permission, outbound message and task creation**.
8. **Review and close:** self-review generated wording as if you were a school administrator. Remove unsupported process conclusions. Run actual lint/types, unit, API, DB, UI E2E and prior P3.1 suites. Update contracts, rubric explanation, evidence ledger and rollback. Record exact observed commands/results; do not claim not-run checks passed.

## Ten required gates

- **SCHOOL-01** one sourced admissions notice -> six-key versioned brief with exact citations.
- **SCHOOL-02** single OSM POI and no autonomy evidence -> campus total and decision rights remain unknown.
- **SCHOOL-03** reception notice never becomes assertion of paper-only, Excel or no ERP.
- **SCHOOL-04** published fee instructions never become manual arrears/reconciliation claims.
- **SCHOOL-05** permitted generic public contact remains signal only: no opt-in/contact effects.
- **SCHOOL-06** contradictory source notices -> conflicting and dual citations, no forced winner.
- **SCHOOL-07** empty/rejected/stale/revoked/corrected claims -> accurate unknown/stale, reassessment flag.
- **SCHOOL-08** replay/concurrent generator -> single logical snapshot; changed evidence generates new history.
- **SCHOOL-09** org/role/CSRF/Urdu/injection/unsafe citation negative tests.
- **SCHOOL-10** deterministic UI/DB integration, prior suites and no ranking/sends.

## Reporting and stop

Return `SCHOOL-01..10` rows with **real** command/exit code/observed state/verdict; touched files/migrations, rubric schema/version, cross-org/security findings, negative-path proof, prior test regressions and rollback. Update `EXECUTION_LEDGER.md`; state `P3.3 UNBLOCKED` only after verified prerequisites. **STOP: no P3.3 qualification, P3.4 evaluation or P4 outreach.**
