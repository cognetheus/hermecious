# Core domain contract: accounts, sources, aliases, facts (P1.2)

Migration `0003` (on top of P1.1's `0002` identity tables). Models: `apps/api/app/accounts/models.py`. Services: `apps/api/app/accounts/service.py`. This is the data substrate for Lahore account research. It has **no HTTP API yet** (P1.4) and **no fetchers** (P2).

## Tables

| Table | Scope | Key rules |
|---|---|---|
| `verticals` | Global reference data | `slug` unique and `^[a-z][a-z0-9_]{1,79}$`; `status` active/inactive. `schools` is seeded by the migration (fixed id `5c4f1d2e-0000-4000-8000-000000000001`) |
| `areas` | Organization | One row per (org, `lower(city)`, `lower(district)` or whole city), as a unique expression index. This avoids the NULL-distinct trap of a plain unique constraint |
| `accounts` | Organization | `status` ∈ discovered, researching, assessed, shortlisted, investigate, nurture, excluded. `version` is an optimistic-concurrency counter: a stale writer fails. **No uniqueness on name**: same-name schools and campuses are separate accounts until P2.3 resolves identity |
| `source_records` | Organization | `permitted_storage_class` ∈ metadata_only, derived_only, full_allowed. A payload reference is allowed only with `full_allowed` (CHECK). `(org, provider, external_key)` is unique when the key is present. URL ≤ 2048 characters with no whitespace (CHECK) |
| `account_aliases` | Organization | `(org, account, normalized_name)` unique |
| `account_facts` | Organization | `source_supported` requires a source and a non-`unknown` confidence (CHECKs). `claim_type` format CHECK. Excerpt ≤ 1000 characters. `expires_at > observed_at` |

**Cross-organization safety:** `accounts`, `source_records` and `areas` expose `UNIQUE (organization_id, id)`. Aliases and facts reference them through composite foreign keys (`fk_account_facts_org_account`, `fk_account_facts_org_source`, `fk_account_aliases_org_account`, `fk_account_aliases_org_source`). A row pointing at another organization's account or source is rejected by Postgres, not just by the ORM. Services additionally filter every lookup by `actor.organization_id`, and a row in another organization behaves exactly like a missing row (`NotFound`). RLS is not used yet; revisit it before any multi-tenant SaaS move.

All timestamps are `timestamptz`. Services require timezone-aware inputs and store UTC; naive datetimes are rejected.

## Service contract

| Function | Capability | Notes |
|---|---|---|
| `create_account(actor, vertical_id, name, city, locality?)` | MUTATE (owner, operator) | Name NFKC-normalized and trimmed; control and bidi-override characters rejected. `normalized_name` = casefold, punctuation removed, single-spaced. Status `discovered` |
| `add_source_record(actor, provider, source_url, observed_at, storage_class, rights_policy_version, external_key?, payload_reference?, expires_at?)` | MUTATE | Provider allowlist and storage-class policy, URL screening, `observed_at` not in the future (5 min skew), duplicate key gives `Conflict` |
| `add_alias(actor, account_id, name, source_record_id?)` | MUTATE | Duplicate normalized alias gives `Conflict` |
| `add_account_fact(actor, account_id, claim_type, typed_value, confidence_label, verification_status, observed_at, source_record_id?, expires_at?, evidence_excerpt?)` | MUTATE | See the fact rules below |
| `get_account_with_evidence(actor, account_id)` | READ (all roles) | Account, aliases, and facts with source provenance and an `is_stale` flag |

Each mutation is a single transaction. Any policy failure raises before writing, and integrity races roll back and raise `Conflict`. Errors use the P0.4 typed errors: `InvalidRequest` (400) with a fixed message, `NotFound` (404), `Conflict` (409), `Forbidden` (403).

## Source rights policy (`app/accounts/policy.py`, `RIGHTS_POLICY_VERSION = rights-2026-10-23`)

| Provider | Allowed storage | HTTP | Payload | Notes |
|---|---|---|---|---|
| `manual_entry` | all | yes | yes | Operator-entered from their own knowledge or documents |
| `owner_seed_list` | all | yes | yes | Owner-supplied seed lists (Pilot A) |
| `first_party_website` | all | yes | no | A school's own site, where access is allowed |
| `google_places` | `metadata_only` | no | no | **Place ID only** (`external_key` required); no content caching (blueprint §7) |
| `fixture` | all | no | yes | Tests |

Unknown providers are refused. Public availability never implies permission to store, enrich or contact. Storing a source record never implies permission to contact anyone (contacts and consent are separate, later models).

**Excerpts:** a verbatim `evidence_excerpt` needs a `full_allowed` source and must be ≤ 1000 characters and ≤ 4000 UTF-8 bytes, with no control characters. `metadata_only` and `derived_only` sources can support facts but cannot carry excerpts.

**URL screening (ingestion baseline only).** URLs must:
- be `https`, or `http` where the provider allows it;
- contain no credentials and no fragment;
- carry no secret-bearing query parameters (`token`, `key`, `sig`, `session`, `code`, …);
- not point at a private, loopback, link-local or metadata IP, `localhost`, `*.internal`/`.local`/`.lan`, or a single-label host;
- contain no control or bidi characters, and be ≤ 2048 characters.

Outbound fetch and SSRF protection are **not** provided here (P2.1, P11.1).

## Fact rules (`app/accounts/claims.py`)

Allowlisted claim types, each with a strict, extra-forbidding Pydantic model:

| `claim_type` | Value | Unknown form |
|---|---|---|
| `campus_count` | `{"count": 1..500}` | none: omit the fact |
| `school_levels` | `{"levels": [preschool, primary, middle, secondary, higher_secondary, o_a_levels]}` | none |
| `ownership_type` | `{"type": independent \| franchise \| chain_campus \| trust \| unknown}` | `unknown` |
| `decision_authority` | `{"holder": owner \| principal \| board \| head_office \| unknown}` | `unknown` |
| `public_workflow_signal` | `{"area": admissions \| fees \| student_records \| reporting \| communication, "signal": ≤300 chars}` | none |
| `software_in_use` | `{"status": "observed", "product": ≤100}` or `{"status": "unknown"}` | `unknown` |
| `website_presence` | `{"status": present \| unknown}` | `unknown` |
| `public_contact_channel` | `{"channel": website_form \| public_phone_listed \| public_email_listed \| social_page}` | none |

- **No absence claims.** There is no "no website", "no software" or "none" value: not seeing something is not evidence it is absent.
- **Unknown stays unknown.** An unknown value must be `hypothesis` with `unknown` confidence; it can never be source-supported.
- **`source_supported`** requires an in-organization source that has not expired and a confidence other than `unknown`.
- **`hypothesis`** may have no source but cannot be `strong`. New facts may only be created as `source_supported` or `hypothesis`; `disputed` and `rejected` come from later review flows.
- **`confidence_label`** describes evidence quality only. There is no likelihood-to-buy claim.
- **No personal data or contact values** as facts. For example, `principal_mobile` is not a claim type.
- **Staleness:** `is_stale` is true when the fact's own `expires_at` or its source's `expires_at` has passed. Stale facts stay visible but must never be presented as current. Re-verification UX arrives in P1.4/P3.

## Downstream contract

| Consumer | Uses |
|---|---|
| P1.4 Accounts CRUD and evidence UI | The services above behind authenticated `/api/v1` routes; `AccountEvidence` for display |
| P2 discovery | `add_source_record` with real adapters, which must register in `PROVIDERS` with reviewed rights |
| P2.3 dedupe | `normalized_name` and aliases as *suggestions* only; never merge on name alone |
| P3 research and qualification | Facts with provenance; `source_supported` and `hypothesis` kept separate |

## Migration and rollback

- Disposable database: `alembic downgrade 0002` drops only P1.2 tables, and P1.1 users and sessions are preserved (tested). Re-upgrade restores an empty P1.2 schema with the `schools` vertical.
- Data-bearing environment: back up first and prefer a reviewed forward repair. **Never** drop fact or source tables to roll back code, and never `docker compose down -v`.
