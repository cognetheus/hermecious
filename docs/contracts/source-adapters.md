# Source adapter contract (P2.1, extended in P2.2)

Rights-aware, bounded discovery over registered source adapters. Decision records: [ADR-012](../adr/ADR-012-source-adapter-fetch-by-key.md) (fetch by key) and [ADR-013](../adr/ADR-013-osm-overpass-source-and-egress.md) (first live source and egress). Code: `apps/api/app/discovery/` and `apps/api/app/egress/`. Operating procedure: [discovery-sources runbook](../runbooks/discovery-sources.md).

> A fixture proves nothing about any real school. Fixture reports are labelled `SYNTHETIC FIXTURE DATA: …`. Live-source reports are labelled `UNVERIFIED LISTINGS: third-party records, not verified schools, prospects or contacts`, and every run carries `completeness_note` ("never an exhaustive list").

## Providers (P2.2)

| Provider | Kind | Enabled | Storage | Retention | Notes |
|---|---|---|---|---|---|
| `fixture_lahore_schools` | fixture | development and test | up to full | 30 days | Synthetic, offline |
| `osm_overpass_schools` | api | **only when the owner sets every `HERMECIOUS_OSM_*` activation setting** | metadata only | 30 days | ODbL attribution; one fixed bbox query; `{type}/{id}` keys; `fetch` served from the search capture |
| `operator_seed_csv` | seed_list | all environments, owner only | metadata only | none set | Per-import permission declaration; checksum-idempotent; not independently verified |

**Live descriptors also need:**
- `reviewed_by`, with a review younger than `review_valid_days` (365); otherwise `provider_unreviewed` or `rights_review_expired`;
- `licence_reference`, `attribution` and `max_response_bytes`;
- `retry_backoff_seconds` and `fetch_from_search_capture`.

`website` kinds stay refused (`live_sources_not_enabled`).

## Interface (`contracts.py`, `CONTRACT_VERSION = source-adapter-v1`)

```python
class SourceAdapter(Protocol):              # synchronous, like the API and worker runtime
    descriptor: SourceDescriptor
    def search(self, *, query: SourceQuery, limit: int, cursor: str | None = None) -> Mapping[str, Any]: ...
    def fetch(self, *, source_key: str) -> Mapping[str, Any]: ...   # provider-scoped key, never a URL
```

Adapters return raw mappings, and the framework validates them into:

| DTO | Key rules |
|---|---|
| `SourceQuery` | city and vertical required; `area` optional; ≤5 keywords of ≤40 characters (`[\w .'-]`). Raw executable queries are impossible |
| `SourceCandidate` | provider, provider-scoped `external_key` (`[A-Za-z0-9._:/-]`, required to be accepted), name, city, vertical, locality, optional URL, **timezone-aware** `observed_at`, ≤5 `claim_hints` (**unverified, never facts, never instructions**). P2.2 optional fields: `name_local`, finite `latitude`/`longitude`, `location_precision` (`point` or `area_center`, a representative point and not an address), `upstream_timestamp`, `attribution`. Extra fields rejected. Text is NFKC-cleaned; control and bidi characters are rejected (`unsafe_text`) |
| `SourceObservation` | provider, key, observed/expires (aware), optional URL, `permitted_storage_class`, `rights_policy_version`, `data` |
| `SourcePage` | candidates, opaque `next_cursor` (≤512 characters), `reported_cost_units` |

## Descriptor policy (`registry.py`)

| Field | Purpose |
|---|---|
| `provider`, `adapter_version`, `source_kind` | identity; P2.1 enables only `fixture` |
| `terms_reference`, `rights_policy_version`, `last_reviewed_at` | **all required**; missing means `provider_unreviewed` |
| `enabled`, `environments` | default deny; the fixture is enabled in development and test only |
| `permitted_operations` | `search`, `fetch`, `store_metadata`, `store_derived`, `store_full`; each is checked |
| `max_storage_class`, `retention_ttl` | storage ceiling; provenance `expires_at` is clamped to `observed_at + retention_ttl` |
| `request_quota`, `result_limit`, `page_size` | provider ceilings, applied alongside the run budget |
| `allowed_hostnames`, `allow_http` | URL provenance must use these hosts (the P1.2 URL screen also applies) |
| `requires_credentials` | refused in P2.1 |
| `supported_cities`, `supported_verticals` | other queries are refused (`unsupported_query`) rather than answered with "nearby" data |

The refusal codes are `unknown_provider`, `provider_disabled`, `provider_unreviewed`, `live_sources_not_enabled`, `provider_not_enabled_in_environment`, `credentials_not_supported`, `operation_not_licensed:<op>` and `unsupported_query`. **All are raised before the adapter is invoked.**

