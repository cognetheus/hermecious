# Draft Studio contract (P4.2)

Decision record: [ADR-021](../adr/ADR-021-grounded-draft-studio.md). Code: `apps/api/app/drafts/`. UI: `/campaigns/{id}/accounts/{account_id}`.

> **DRAFT ONLY — NOT APPROVED FOR SENDING.** Every draft has `sendable: false`, `operator_review_required: true` and `channel_eligibility: not_evaluated`. These are database-enforced.

## Endpoints

| Route | Roles | Behaviour |
|---|---|---|
| `POST /api/v1/campaigns/{cid}/accounts/{aid}/drafts` | owner, operator (CSRF) | `{template_id, locale, idempotency_key}`. 201 on create, 200 on replay. 409 for blockers (paused, excluded, gate, stale evidence, offer not published, budget) or a reused key with a different request. 422 for `TEMPLATE_UNAVAILABLE`, `OFFER_CLAIM_UNAVAILABLE` or `VALIDATION_FAILED: …` |
| `GET /api/v1/campaigns/{cid}/accounts/{aid}/drafts` | any | All revisions, newest first, each with its effective `status` (`needs_review` or `blocked_stale`) and `stale_reasons` |
| `GET /api/v1/drafts/{id}` | any | One draft: `body_text`, plus `sentences[{category, text, grounding, source?{provider, rights_policy_version, source_url, expires_at, rights_current}}]` |
| `POST /api/v1/drafts/{id}/regenerate` | owner, operator (CSRF) | `{reason, idempotency_key, template_id?}`. Creates a new revision; earlier revisions stay unchanged |

## Example (synthetic fixture; **not sent**)

> Assalam-o-Alaikum, This is the CoderzHunt team in Lahore. We noticed that your school lists 2 campuses. Our team offers admissions_intake module for schools. Who usually decides on new administration tools for this campus? If it would help, could we share a short overview with you? If you would prefer not to hear from us, just reply STOP and we will not contact you again. — CoderzHunt, Lahore

**Grounding for that example:**
- "lists 2 campuses" cites one usable, source-supported `campus_count` fact.
- "admissions_intake module" cites a sales-approved claim of the published offer revision.
- The question cites the P3.2 `operator_autonomy` unknown.
