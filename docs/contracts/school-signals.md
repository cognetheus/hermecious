# School operations brief contract (P3.2)

Decision record: [ADR-017](../adr/ADR-017-school-operations-brief.md). Code: `apps/api/app/signals/`.

## Snapshot view

| Field | Meaning |
|---|---|
| `id`, `rubric_version` (`school-signals-1.0`), `input_digest`, `inputs`, `linked_listings`, `created_at`, `created_by` | Identity and inputs of the snapshot |
| `signals` | Exactly six keys in canonical order (below), each a `Signal` |
| `citations` | `fact_id → {claim_type, verification_status, observed_at, superseded, has_excerpt, source{provider, source_url, storage_class, expires_at, expired}}` |
| `ranking` | Always `null` |

The six signal keys, in order: `campus_footprint`, `operator_autonomy`, `admissions_workflow`, `fee_process`, `public_contact_route`, `operational_complexity`.

Each `Signal` contains:
- `state`: `observed`, `hypothesis`, `conflicting` or `unknown`;
- `statement` and `caveat`;
- `question`: one discovery question;
- `fact_ids`, `conflicting_fact_ids` and `stale_fact_ids`;
- `freshness`: `current`, `aging` (over 365 days), `stale` or `none`;
- `evidence_at`.

## Rules worth remembering

- **Unknown stays unknown.** It is never "no", "weak" or "false".
- **What notices do not show:**
  - a reception or online admission notice says nothing about internal tools;
  - fee instructions say nothing about reconciliation or arrears;
  - a public phone, email or form is not consent and not owner access.
- **What a listing does not show:** a single map listing or brand says nothing about campus count or buying autonomy.
- **Conflicts** keep both citations.
- **Expired or metadata-only evidence** never certifies an observation.

## Endpoints

| Route | Access |
|---|---|
| `POST /api/v1/accounts/{id}/school-signals/generate` | owner, operator (CSRF). 201 created; 200 when the same evidence replays the existing snapshot |
| `GET /api/v1/accounts/{id}/school-signals` | any role. Returns `{latest, needs_reassessment, current_input_digest, history[≤20]}` |
| `GET /api/v1/school-signal-snapshots/{id}` | any role, organization-scoped (404 across organizations) |
