# Account management and evidence contract (P1.4)

Operators create Lahore school accounts, attach source-backed facts or visibly unverified hypotheses, and correct facts with traceable history. Builds on [core-domain.md](core-domain.md) (P1.2 schema, rights policy, claim registry). Code: `apps/api/app/accounts/{management,routes}.py`. UI: `/accounts`, `/accounts/new`, `/accounts/{id}`. Migration `0005`.

## API (`/api/v1/accounts`, session + CSRF on every write)

| Method / path | Roles | Behaviour | Errors |
|---|---|---|---|
| `POST /` `{canonical_name, locality?, city="Lahore", vertical="schools"}` | owner, operator | 201 with the account, `ETag: "1"`. **No name uniqueness**: same-name schools are separate accounts | 422 bad body or city other than Lahore; 400 control/bidi characters in the name; 403 observer |
| `GET /?limit&cursor&city&vertical_id&status&q` | all | Keyset page ordered `updated_at DESC, id DESC`. `limit` 1–100 (default 25). `q` is a **normalized name prefix**, using the `text_pattern_ops` index. Returns `{accounts, next_cursor}` | 422 for bad limit, status, city, uuid or cursor length; 400 for an invalid cursor or one whose filters changed |
| `GET /{id}` | all | Account, aliases, facts (projection below) and the last 100 audit entries. `ETag: "<version>"` | 404 for missing or other-organization ids |
| `PATCH /{id}` `{expected_version, canonical_name?, locality?\|null, status?}` or `If-Match: "<version>"` | owner, operator | Atomic compare-and-swap: `UPDATE … WHERE id AND organization_id AND version = expected`, and `version + 1`. Audited with from/to values | 409 stale version (state preserved); 422 invalid transition or `excluded`; 400 missing, disagreeing or invalid version |
| `POST /{id}/archive` `{expected_version}` | **owner** | `status = excluded`. Nothing is deleted | 403 non-owner; 409 stale or already archived |
| `POST /{id}/facts` | owner, operator | Adds a `source_supported` fact or a `hypothesis`. `source` is either `{source_id}` (an existing in-organization source) or `{new: {provider, source_url, storage_class, observed_at, external_key?, expires_at?}}`. A new source is registered **in the same transaction and never fetched** | 403 when source rights forbid it; 400 for a policy, URL, claim-value, expired-source or timestamp problem; 422 for a malformed body; 404 for another organization's account or source |
| `POST /{id}/facts/{fact_id}/corrections` `{reason, …fact fields}` | owner, operator | Atomic correction: locks the prior fact, writes a **new** fact with `supersedes_fact_id`, `correction_reason` and `recorded_by`, then audits | 422 for a missing or short reason, or a different `claim_type`; 409 if the fact was already corrected (correct the latest version); 404 cross-organization |

There is **no delete endpoint**. Response errors use the P0.4 envelope `{error: {code, message, request_id, retryable}}`. Batch 03 calls the field `trace_id`; the accepted P0.4 contract name `request_id` is kept.

**Lifecycle transitions** (PATCH): `discovered → researching`; `researching → assessed | discovered`; `assessed → shortlisted | investigate | nurture | researching`; `shortlisted`, `investigate` and `nurture` each move to `researching` or between one another. `excluded` is reachable only through archive, and P1.4 has no way to un-archive.

**Cursor:** an opaque base64url token holding `{updated_at, id, filter digest}`, where the digest is the SHA-256 of the organization id plus the exact filters. It is **validated, not signed**: it can only address positions inside the caller's own organization-scoped, filtered result set. Every query is filtered by `organization_id` regardless of the cursor, and a cursor reused with other filters or from another organization is rejected.

## Fact projection (detail)

Each fact carries:
- `verification_status`, `confidence_label`, `observed_at`, `expires_at`;
- `is_stale` (the fact or its source has expired; `source_supported` and stale can both be true);
- `is_current` (no successor);
- `source` (provider, URL, storage class, rights version, observed and expires times; never payload references);
- `evidence_excerpt` (plain text, ≤1000 characters, `full_allowed` sources only);
- `supersedes_fact_id`, `superseded_by_fact_id`, `correction_reason`, `recorded_by`.

A hypothesis is never labelled verified. A URL alone does not support any statement. An unknown value stays `unknown`, and absence of evidence is never shown as absence.

## Integrity guarantees

- **Facts are append-only.** The trigger `account_facts_append_only` blocks UPDATE and DELETE, so a correction is always a new row. The partial unique index `uq_account_facts_org_supersedes` allows **one successor per fact**, so two racing corrections cannot both become current; the loser gets 409.
- **`action_audits` is append-only and organization-scoped.** Entries are written in the same transaction as the change: `account.created`, `account.updated` (with from/to values), `account.archived`, `account.fact_added` and `account.fact_corrected`, each with actor, time and request ID.
- **Every lookup is scoped by the session's organization.** Composite foreign keys reject cross-organization links in the database.
- **Logs** carry event names and IDs (`account_id`, `fact_id`), never fact values or excerpts.

## UI

- **`/accounts`:** status filter, name-prefix search, a keyset "Next page" link, and a "New account" link (owners and operators only).
- **`/accounts/{id}`:**
  - **Identity:** an editor with optimistic version, plus archive for owners.
  - **Evidence (current, source-supported):** cards showing source, observed time in **Asia/Karachi**, rights and staleness.
  - **Hypotheses and unknowns (not verified)**, kept separate from verified evidence.
  - **Correction history**, a form to add evidence (with optional source registration), a correction form on current facts that requires a reason, and the **audit trail**.
- Observers see read-only pages with no controls.
- All text is rendered as escaped data, and long strings wrap on mobile.

## Tests

- **API:** `apps/api/tests/integration/test_account_management.py`.
- **Browser:** `apps/web/e2e/accounts.spec.ts`, run by `scripts/test-e2e.sh` on a disposable full stack (desktop and mobile Chromium, plus an api/web restart check). Both run in `scripts/check.sh`.

## Rollback

On a disposable database, `alembic downgrade 0004` drops the correction columns, `action_audits` and the triggers. Where data exists, corrections and audits are history: back up and prefer a forward repair. Never `docker compose down -v`.
