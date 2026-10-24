# ADR-021: Drafts are deterministic, source-grounded, immutable and never sendable

- **Status:** Accepted
- **Date:** 2026-10-24
- **Source:** `OPUS_P4.2_PROMPT.md`; blueprint §4 P4.2. Batch 06 is absent from the repository.

## Decision

### 1. Contract `draft-contract-1.0`

A draft is a list of typed sentences:

| Kind | Content |
|---|---|
| Static (reviewed template text) | `greeting`, `identity` ("This is the CoderzHunt team in Lahore."), `generic`, `cta`, `opt_out` ("If you would prefer not to hear from us, just reply STOP and we will not contact you again."), `signoff` |
| `observation` | Exactly one current, usable fact. It says only what the source says (for example "your public page describes your admissions process"), never a tool, process or deficiency |
| `capability` | Exactly one sales-approved claim of the campaign's pinned **published** offer revision (code and `content_sha256`) |
| `question` | A P3.2 discovery question for an unknown area |

The opt-out is consent-neutral: it is not a permission record.

### 2. Templates

`school_introduction_v1` and `school_question_v1`, in `en-PK` only. Urdu and Roman Urdu return `TEMPLATE_UNAVAILABLE` until reviewed templates exist. A missing published claim gives `OFFER_CLAIM_UNAVAILABLE`, never placeholder text.

### 3. Verifier

The verifier runs on the final text whatever produced it. It requires the sender identity and the opt-out, and at most 650 characters. It rejects:
- links, emails and phone numbers;
- personal names and honorific-name patterns;
- prices, discounts, timelines and guarantees;
- deficiency claims (Excel, manual, paper, no software, lacks …) and insults;
- control or bidi characters and instruction text;
- ungrounded observation or capability sentences.

No model is configured, so there is no model path.

### 4. Persistence (migration 0015, `drafts`)

Drafts are append-only. Database checks enforce:
- `status = 'needs_review'`;
- `operator_review_required`;
- `NOT sendable`;
- `channel_eligibility = 'not_evaluated'`;
- body ≤650 characters.

Each draft records the campaign, the membership, the assessment id and revision, the offer revision and capability version, the snapshot, the cited fact ids, the source rights versions and a fingerprint. An idempotency key with a request digest makes replays safe; regeneration appends a revision with a reason.

### 5. Gating

**At generation**, under the campaign lock, everything below is re-checked:
- the campaign is open;
- the gate is open (live) or the campaign is a non-production fixture;
- the account is approved for drafting and not excluded;
- the rules, offer and assessment are unchanged and the evidence is current;
- the offer is published;
- the drafts budget (Asia/Karachi day) allows it.

**At read time**, the same checks plus "the cited facts are still current and usable" produce `blocked_stale` with reasons. The stored row is never rewritten.

## Consequences

**Real customer drafts are impossible** until the P3.4 gate opens (EVAL-07). Fixture drafts are labelled test-only.

## Rollback

- **Stop:** stop generating drafts.
- **Keep:** drafts are history.
- **Schema:** downgrade 0015 only on a disposable database.
