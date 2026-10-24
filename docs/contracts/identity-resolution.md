# Campus identity resolution contract (P2.3)

Decision record: [ADR-014](../adr/ADR-014-campus-identity-resolution.md). Code: `apps/api/app/resolution/`. Gold fixtures: `apps/api/tests/fixtures/identity_gold_v1.json`.

> A suggestion is not a merge. Only a human decision creates an association, every decision is appended to history, and undo never deletes sources, candidates, accounts or facts.

## Outcomes

| Resolution | When | Stored? |
|---|---|---|
| `exact_reobservation` | Same organization, provider and external key | No: P2.2 staging updates the one candidate row (revision and audit with the previous values) |
| `suggest_review` | Similar same-script names with the same locality or precise points ≤150 m apart; or different names at precise points ≤50 m apart | Yes, `pending` |
| `insufficient_evidence` | Similar names but no site evidence, area-centre ambiguity, same provider with different ids, no comparable script, or a missing city | Yes, `pending` |
| `distinct` | Different city, branch, locality or coordinates; dissimilar names; a chain domain without site evidence | No; counted in the run report |

**Reason codes:**
- `same_provider_same_external_key`
- `different_city`, `missing_city`
- `conflicting_branch`, `different_locality`, `coordinate_conflict`
- `no_comparable_name_script`, `name_dissimilar`, `co_located_different_names`
- `name_exact`, `name_near`
- `same_locality`, `coordinates_near`, `area_center_ambiguous`, `locality_unknown`
- `same_provider_distinct_ids`
- `shared_domain_weak`, `chain_without_site_evidence`

**Feature keys** (labels and scores only, never upstream text):
- `buying_authority` (always `unknown`)
- `same_provider`, `city`
- `name_match`, `name_similarity`, `name_script`
- `branch`, `locality`
- `distance_km`, `location_precision`
- `domain`

## HTTP

| Route | Roles | Notes |
|---|---|---|
| `POST /api/v1/identity/resolve` | owner, operator (CSRF) | Synchronous run. Returns `algorithm_version`, the candidate and account counts, `pairs_considered`, `skipped_common_blocks`, `outcomes`, and the created, recomputed, superseded and unchanged counts plus `evidence_changed_on_reviewed`. Writes a `identity.resolution_run` audit |
| `GET /api/v1/identity/suggestions?status=&limit≤50` | any role | Organization-scoped. Each item carries both sides' summaries, features, reasons, status, version and `buying_authority: unknown` |
| `GET /api/v1/identity/suggestions/{id}` | any role | The above plus the decision history; 404 across organizations |
| `POST /api/v1/identity/suggestions/{id}/decisions` | owner, operator (CSRF) | Body `{command_id, action, expected_version, reason (3–1000)}`; extra fields give 422. Returns the suggestion plus `decision_id`, `replayed`, `held_fact_ids` and `link_id` |

**Response codes for decisions:**
- **409:** a stale `expected_version`, a reused `command_id` with a different payload, a transition that is not allowed, a candidate already linked to another account, or an undo still blocked by held facts.
- **403:** observers, or a missing CSRF token.
- **404:** the suggestion belongs to another organization.

## State machine

```
pending ──confirm──▶ confirmed ──undo──▶ undone ──(confirm | mark_distinct | defer)──▶ …
   │                    │
   │                    └─undo with held facts──▶ reallocation_review ──undo (facts corrected)──▶ undone
   ├─mark_distinct──▶ distinct ──undo──▶ undone
   └─defer──▶ deferred ──(confirm | mark_distinct | undo)
```

**Resolver re-runs:**
- An open suggestion whose evidence changed is recomputed (version +1), or becomes `superseded` if the pair is now distinct.
- A reviewed suggestion keeps its status and version and gains `evidence_changed_at`.

## Tables (migration 0008)

**`identity_suggestions`**
- Unique on `(org, left, right, algorithm_version)` or `(org, left, account, algorithm_version)`.
- `left_candidate_id < right_candidate_id` (canonical order).
- Exactly one counterpart: another candidate or an account.

**`identity_decisions`**
- Append-only (a trigger raises on UPDATE or DELETE).
- Unique on `(org, command_id)`.

**`candidate_account_links`**
- One active link per candidate (partial unique index).
- Ending a link sets `unlinked_at` and `unlinked_by` together.

**Foreign keys:** all are composite with `organization_id`, so cross-organization links are impossible at the database level.

## Limits stated honestly

- **Gold-set scope:** results are measured on 26 fictional, labelled pairs (`campus-identity-gold-v1`): 3 exact, 6 suggest, 11 distinct, 6 insufficient, and **0 automatic merges of different identities**. That is not a general accuracy figure.
- **Blocking limit:** blocks of more than 60 candidates sharing one token are skipped (`skipped_common_blocks`). Pairs that share only very common tokens are not proposed.
- **Transliteration:** Urdu and English are never matched to each other through transliteration.
