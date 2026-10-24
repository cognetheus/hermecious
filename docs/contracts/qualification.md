# Qualification contract (P3.3)

Decision record: [ADR-018](../adr/ADR-018-four-axis-qualification.md). Code: `apps/api/app/qualification/`.

## Endpoints

| Route | Roles | Behaviour |
|---|---|---|
| `POST /api/v1/accounts/{id}/assess` | owner, operator (CSRF) | `{offer_id?}`. Refreshes the P3.2 brief. 201 creates a new revision; 200 returns the latest when inputs are unchanged. An offer from another organization gives 404 |
| `GET /api/v1/accounts/{id}/assessments` | any | `{latest, needs_reassessment, history[≤20], signal_snapshots}` |
| `POST /api/v1/accounts/{id}/assessments/{assessment_id}/override` | owner, operator (CSRF) | `{expected_revision, reason (3–1000), decision?, dimensions?, evidence_fact_ids?[≤10]}` gives 201. Responses: 409 for a stale revision, a non-latest assessment, or a conflict with a hard disqualifier; 400 for no change or foreign evidence; 422 for unknown fields or values |

## Assessment view

| Field | Meaning |
|---|---|
| `dimensions.{customer_fit, need_evidence, accessibility, delivery_fit}` | `{value, machine_value, reason, fact_ids, questions}` |
| `decision` / `machine_decision` | `contact_now`, `investigate`, `nurture` or `exclude` |
| `decision_text` | For `contact_now`: "Research priority: contact candidate — channel eligibility not checked." |
| `blocking` | Why the account is not `contact_now` |
| `questions` | Open questions |
| `channel_eligibility` | Always `not_evaluated` |
| `probability` | Always `null` |
| `revision`, `origin`, `rubric_version`, `offer_id`, `offer_revision_id`, `capability_version`, `override_reason`, `changed_fields` | Provenance and override details |

## New P1.2 claim types

| Claim type | Value | Effect |
|---|---|---|
| `hard_disqualifier` | `{reason: school_closed \| not_a_school \| outside_service_area \| declined_vendor_contact}` | `exclude` when cited, current and auditable |
| `review_deferral` | `{reason: asked_to_reconnect_later \| contract_in_place \| budget_cycle \| term_in_progress, until: YYYY-MM-DD}` | `nurture` while in force when cited. Nothing is scheduled |

Both drive decisions **only** when they are source-supported, current and auditable. An unverified entry yields `investigate` with a question.