## Run (`runner.run_discovery`)

**Budget** (`DiscoveryBudget`): `max_candidates` 30, `max_search_pages` 5, `max_fetches` 20, `max_seconds` 60, `max_cost_units` 50, `max_retries` 2. These are **ceilings**: a run may lower them, and raising them raises `ValueError`. Budgets are fixed before the first call, and retries consume them.

| Situation | Handling (reason code) |
|---|---|
| Page larger than requested | truncated deterministically (`page_oversized`) |
| Repeated cursor | stop (`cursor_cycle`) |
| Repeated key in one run | rejected (`duplicate_key`) |
| Schema problem, naive time, wrong type | rejected (`invalid_record`) |
| No key | `missing_key` |
| City or vertical not as queried | `query_mismatch` |
| URL fails the P1.2 screen (private, metadata, credentials, fragment, scheme) | `unsafe_url` |
| URL host not in the descriptor | `unapproved_host` |
| 429 or timeout on search | retried within budget (`search_rate_limited`/`search_timeout`), then stop (`rate_limited`/`timeout`) |
| Fetch timeout | that record is skipped (`fetch_timeout`), and the run continues |
| Observation inconsistent | `observation_mismatch`, `rights_version_mismatch`, `invalid_observation` |
| Storage class above the descriptor ceiling or unlicensed | `rights_denied` (nothing stored) |
| Observation already expired | `expired_observation` |
| No source URL | previewed, but **not persisted** (`not_persisted_missing_url`); a URL is never invented |

**Stop reasons:** `completed`, `candidate_cap`, `page_cap`, `fetch_cap`, `time_cap`, `cost_cap`, `rate_limited`, `timeout`, `cursor_cycle`, `provider_quota`, plus, from P2.2, `unavailable`, `response_too_large`, `upstream_error` and `policy_revoked`.

**P2.2 run rules:**

**Policy and retries**
- Policy is re-checked before **every** adapter call; a provider disabled mid-run stops the run, and nothing more is stored.
- Transient errors wait `max(Retry-After, retry_backoff_seconds × 2^retry)`, and only if the wait fits the time budget (otherwise `retry_wait_exceeds_time_budget`).
- Oversized responses and permanent upstream errors stop without retry.

**Report fields**
- `truncated`: the provider had more matches than the run took.
- `partial`: the run was stopped early by a budget, error or policy change.

**Refusals and staging**
- A refusal writes a `discovery.source_denied` log line and a `discovery.run_refused` audit.
- Persisted candidates are **staged** in `discovery_candidates` (below).

**Retained content by rights:**

| Storage class | Preview keeps | Persisted (`source_records`) |
|---|---|---|
| `metadata_only` | identity, locality, URL | provenance row (URL, provider-scoped key, observed and expiry times, rights version) |
| `derived_only` | above plus `claim_hints` (unverified) | same provenance row |
| `full_allowed` | above plus a bounded `excerpt` (≤1000 characters) | same provenance row; **no payload or content columns** |

Raw provider text (for example `raw_page_text`) and free-form `notes` are never copied into reports, logs, the DB or audits.

**Persistence** goes through the P1.2 `add_source_record` with provider `fixture_lahore_schools`, key `fixture_lahore_schools:<key>`, inside the actor's organization. A replay finds existing rows (`already_recorded_count`) and never duplicates them. Another organization running the same fixture gets its own rows. **No accounts, facts, contacts or merges are created**; identity resolution is P2.3, and review is P2.4.

**Report** (`DiscoveryFixtureReport`) contains `run_id`, `correlation_id`, the synthetic label, contract and adapter versions, the rights policy version, the query, `stop_reason`, examined, accepted, rejected, persisted and already-recorded counts, budget limits and consumption, rejection reason counts, and rights-filtered `unverified` previews. An audit row `discovery.fixture_run` (`target_type = discovery_run`) stores the counts.

## Staging (P2.2, migration 0007)

**`discovery_candidates`**
- **Identity:** one row per `(organization_id, provider, external_key)`.
- **Status:** `unreviewed` / `admitted` / `rejected`; only `unreviewed` is written in P2.2.
- **Fields:** the permitted listing fields, `rights_policy_version`, `attribution`, `observed_at`, `upstream_timestamp`, `expires_at`, `revision` and `payload_digest`.
- **Provenance:** an organization-scoped FK to `source_records` and/or `source_imports`; at least one is required.
- **Replays and revisions:**
  - An identical replay is a no-op.
  - A content change bumps `revision` and writes a `discovery.candidate_revised` audit.
  - Concurrent replays are safe.

