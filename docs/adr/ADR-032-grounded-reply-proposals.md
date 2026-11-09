# ADR-032: Grounded reply proposals: rules-only drafts from one published offer, never sent

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-11-09
- **Source:** the owner's P6.2 prompt; blueprint §4 P6.2 ("no unsupported price, features, dates or claims"). `docs/phases/HERMECIOUS_BATCH_10_P6.2-P6.4.md` is not in the repository.

## Context

- **P6.1:** not verified. INTENT-07 is BLOCKED (no human review) and INTENT-08 is BLOCKED_QUALITY.
- **P5.5:** NO_GO.
- **Models:** no model gateway exists.

## Decision

1. **Rollout gate.** `HERMECIOUS_REPLY_PROPOSALS` takes one of three values:
   - `off`: the default; generation refuses.
   - `fixtures`: refused in production; for synthetic data in test and development.
   - `inbound`: refuses to start without `HERMECIOUS_INTENT_GATE_SIGNED_BY` and `_AT`, a named human statement that the P6.1 intent gate passed on human-reviewed data.

   **Rollback:** set `off`. Stored proposals and reviews stay (append-only); nothing is approved or sent.
2. **Contract `reply.v1`** (`app/replies/schema.py`). It is validated before storage.
   - **Fields:** `status` (proposed/abstained), `proposed_reply|null`, the exact P6.1 `intent` and observation id, `safety_flags`, `confirmed_facts`, `open_questions`, `missing_claims`, `recommended_action`, `escalate`, `citations`, `snapshot`, `abstention_codes`, provenance (`composer_version`, `policy_version`, `model_version: null`, `prompt_version: null`, `tool_calls: 0`).
   - **`confirmed_facts`:** only spans quoted from the signed message, `attribution: prospect_stated`, `verified: false`.
   - **`recommended_action`:** a fixed, non-executable allowlist (`review_draft`, `manual_review_missing_claim`, `human_handoff`, `opt_out_review_no_reply`, `abuse_review_no_reply`, `manual_triage`).
   - **Never present:** recipient, tool, transport, consent, owner or opportunity fields.
3. **Knowledge** (`app/replies/knowledge.py`):
   - only the **currently published** revision of a same-org, `schools`-vertical offer, read through P1.3's own `content_of`;
   - its claims were validated at publication (`assert_publishable`: sellable readiness, evidence, approval note, no commitment wording);
   - a claim whose newest evidence is older than 365 days is excluded as expired;
   - approved price rules are the only price knowledge;
   - the only locale is `en`, because approved wording exists only in English;
   - each claim carries a digest over offer, revision, content hash and claim;
   - no vector store, search, web access or historical revision.
4. **Proposer** (`app/replies/composer.py`, `reply-rules-1.0`): deterministic, with no model.
   - **Safety first:** opt-out → no reply; abuse → no reply; injection (the P6.1 flag **or** the proposer's own check) → triage; a request for a person → handoff, which wins over a details question; sensitive personal data → triage with nothing quoted; unavailable content; unsupported language; unmatched contact.
   - **Then what was asked:** a capability needs a claim, a price needs an approved rule, and migration, timelines, guarantees, integrations, SLA, discounts and ROI always need a person. Anything unanswered → abstain, naming the missing claim. An ambiguous intent never gets a draft.
   - **Draft:** fixed template sentences plus approved claim text **quoted verbatim**, each with a citation. Non-English inbound → an English draft marked `language_fallback`; nothing is translated.
   - **Independent verifier:** every sentence asserting a capability, price, discount, timeline, guarantee, integration, migration, SLA or ROI must cite a digest in the snapshot, otherwise the result is an abstention. The same verifier applies to any future model output.
5. **Persistence** (migration 0027, append-only):
   - **`reply_proposals`:** unique per (organization, message, input digest), so a replay returns the same proposal. `lineage_seq` versions are serialized by locking the conversation's thread.
   - **Staleness is computed on read:** a stored draft is `stale` when its inputs change (intent observation or classifier version, offer revision or claims, content state, composer or policy). History is never rewritten.
   - **`reply_proposal_reviews`:** reject only, audited.
6. **API and UI.**
   - **Routes:** `POST/GET /api/v1/inbox/whatsapp/messages/{id}/reply-proposals` and `POST …/{proposal_id}/reject`. Owner and operator, CSRF; observers 403.
   - **Binding:** the message must be on the organization's enabled connection and inside its P5.4 conversation; a supplied `conversation_id` must match.
   - **Inbox UI:** a "Suggested reply" panel beside each inbound message, labelled **DRAFT — NOT SENT** / **ABSTAINED** / **STALE**, with citations, stated facts (unverified), missing claims, "rules only, no model · nothing here is sent", and a reject form. There is no send or approve control.

## Consequences

- Real-inbound use waits for a human sign-off of P6.1. The feature is proven on synthetic signed messages, a real published P1.3 offer and a 72-case policy corpus.
- P4.4 approval of reply content and any send path belong to P6.5, behind P6.3's dispatch fence and P5.5.
