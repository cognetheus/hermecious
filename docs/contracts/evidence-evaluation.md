# Evidence evaluation contract (P3.4)

Decision record: [ADR-019](../adr/ADR-019-evidence-quality-evaluation.md). Code: `apps/api/app/evaluation/`. UI: `/quality`.

## Endpoints

| Route | Roles | Behaviour |
|---|---|---|
| `POST /api/v1/evidence-evals` | owner, operator (CSRF) | `{kind: baseline\|post_remediation, seed, idempotency_key, baseline_run_id?, allow_synthetic?}`. 201, or 200 on replay. A reused key with a different request gives 409. `allow_synthetic` is refused in production |
| `GET /api/v1/evidence-evals[/{id}]` | any | The run (and its items), with `state`: PASSED, FAILED, BLOCKED, INCOMPLETE or READY_TO_FINALIZE |
| `GET /api/v1/evidence-evals/{id}/report` | any | Redacted export: counts, fingerprint, items and verdict history. Reviewer ids only; no excerpts or contact details |
| `POST /api/v1/evidence-evals/{id}/items/{item_id}/verdict` | owner, operator (CSRF) | `{verdict, reason, expected_version}`. 409 when stale, finalized, or `supported` on evidence that is not usable or is contradicted |
| `POST /api/v1/evidence-evals/{id}/items/{item_id}/remediate` | owner, operator (CSRF) | `{reason}`. Failed fact items only. Demotes the fact through a P1.4 correction and records the link. Replay-safe |
| `POST /api/v1/evidence-evals/{id}/finalize` | owner, operator (CSRF) | `{expected_version}`. 409 while items are unreviewed. Replay-safe |
| `GET /api/v1/evidence-evals/gate` | any | `{enrollment_allowed, status, reason, run_id?}`. Fail-closed |

## Reported counts

| Count | Meaning |
|---|---|
| `accounts`, `real_accounts`, `synthetic_accounts` | Sample size and provenance |
| `accounts_without_claims` | Sampled accounts with no displayed factual claims (zero-fact accounts are still counted) |
| `excluded_accounts` | `{id: reason}`, where reason is `duplicate_campus_record`, `no_sources` or `synthetic_not_eligible` |
| `items`, `pending` | Total claims and claims not yet reviewed |
| `numerator` / `denominator` | Supported claims out of all claims |
| `still_displayed_failures` | Failed claims still displayed as fact |