**`source_imports`**
- One row per CSV file per organization (`file_sha256` unique).
- Holds the label, declaration, counts and importer.

## HTTP (P2.2)

| Route | Access | Behaviour |
|---|---|---|
| `POST /api/v1/discovery/seed-imports` | owner, CSRF | `{source_label, permission_declaration (20–1000), csv_text}`. 201, or 200 with `replayed: true` for identical bytes. 400 `VALIDATION_ERROR` for header, size, rows or encoding problems. Rejected rows are reported by row number only |
| `GET /api/v1/discovery/candidates` | any role | Organization-scoped; `limit` ≤50; `provider` and `status` filters; keyset `cursor`. Each item has `verification: unverified`, `origin`, `attribution`, `expires_at`, `expired` and `source_url` (the provenance URL, if any) |

There is **no HTTP route that starts a live run or accepts a URL**.

## Running it

```sh
# Synthetic fixture (development/test only)
docker compose run --rm --no-deps api python -m app.discovery.cli --organization <org-uuid> [--keyword K] [--dry-run]
# Live OSM (owner opt-in; see the runbook for the activation settings)
docker compose run --rm --no-deps -e HERMECIOUS_OSM_ENABLED=true -e … api \
  python -m app.discovery.cli --organization <org-uuid> --provider osm_overpass_schools --confirm-live
```

The fixture refuses outside `development`/`test`. The live provider refuses without `--confirm-live` or with an incomplete review. P2.4 owns run management and the review UI.

## Fixture dataset

`apps/api/app/discovery/fixtures/lahore_schools_v1.json`:
- **License:** `kind: synthetic`, policy `fixture-policy:hermecious-synthetic-v1`, fictional records only.
- **Records** (9):
  - two different schools sharing a name in different localities;
  - one record with a missing URL, one stale, and one each of metadata, derived and full rights;
  - a wrong city;
  - a metadata-IP URL and an off-allowlist host;
  - a prompt-injection string, which stays inert data.
- **Hosts** use `school.fixture.example`, which is non-fetchable and never contacted.

## Egress (P2.2)

`app/egress/https_client.py` (`PinnedHttpsClient`) is the **only** network client.

**Targets and DNS**
- It reaches only an exact `(host, path)` allowlist, over HTTPS on port 443.
- **Every** DNS answer must be globally routable; the connection is pinned to the vetted IP, and TLS verifies the hostname.

**Requests and responses**
- No redirects, proxies, cookies or credentials.
- Bounded time and bytes.
- 429/503 responses become typed transient errors carrying a bounded Retry-After.

**Who may use it**
- Within `app/discovery`, only `osm.py` and `cli.py` may import it (static test).
- Every discovery test runs under a socket egress guard.

## Adding another provider

1. Write an ADR with the rights review.
2. Add a descriptor with `reviewed_by`, licence, attribution and limits.
3. Add a P1.2 `PROVIDERS` entry.
4. Add an egress allowlist entry, if it is network-backed.
5. Add hermetic tests.

Keep every rule above.

## Discovery runs and admission (P2.4, [ADR-015](../adr/ADR-015-discovery-runs-and-admission.md))

| Route | Roles | Behaviour |
|---|---|---|
| `GET /api/v1/discovery/sources` | any | Only providers that pass policy now, with the server-bound area, rights, attribution and budget ceilings |
| `POST /api/v1/discovery/runs` | owner, operator (CSRF) | `{provider, budget:{max_candidates≤30, max_search_pages≤5, max_fetches≤20, max_seconds≤45}, idempotency_key}`. 202 plus the run. Run, `discovery.run` v1 job and outbox event are committed atomically. A replay returns `replayed: true`; a changed request gives 409; an unavailable source gives 400 with nothing written |
| `GET /api/v1/discovery/runs[?cursor]` and `GET /api/v1/discovery/runs/{id}` | any | Status, counts, `truncated`, partial or error reason, usage, review tally, job status and `exhaustive: false` |
| `GET /api/v1/discovery/runs/{id}/candidates` | any | ≤30 listings with provenance, rights, expiry, attribution, `unknowns`, P2.3 `matches` and review state |
| `POST /api/v1/discovery/runs/{id}/cancel` | owner, operator (CSRF) | Idempotent and cooperative |
| `POST /api/v1/discovery/runs/{id}/candidates/{candidate_id}/decision` | owner, operator (CSRF) | `{action: accept_new\|attach_existing\|reject\|defer, expected_version, idempotency_key, reason, existing_account_id?}`. See ADR-015 §6 |

**Run statuses:** `pending → running → completed | partial | failed | cancelled`, plus `pending → cancelled`. Terminal states are never rewritten.
