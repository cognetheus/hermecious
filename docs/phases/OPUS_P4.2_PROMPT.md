# Claude Opus 5.5 High — HERMECIOUS P4.2: Source-Grounded Personalization and Draft Studio

**ASSIGNMENT: IMPLEMENT P4.2 ONLY. GENERATE REVIEWABLE, NON-SENDABLE DRAFTS. STOP AFTER VERIFICATION.**

## 1. Confirm facts before changing code

Read `CLAUDE.md`/`AGENTS.md`, accepted ADRs, `EXECUTION_LEDGER.md`, `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_05_P3.1-P3.3.md` and `docs/phases/HERMECIOUS_BATCH_06_P3.4-P4.2.md` sections **0, P4.2, 4**. Inspect implemented P1.3 published approved offer claims, P3.1 fact/source rights, P3.2 signals, P3.3 current assessment, P3.4 actual quality gate, P4.1 candidate and limits. Run baseline/test and report repo SHA/dirty worktree/migration head. P4.1 must be VERIFIED. Where production quality gate is incomplete, **fixture-only Draft Studio testing is allowed, real customer drafts blocked**.

## 2. Target result

An operator can select an approved-for-drafting (NOT marketing eligible) candidate and create an immutable, rights-compliant first-contact **draft**. Every dynamic business fact references current supported evidence; every product/capability assertion references a **current published P1.3 claim**. The message identifies **CoderzHunt** legitimately, includes a simple opt-out option, asks a respectful discovery question and never invents need, authority, pricing, timelines or software absence. Draft marked `needs_review`, `operator_review_required=true`, `channel_eligibility=not_evaluated`, and **NOT SENDABLE**.

## 3. Concrete implementation steps

1. Map `DRAFT-01..10` to fixtures and expected persisted states. Define typed `draft_contract_v1`, allowed sentence categories, claim-to-text grounding references and strict zero-send authority. Reuse any existing `outreach_plans`; don't create parallel shadow message storage.
2. Pure deterministic template renderer for `school_introduction_v1` and `school_question_v1`; use `en-PK` initially with approved sender profile. `ur-PK`/`roman-ur-PK` only if actual reviewed locale templates exist; otherwise a typed `TEMPLATE_UNAVAILABLE` error. A missing current approved offer claim blocks generation, not placeholder filler.
3. Validate each named fact and approved capability **by ID/revision and explicit rendered span**, attribution/source relevance, rights, freshness and school campus association. A school reception notice permits “your website lists reception form collection”, not “you process admissions manually in Excel.” Unknowns become questions, never factual assertions. Do not make private principal-name guesses.
4. Every draft must include actual sender identity, respectful CTA, opt-out wording (without representing this alone as channel consent). Apply length cap <=650 chars unless stricter existing rule, Unicode safety, XSS-safe rendering and absence of forbidden commercial guarantees. No arbitrary links or contact-address suggestion by model.
5. Persist immutable draft revision with exact campaign, membership, assessment, offer, source policy versions and fingerprint; real approval needs P3.4 gate and valid manually approved P4.1 candidate. Transaction must lock/recheck latest evidence, quality, offer publication, campaign pause/exclusion and daily quota. Retry with same scoped idempotency returns one logical draft; conflicting request key=>409.
6. Implement typed `/api/v1/campaigns/{id}/accounts/{account_id}/drafts` and read/regenerate endpoints adapted to actual routing conventions. All mutations operator/owner + CSRF; reads org-scoped observer+; preserve earlier revisions and audit. `regenerate` always creates new version with reason, not overwrite.
7. Implement Draft Studio on the existing campaign/account UI: draft text, narrow explanation for chosen school signal, evidence-to-sentence drilldown, source time and rights status, P1.3 offer claim version, unknown discovery questions, language selector only for reviewed templates, and **large “DRAFT ONLY — NOT APPROVED FOR SENDING”** notice. No Send, Approve, Queue, Schedule or provider-connect controls.
8. Optional use of ModelGateway **only if already vetted and configured**: schema-limited suggestion, strict inputs/egress, timeout/token/attempt budget, treat all model output as untrusted. Run final deterministic verifier; if hallucination/injection/unauthorized link occurs, use verified deterministic fallback or abstain. Local deterministic path must work without LLM credentials/internet.
9. Implement invalidation on account correction/identity, source rights expiry/revocation, offer version/status, assessment revision, campaign editing/pause, exclusion or quality-gate failure. Changes make previous drafts `blocked_stale` and never silently approved/reusable. Preserve audit under legal retention rules.
10. Run positive, negative and E2E tests `DRAFT-01..10`, plus P1.3/P3/P4.1 regressions, race/timeout/replay/restart and data retention checks; verify **zero** outbound/consent/send/approval side effects. Self-review and ledger update with evidence. STOP.

## 4. Required ten acceptance gates

- `DRAFT-01`: identity + consent-neutral opt-out + approved capability and rights-safe current source mapping, immutable persisted version.
- `DRAFT-02`: reception notice does not yield invented Excel/manual admissions/software deficiency.
- `DRAFT-03`: revoked, stale, metadata-only or wrong-campus claim excluded; downgrade to generic or block.
- `DRAFT-04`: unpublished offer or hallucinated product price/discount/timeline rejected.
- `DRAFT-05`: missing identity, opt-out, insulting wording, imaginary principal or locale unsupported => validation failure.
- `DRAFT-06`: hostile research text/model instruction/template output never changes permissions/contacts/sends.
- `DRAFT-07`: idempotency and concurrent requests yield one logical draft/quota; regeneration preserves history.
- `DRAFT-08`: campaign pause/exclusion/source change/offer change/quality-gate revocation invalidates old drafts.
- `DRAFT-09`: CSRF, RBAC, cross-org, Unicode, XSS and privacy protections hold with zero leaked data.
- `DRAFT-10`: full synthetic gated UI campaign→draft→evidence drilldown→restart plus regressions; **no messages/sending jobs/provider calls**.

## 5. Deliver and stop

Return changed files, migrations, actual routes/types, complete `DRAFT-01..10` proof table and commands/exit status, draft example clearly synthetic and **not sent**, limitation of real production quality-gated campaign access, P1.3 claim grounding examples, privacy/sending authority audit, rollback/feature-disable, `P4.3 READY/BLOCKED` judgment and update `EXECUTION_LEDGER.md`.

**NEVER** implement P4.3 permission evaluator, P4.4 outbound approval, P4.5 simulator, P5 official WhatsApp transport or send from this prompt. **STOP AFTER P4.2.**
