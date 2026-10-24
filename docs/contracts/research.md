# Research contract (P3.1)

Decision record: [ADR-016](../adr/ADR-016-source-backed-research.md). Code: `apps/api/app/research/`. Fixture documents: `apps/api/app/research/fixtures/school_documents_v1.json`, which are synthetic.

> A research claim repeats what a source says. It is **proposed** until a reviewer accepts it, and only then becomes a P1.4 source-supported fact. A statement that is absent from a source proves nothing.

## HTTP

| Route | Roles | Behaviour |
|---|---|---|
| `GET /api/v1/accounts/{id}/research-sources` | any | Sources associated with the account (`admitted_listing`, `alias_provenance` or `fact_source`), with `eligible` and `ineligible_reason` |
| `POST /api/v1/accounts/{id}/research-runs` | owner, operator (CSRF) | `{source_record_ids[1..5], idempotency_key, budget?}`. 202, with run, job and outbox committed atomically. A replay returns `replayed: true`; a different request with the same key gives 409. An unassociated or ineligible source gives 400 and nothing is written |
| `GET /api/v1/accounts/{id}/research-runs` | any | The newest runs (≤20) |
| `GET /api/v1/research-runs/{id}` | any | Run, observations (status, reason, language, character count, `retrieved_at`) and claims |
| `POST /api/v1/research-runs/{id}/cancel` | owner, operator (CSRF) | Idempotent and cooperative |
| `POST /api/v1/research-claims/{id}/review` | owner, operator (CSRF) | `{action: accept\|reject, expected_version, reason, idempotency_key, confidence_label?}`. Returns `fact_id` on accept. 409 for a stale version, an already-reviewed claim, rights lapsed, or a reused key |

## Claim view

Each claim carries:
- `claim_type` and `value`, from the P1.2 registry;
- `rule_id` and `extractor_version`;
- `language`;
- `locator {start, end}` and `span_sha256`;
- `excerpt`, which is `null` for `derived_only` sources, or withheld with `excerpt_withheld_reason` when rights have lapsed at render time;
- `excerpt_policy` (`stored` or `locator_only`);
- `source`: provider, URL, storage class, rights version, captured time, expiry, and `current_rights`;
- review fields.

## Run statuses

`pending → running → completed | partial | failed | cancelled`.

| Reason | Meaning |
|---|---|
| `partial_reason: job_time_budget` | The run's time budget ran out before every source was processed |
| `partial_reason` holding a fetch error (`rate_limited`, `unavailable`) | Some sources failed while others were processed |
| `error_code` holding a fetch error | Every source failed |
| `skipped` (per source) | A rights refusal; the run itself can still be `completed` |

## Limits

| Limit | Value |
|---|---|
| Sources per run | 5 |
| Body size | 2 MiB per source |
| Normalized text | 60 000 characters per run |
| Time | 30 s per source, 60 s per run |
| Claims | 25 per run |
| Excerpt length | 1 000 characters |
