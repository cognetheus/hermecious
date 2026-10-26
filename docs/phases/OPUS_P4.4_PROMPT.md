# OPUS 5.5 HIGH — HERMECIOUS P4.4: Approval Studio and Immutable Draft Revisions

**ASSIGNMENT:** Implement **P4.4 only**. Approval is content authorization, **not** consent or permission to message. STOP after verification. No P4.5 simulation or P5 WhatsApp.

## Read and verify upstream, not just prose

Read `CLAUDE.md`, `AGENTS.md`, ADRs, `EXECUTION_LEDGER.md`, `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_06_P3.4-P4.2.md`, and **Batch 07 master sections 0, P4.4, 4, 5**. Inspect actual P1.3 published offer capabilities, P3.1 rights/facts, P3.4 live quality eval status, P4.1 campaign, P4.2 immutable drafts and **P4.3 verified current policy evaluator**.

Record SHA/branch/dirty tree, migration head, baseline commands/results, existing approval-related schema. If P4.3 is incomplete or tests fail, mark this subphase `BLOCKED` for real integrations. Do not silently build an alternative permission checker or skip gates. Test-only fixture implementation may proceed only behind an explicit test mode without production eligibility.

## User journey to deliver

A logged-in operator opens a candidate's P4.2 draft, reviews evidence and the **exact current draft version**, edits it (creating a new immutable revision), views the P4.3 eligibility reason, and chooses `Approve content only`, `Reject`, or `Revoke approval`. Every user-visible status is truthful: `approved_content` != `queued`, `sent`, `whatsapp_template_approved` or `production_ready`.

## Explicit data and method contracts

Extend existing `outreach_plans`/draft-revision storage with immutable version, `content_digest`, metadata/provenance/version vector (campaign, offer, assessment, source rights, policy, permission revision), status, reviewer ID, reviewer timestamp, reviewer reason, expected revision and expiry. Store each approval/rejection/revocation as append-only durable, org-scoped audit record; never overwrite reviewed text. Avoid a second shadow `drafts` table when P4.2 already owns it. Reconcile state naming with migrations; no destructive table reset.

Suggested domain boundary:

```python
create_draft_revision(draft_id, edited_text, reason, expected_revision, actor) -> DraftRevisionReceipt
review_draft(draft_id, draft_version, content_digest, decision, reason, actor) -> ReviewReceipt
revoke_content_approval(draft_id, approval_version, reason, actor) -> ReviewReceipt
read_approval_status(draft_id, current_state) -> ApprovalStatus  # status computed from live dependencies
```

- Use optimistic concurrency compare-and-swap and scoped idempotency. Same key+same canonical payload returns same receipt; conflicting body/key yields 409; two reviewers racing cannot both commit inconsistent active revisions.
- Any edit/rewrite creates a NEW revision + digest; older approval becomes stale regardless of semantic similarity. Unicode NFC/canonical encoding must be consistent for preview and digest. Prevent script injection; render plain text safely.
- **Re-validate** message content with P4.2 grounding validator (every factual assertion cites current permitted evidence; only published P1.3 capability). Require sender identity and opt-out wording, no fabricated software deficiencies, false guarantees/pricing or principal identities.
- **Re-evaluate** P4.3 for exact contact/channel/purpose during review and never grant/alter contact permissions. A verified synthetic test permission can prove the code, not real permission to approach schools. If quality gate (30 real schools) incomplete, allow approvals only for **synthetic fixture campaign** stored as `simulation_only=true`; production approval must remain unavailable.
- Approval references **exact contact, business identity and campaign**. If no selected contact, deny approval with actionable reason; draft may still be viewed/edited.
- Revoked consent, opt-out, human takeover, campaign pause/cancel, evidence rights/offer revision, quality gate revocation, account/contact change, content edit -> deny or mark stale. Content approval status cannot bypass current send-time check later.

## Implement in small steps

1. Inventory canonical paths, migrations, draft status and existing P4.2 verifier; create test-first `APPROVAL-01..10` proof matrix. Confirm P4.3 is VERIFIED.
2. Write additive migration with immutable revisions/review audit/uniqueness. Prefer existing audit logging infrastructure where adequate; no duplicate incompatible abstractions.
3. Implement `create_draft_revision`, `review_draft`, reject/revoke transitions as domain services, CSRF and RBAC, expected version/digest checks. DB transaction includes state change + audit. Add event recording only if P1.5 supports **safe non-send** event type. Never enqueue dispatch.
4. Implement freshness read-time evaluator with P4.1/P4.2/P4.3/P3.4/P1.3 current dependency checks; do not rely solely on stale `approved=true` field. Handle revoked/changed permission immediately, including concurrent suppression.
5. Implement org-scoped routes (adapt `/api/v1/outreach-plans/{id}/revisions`, `:approve`, `:reject`, `:revoke-approval`, review history) and UI with masked contact data, source-grounding, version comparisons, badges `Simulation only`, explicit approval wording and blocked reasons. Do not create Send/Queue controls.
6. Run unit/contract/real-Postgres integration/replay/concurrency/UI E2E, injected adversarial draft text and regressions. Prove no outbound side effects. Update ledger with actual command outputs and rollback.

## Ten required gates

| Gate | Prove |
|---|---|
| `APPROVAL-01` | Only current, evidence-supported and **simulation eligible** fixture is content-approved; immutable receipt; zero send |
| `APPROVAL-02` | Content edit/regenerate/locale changes invalidate previous digest/approval |
| `APPROVAL-03` | Rejection and stale re-approval attempts fail safely |
| `APPROVAL-04` | Grounding verifier blocks unsupported claims/injection/unsafe markup |
| `APPROVAL-05` | Suppression/revocation during approval denies or invalidates |
| `APPROVAL-06` | Pause/cancel, source rights, offer, assessment or quality gate change stales approval |
| `APPROVAL-07` | Concurrent reviewers + idempotency behave deterministically |
| `APPROVAL-08` | Org/CSRF/RBAC/contact binding, masking and XSS controls hold |
| `APPROVAL-09` | Restart/replay, explicit revocation and old-revision reopening never restore approval |
| `APPROVAL-10` | UI end-to-end edit→verify→approval→invalidation, no send jobs/provider/network activity |

## Enforce these stop limits

Never activate outbound transport, send a WhatsApp message (even test), upload/approve provider templates, auto-approve generated model text, fabricate consent, implement the simulator or advance into P5. P4.4 is complete only when all implemented gates have real evidence; if real evidence audit/consent missing, report production status **BLOCKED** and keep test-only results separate.

## Final Opus report

SHA, files, migrations, actual API/storage contracts, `APPROVAL-01..10` test table with commands and statuses, sample synthetic revision lineage, concurrency and security results, quality/consent blockers, rollback/feature flag, ledger entry, **`P4.5 implementation-ready?`** and **`live outreach ready? NO`**.

**STOP AFTER P4.4.**
