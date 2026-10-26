# ADR-023: Content approval is an append-only, simulation-only receipt bound to one exact revision, re-validated on every read

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" after reviewing the audit; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-24
- **Source:** `OPUS_P4.4_PROMPT.md`; blueprint §4 P4.4 ("expire approval on material change"). Batch 07 is absent from the repository.

## Context

- **Drafts (P4.2, ADR-021)** are immutable revisions in `drafts`. No `outreach_plans` table exists. P4.4 extends `drafts` instead of adding a shadow table.
- **Channel eligibility (P4.3, ADR-022)** is a read-only policy reading.
- **The P3.4 quality gate is closed** (EVAL-07).

## Decision

### 1. Edits are new revisions built only from grounded or reviewed sentences

`POST /drafts/{id}/revisions` stores an edit as a new `drafts` row:
- `origin = 'edited'`, linked through `regenerated_from`, with a reason;
- a compare-and-swap on `expected_revision` under the campaign lock.

The edited text is canonicalised (NFC, collapsed whitespace) and must decompose, longest match first, into sentences from a library:
- the reviewed template sentences;
- one observation per currently usable fact;
- one capability sentence per sales-approved claim of the pinned offer revision;
- the P3.2 discovery questions.

Anything else gives `UNGROUNDED_TEXT`: new wording, markup, prices, names, links, or a reworded claim. Repeats give `DUPLICATE_SENTENCE`. The P4.2 verifier then runs; it now also requires the identity sentence itself, not just the sign-off.

**Why so strict.** There is no reviewed phrase bank or model, so free wording cannot be grounded. Operators can drop, reorder and swap grounded sentences.

### 2. Reviews are append-only receipts (migration 0017, `draft_reviews`)

Each row is one decision on one revision: `approved_content`, `rejected` or `revoked`. It records:
- the content digest (SHA-256 of the canonical body) and the reviewer, time and reason;
- for approvals: the contact, purpose `marketing`, template reference, eligibility decision, an expiry of 7 days, and a **version vector**: campaign revision and rules, offer revision and capability version, assessment, cited facts, source rights versions, business identity, policy version, permission revision and suppression revision.

**Database guards:**
- `simulation_only` is always true;
- an approval must bind a contact, template, expiry and an `allow_for_simulation` or `defer` eligibility decision;
- a `revoked` row must point at the approval it revokes;
- uniqueness on (draft, seq) and (org, idempotency key);
- an append-only trigger.

### 3. Approve, reject and revoke

All three lock the campaign row, which serialises reviewers, and are idempotent: the same key and request return the same receipt, and a different request returns 409.

| Command | Requirements |
|---|---|
| **Approve content only** | The digest must match. The revision must be the latest. There must be no Draft Studio staleness, the grounding must still be in the current library, and the campaign must be a **fixture** (live: `production_approval_unavailable`). The contact must belong to the draft's account (`NO_CONTACT_SELECTED`, `CONTACT_NOT_FOR_ACCOUNT`). A template is required. P4.3 must not deny. Not allowed while an approval is current, or after a rejection (edit instead) |
| **Reject** | The digest must match. Not allowed while approved (revoke first), or twice |
| **Revoke** | Only the current approval can be revoked |

### 4. Status is computed, never stored

`approval.state` comes from the latest receipt:
- `not_reviewed`, `rejected` or `revoked`;
- or, for an approval: `approved_content` if every dependency is still current, otherwise `approval_stale` with reasons.

The dependencies checked are expiry, newer revision, Draft Studio staleness (pause or cancel, exclusion, gate, rules, offer, assessment, evidence, cited-fact rights), grounding, a live P4.3 re-decision (suppression, revoked or expired permission, template, kill switch), permission revision and campaign revision.

Replays, restarts and older revisions cannot restore an approval. Every view also returns `queued: false`, `sent: false`, `whatsapp_template_approved: false` and `production_ready: false`.

### 5. Approver

Operators and owners can approve content. Content approval is not a send, a permission grant or a policy decision. It is still bound to the P4.3 decision, which needs owner-verified evidence.

## Consequences

- **Real approvals are impossible** while the P3.4 gate is closed and before P5 provides templates.
- **Send-time checks.** P4.5 and later must re-run eligibility; a content approval never replaces the send-time check.

## Rollback

- **Stop:** stop using the review endpoints; receipts are history.
- **Schema:** downgrade 0017 only on a disposable database.
