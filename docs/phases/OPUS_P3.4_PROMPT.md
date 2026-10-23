# Claude Opus 5.5 High — HERMECIOUS P3.4: Real Evidence Quality Evaluation

**ASSIGNMENT: IMPLEMENT P3.4 ONLY. DO NOT START P4.1 OR ANY CAMPAIGN WORK. STOP AFTER P3.4 VERIFICATION OR AN HONEST BLOCKER REPORT.**

## 1. Establish actual prerequisites

Read, in this order:

1. `CLAUDE.md` and/or `AGENTS.md`, accepted architecture/security ADRs and actual `EXECUTION_LEDGER.md`.
2. `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` §P3.4 and master data/API conventions.
3. `docs/phases/HERMECIOUS_BATCH_05_P3.1-P3.3.md` (especially source, signal and qualification contracts).
4. `docs/phases/HERMECIOUS_BATCH_06_P3.4-P4.2.md` sections **0, P3.4, 4** (the binding specification for this task).
5. Actual repository source schemas, P3.1 facts and rights, P3.2 six-signal projector, P3.3 qualifications, reviewer UI, tests, P0.4 logging and P1.5 durable jobs.

Report branch, SHA, dirty worktree, migration head and baseline test results. Require observed verification of P3.1–P3.3 in the execution ledger. If a prerequisite is missing, **BLOCK** rather than stubbing earlier phases or pretending this task is done. Keep existing functionality, naming, directories and migrations whenever possible.

## 2. Definition of done

Hermecious can (a) construct a reproducible, frozen corpus of **30 distinct real permitted Lahore-school account records**, (b) enumerate every displayed factual assertion in that sample, (c) have a human adjudicate whether each is directly supported, (d) publish baseline numerator/denominator including unsupported, stale, contradicted and unverifiable claims as failures, (e) correct/demote/withdraw unsupported factual displays with history intact and rerun a separately labeled post-remediation audit, and (f) show the **current, truthful** quality gate for downstream enrollment. **Accept only if >=90% supported factual assertions and no known unsupported assertion remains displayed as fact**; this is an initial sample target, not a population accuracy guarantee.

**NO FAKE EVIDENCE:** Automated fixture tests do NOT satisfy the real 30-account gate. If 30 real policy-permitted records, lawful source access or manual human adjudication are absent, implement the system and mark live gate `BLOCKED/NOT-RUN`, with exact missing input; don't manufacture schools, scores, reviewers or evaluation results. Preserve an explicit fail-closed production enrollment flag.

## 3. Implement in bounded steps

1. Create requirement-to-evidence plan for `EVAL-01..EVAL-10` and deterministic fixtures before implementation. Define `displayed_factual_claim` precisely, including factual statements in summaries and projection UI; ensure hypotheses/question text cannot be used to conceal an assertion.
2. Add smallest necessary `evidence_eval_runs` / `evidence_eval_items` or equivalent **org-scoped, versioned** storage; use immutable baseline snapshots/digests, selection method and seed; avoid raw source HTML duplication and unlicensed excerpts. Write additive Alembic migration only if schema is genuinely missing. Validate migration on disposable DB; preserve prod data.
3. Build 30 **distinct account** seed/fixed sampling with campus checks, real-vs-synthetic provenance flag, rights/TTL eligibility and snapshot of current P3.1 fact/source/assessment revisions. A sample with <30 real eligible accounts must clearly report `INSUFFICIENT_CORPUS` and cannot pass.
4. Implement human verdicts: `supported`, `unsupported`, `contradicted`, `stale`, `unverifiable`, with reviewer ID, reason, rights-safe locator, immutable revisions and CSRF/version protected actions. External page content/model results may suggest but **never finalize verdicts by themselves**.
5. Implement honest precision metric. Denominator = **all adjudicated displayed factual claims**, not just claims that can be sourced. Empty denominator, incomplete review and expired policies fail. Report account coverage and counts including zero-fact accounts. Never silently remove failed items from frozen baseline.
6. Remediation: link factual-claim corrections/demotion to prior eval failures; trigger P3.2/P3.3 invalidation; produce distinct `post_remediation` run, attach baseline run ID, re-adjudicate and preserve original failures. Require zero known unsupported factual assertions left displayed.
7. Add typed authenticated `POST/GET/review/finalize` API and an evidence-quality operator screen with explicit `PASSED`, `FAILED`, `BLOCKED`, `INCOMPLETE` state and source-safe citations. Observer read-only; other-org data 404/denied consistently with existing repo.
8. Run security and failure tests: wrong campus, permission revocation, metadata-only source, 0 facts, 29 real accounts, 30 synthetic records, concurrency, replay, incomplete reviewer, report export redaction, malicious prompt text, UI Urdu/XSS, restart. Run impacted P3.1–P3.3 regressions. Assert no campaigns created, outbound outbox events or provider calls.
9. If (and **only if**) actual 30 eligible accounts and authorized human review are available, perform real audit and capture reproducible manifest + actual reviewer verdicts and counts. Do NOT claim that `EVAL-07` is verified without executing it. If not, leave feature usable but production quality gate closed and explain exact blocker.
10. Self-review for metric gaming, privileged info, source rights, 30 distinct count, audit tamperability, invalidation gaps; fix and rerun. Add docs and update `EXECUTION_LEDGER.md` with real evidence. **STOP**.

## 4. Ten non-negotiable acceptance gates

- `EVAL-01`: 30 distinct *real* eligible canonical schools in frozen reproducible selection; insufficient count blocks (not a passing 29/30).
- `EVAL-02`: frozen revision-aware factual display universe, provider rights and deterministic corpus fingerprint.
- `EVAL-03`: accurate source-supported fact accepted and fake Excel/ERP inference rejected.
- `EVAL-04`: source expiry, revocation, contradiction and metadata-only unknown counted as non-supported.
- `EVAL-05`: synthetic math fixture: 18/20 = 0.90 with 30-account fixture coverage; 0/0 never passes.
- `EVAL-06`: failed claim corrected/demoted, prior baseline retained, post-remediation rerun and P3 invalidation.
- `EVAL-07`: **real manual** 30-account evaluation, >=90% supported plus zero remaining unsupported displays, or explicit BLOCKED/NOT-RUN.
- `EVAL-08`: duplicate account, replay, concurrent adjudication, interrupted finalization safely controlled.
- `EVAL-09`: permission, CSRF, org, injection, PII and source storage negatives, zero sends.
- `EVAL-10`: UI evidence review → quality report → linked correction → rerun plus impacted P3 regressions and truthful status.

Follow the detailed expected end state under each ID in the master Batch 06 document; no test names without actual assertions of DB and user-visible state.

## 5. Output contract

Return actual changed files and migration IDs; real command/exit/observed summaries (types/lint/unit/contracts/integration/UI), schema/route changes, `EVAL-01..10` proof table with `VERIFIED/FAILED/BLOCKED/NOT-RUN`, metric numerator/denominator and **real/synthetic provenance**, rights and privacy review, rollback/feature-disable procedure and next-prerequisite status. Never call it “production evidence accuracy achieved” based on fixtures or incomplete manual work. Respect dirty worktree; no surprise pushes/deploys.

**STOP AFTER P3.4. Do not implement P4.1.**
