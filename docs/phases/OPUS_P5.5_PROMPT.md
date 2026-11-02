# OPUS 5.5 HIGH — HERMECIOUS P5.5 | Production Go/No-Go + Operator-Only Pilot Gate

**YOUR ASSIGNMENT: IMPLEMENT P5.5 ONLY.** Deliver an audited, conservatively blocked production eligibility review and separately guarded operator-only single-send pilot infrastructure. **NO REAL PRODUCTION WHATSAPP MESSAGE is authorized by this prompt.** All coding tests use fake transports; keep `HERMECIOUS_LIVE_OUTBOUND_ENABLED=false` in automated environments and after this task. A readiness report, a provider-approved template, and a human-edited draft are not permission to contact a business. STOP after P5.5.

## Required inventory (do not assume earlier phases are finished)

1. Read `CLAUDE.md` / `AGENTS.md`, ADRs, `EXECUTION_LEDGER.md`, actual git branch/dirty state, migrations, security/CI baseline and existing architecture.
2. Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` P3.4, P4.1–P4.5, P5.1–P5.5; master `docs/phases/HERMECIOUS_BATCH_09_P5.4-P6.1.md` sections 0, P5.5 and 4–6; Batch 07 and 08 plans and implementation ledgers.
3. Identify actual implemented P4.3 consent/suppression evaluator, P4.4 exact-version approvals, P4.5 dry run, P5.1 transport, P5.2 signed callbacks, P5.3 `WATEST-10` real test verification, P5.4 read-only inbox. Check true P3.4 30-school manually validated evidence audit, never accept synthetic sample as the real gate.
4. Recheck live official Meta WhatsApp Business policy/provider account in the user's authorized environment; official policy as of 2026-09-23 requires opt-in, approved initiation templates, 24-hour ordinary reply window and human escalation. Meta verification/app permissions vary by account; do not assert statuses you cannot observe. Document Pakistan-local legal compliance review as **human decision**, not a model-verified fact.
5. Produce prerequisite matrix with `VERIFIED|FAILED|UNKNOWN|BLOCKED_EXTERNAL`, actual evidence path and owner. Missing live Meta credentials/verified real test receipt/consent/real audit means `NO_GO`, not a reason to bypass.

## Deliverable / guarded workflow

Authenticated owner opens **WhatsApp Production Readiness**, reviews reproducible read-only evidence, blockers and expiry; an evaluation returns `NO_GO`, `BLOCKED_EXTERNAL`, or `READY_FOR_OPERATOR_REVIEW`. **None** of these states sends messages. A separate future owner action may authorize a scoped 1:1 pilot; a distinct deploy-time live enablement is also required. Only their combined, still-fresh presence can make a manual preview/confirm request eligible. Opus must not perform that go-live action or enable live sending while executing this prompt.

## Implement in strict order

**1. Auditable prerequisites.** Define typed, immutable `ReadinessAssessment` with snapshot version/digest, org, Meta WABA/phone identity fingerprints, code SHA, checked-at/expiry, reviewer and evidence refs, reasons for unknown/failure. Check real P3.4 30-account >=90% support evaluation (for prospect campaigns), provider/test identity proof, test WATEST-10, signed callback health, production account permissions as applicable, verified Meta template category/language/current status, P4.3 opt-in scope/source/time and suppression, current P4.4 immutable draft revision, P5.4 operator inbox, local legal review sign-off, rate/quality/feedback monitoring, backup/kill/rollback readiness. Do not use a naked user-entered `is_verified:true` as proof.

**2. Fail-closed state machine.** `no_go|blocked_external|ready_for_operator_review`, with typed blockers, freshness, invalidation on template revocation, code/deploy config, provider identity, contact revocation, quality, signed callback failure or pilot-specific evidence changes. A ready report alone must not grant send permission. Keep distinct review of *global provider readiness* versus *per-contact/purpose send eligibility*. No implicit campaign enrollment.

**3. Operator authorization.** Add separately persisted narrowly scoped `PilotAuthorization` with owner identity, explicit independent consent to the pilot, one fixed production connection, recipient selection from previously verified opted-in contact registry, approved purpose, expiry, hard caps (start recommended maximum 3 manual messages/day, configurable stricter), no bulk, kill switch/revocation, full audit. `READY_FOR_OPERATOR_REVIEW` is not permission; require both pilot authorization and independent env/deployment enablement. Auth must be owner-only with CSRF and fresh re-auth where current app supports it. Never let model, job, admin CSV, or UI preview set env/live flag.

**4. Safe potential dispatch path (fake in tests only).** If existing P5.1 has a prepared transport contract, implement the *smallest* guarded operator-only preview/confirm service: server-resolved recipient, exact approved P4.4 revision and Meta template/language/parameters; short-lived immutable digest+nonce; no arbitrary `phone_number`, `template_status=approved`, `skip_consent`, `campaign_send`, `account_id` string as target. Recheck P4.3, quiet hours `Asia/Karachi`, 24-hour customer window vs template, P3.4 where prospect campaign applies, template live status, suppressions, global/connection kill, human takeover and quotas immediately before network boundary. Only after all checks could a future separately authorized owner call official P5.1 production transport. Prevent sending from Opus run, CI, fixtures, or automatic jobs.

**5. Idempotent attempt and recovery.** Reserve attempt transactionally; concurrent confirm one reservation; key+same payload returns same result, changed payload 409; safe graph statuses and signed P5.2 reconciliation. Provider 200 `wamid` means **accepted** only, not delivered; timeout after possibly accepted means `indeterminate` and **never** automatic replay; provider 401/429/5xx handled with safe error/circuit breaker. Global stop cancels future attempts but cannot recall already accepted Meta messages. Preserve history for manual investigation.

**6. UI/operator runbook.** Show human-readable check list, actual evidence and fresh/stale states, masked provider IDs, blocked reasons, capacity/quiet-hours and operator's rollback procedure. Explicit persistent warning: `PRODUCTION OUTBOUND DISABLED UNTIL SEPARATE OPERATOR GO-LIVE`. No automatic mass-send button. Implement safe reports/audit without raw numbers/tokens. Add a clear operator escalation path for real inbound customers, no AI responses.

**7. Prove negative cases and stop.** Run lint/type/schema, migrations in disposable DB, unit/integration/E2E, concurrency, fake provider and zero-egress tests. Check CI cannot turn on real sending, no production Graph traffic, no P3.4 fixtures disguised as production proof, no automatic campaign send handlers. Self-review and rerun failed tests.

## Exact acceptance gates

| Gate | Required evidence |
|---|---|
| `RELEASE-01` | Unverified Meta identity/permissions, webhook or real test receipt => NO_GO/BLOCKED_EXTERNAL |
| `RELEASE-02` | P3.4 real-school audit absent/failing => school campaign activation denied |
| `RELEASE-03` | Meta template status/category/language/parameters and exact approved content revision checked fresh |
| `RELEASE-04` | Missing/revoked consent, suppression or Pakistan-local compliance review blocks |
| `RELEASE-05` | Audited, expiring, digest-bound checklist with credible evidence refs; secrets never exported |
| `RELEASE-06` | Ready checklist alone never sends; both independent owner pilot approval+live env gate required |
| `RELEASE-07` | Operator-only 1:1 exact-revision preview/confirm, caps, nonce, CSRF and hours deny bypass |
| `RELEASE-08` | Concurrency/timeouts/rate limit/kill/crash = bounded, replay-safe outcome, no uncertain auto-retry |
| `RELEASE-09` | Revocation, opt-out, quality alert or human takeover blocks unsent work and preserves past observations |
| `RELEASE-10` | All automated tests prove **zero real production sends**; no false go-live claim or external gate bypass |

## Mandatory adversarial and race tests

- School public listing phone pasted as candidate without opt-in; expired consent; consent for a different business/purpose; contact opted out between preview and confirm.
- Business verification unknown, wrong WABA/production ID, Meta sandbox test number presented as production; provider template status changes from approved to paused.
- Stale P4.4 digest after edit or P1.3 offer change; P3.4 last real audit not present; user forges readiness report ID from another tenant.
- Human takes over/connection paused just before queued attempted send; kill switch between DB reservation and Graph call; two confirms with same nonce.
- Provider timeout after possibly accepting, 429/401/5xx, duplicate callback, out-of-order status and operator accidentally repeats a send.
- UI CSRF/role bypass, token/number leaking via logs/exports, unsafe automatic enablement in CI/Compose, tests accidentally accessing Internet.

## Scope exclusions and verdict

Do NOT initiate actual live provider transmission, change deployment live flag to true, alter Meta account or apply to live school prospects. Do not add campaign bulk dispatch, no autonomous messages, no LLM policy overrides. Missing external credentials and human signoff are a real **external blocker**; implement safe code and leave activation blocked. If earlier phases are missing, document exact interface gaps without rewriting P4/P5 code outside this limited scope.

Report base/final SHA, files/migrations/DTOs, 10 gates with actual commands and exit codes, review decisions, Meta external evidence availability, policy checks, rate/retry state, QA, zero-egress proof, explicit `PRODUCTION OUTREACH READY: NO` unless independent signoff is genuinely present (even then **NO MESSAGES SENT BY THIS RUN**), rollback, ledger status. Only `VERIFIED` when real requirements met; mock evidence cannot satisfy provider or real-world policy signoff.

**STOP AFTER P5.5. DO NOT BEGIN P6.1 UNTIL P5.5 ENGINEERING IS VERIFIED OR ITS EXTERNAL BLOCKERS ARE EXPLICITLY RECORDED AND P6.1 IS RESTRICTED TO OFFLINE CLASSIFICATION.**
