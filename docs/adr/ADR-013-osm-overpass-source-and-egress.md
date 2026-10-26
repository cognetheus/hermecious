# ADR-013: First live source is OpenStreetMap via Overpass, behind one pinned egress client; CSV seeds are the fallback

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" after reviewing the audit; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-24
- **Source:** Batch 04 §P2.2 and §5.1; `OPUS_P2.2_PROMPT.md`; ADR-012

## Context

P2.1 ships an offline source framework, and ADR-012 left P2.2 to add one reviewed real provider with SSRF-safe egress. Batch 04 recommends:
- OpenStreetMap school POIs through one small Overpass query;
- an operator CSV as the fallback.

It also forbids:
- Google Maps/Places scraping;
- public Nominatim grids;
- crawling;
- treating a map listing as a prospect.

## Decision

### 1. Provider `osm_overpass_schools` (`source_kind = api`, adapter 1.0.0, rights policy `osm-odbl-2026-10`)

**Disabled by default.** The descriptor is built from settings and enabled only when **all** of these are set:

| Setting | Meaning |
|---|---|
| `HERMECIOUS_OSM_ENABLED=true` | Explicit opt-in |
| `HERMECIOUS_OSM_REVIEWED_BY` | Who reviewed the current OSM/ODbL and Overpass-instance terms |
| `HERMECIOUS_OSM_REVIEWED_AT` | Timezone-aware review time. Older than 365 days fails with `rights_review_expired` |
| `HERMECIOUS_OSM_BBOX` | `south,west,north,east`, chosen by the operator |
| `HERMECIOUS_OSM_BBOX_CITATION` | Where that box came from |
| `HERMECIOUS_OSM_ENDPOINT` | Must be in the code allowlist, which holds only `https://overpass-api.de/api/interpreter` |

- **Invalid activation stops startup.** A partially configured activation fails settings validation and names the setting.
- **Bounding-box limits:** at most 0.6° per side, and inside a Pakistan sanity envelope. The envelope rejects typos; **it is not a city boundary**.
- **No geocoding:** no place name is ever geocoded.

### 2. Query and parsing

The only query is a fixed template with validated numbers:

`[out:json][timeout:20];nwr["amenity"="school"](S,W,N,E);out center 31;`

- **Size:** one more element than the 30-candidate ceiling is requested, so truncation is detected and reported as `truncated`; extra pages are never swept.
- **Paging:** there is no cursor. One query per run, `request_quota = 3`, including retries.
- **Elements:** only `node`/`way`/`relation` with a positive integer id are kept.
  - **Key:** `{type}/{id}`.
  - **Provenance URL:** `https://www.openstreetmap.org/{type}/{id}`, built from the validated key and never from response data.
- **Tags:** only `name`, `name:ur` and `addr:suburb` are kept.
  - Contributor metadata is never requested or kept.
  - Phone, email, website and operator tags are dropped.
- **Location:**
  - Coordinates must be finite and inside the configured box.
  - Without usable geometry the element is rejected.
  - A way/relation `center` is labelled `area_center` (a representative point), never an address.
- **Missing name:** rejected; a name is never synthesized.
- **Timestamps:** capture time is `observed_at`; the `osm3s.timestamp_osm_base` is `upstream_timestamp`.
- **`fetch`:** serves the observation captured by this run's search, with no second request (`fetch_from_search_capture`), so it does not consume the remote fetch budget.

### 3. Rights

- **Storage:** `metadata_only` (P1.2 `PROVIDERS` entry; external key required; no payload).
- **Retention:** 30 days.
- **Attribution:** "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)". It is carried on every candidate and report.
- **Licence:** ODbL obligations (attribution, and share-alike for a publicly distributed derived database) must be re-assessed before any **external** export. P2.2 has no export.

### 4. One egress client: `app/egress/https_client.py` (`PinnedHttpsClient`)

**Target rules:**
- HTTPS only;
- an exact `(host, path)` allowlist on port 443;
- no query string, userinfo or fragment.

**DNS and connection:**
- DNS is resolved once, and **every** answer must be globally routable, otherwise the call is `non_public_address`. This excludes loopback, private, link-local and metadata, CGNAT and IPv4-mapped addresses.
- The TCP connection is pinned to a vetted address, while TLS verifies the hostname through SNI. This defeats DNS rebinding.

**Request rules:**
- No redirects (any 3xx gives `redirect_refused`);
- no proxies (`http.client` with a pre-connected socket ignores `*_PROXY`);
- no cookies or credentials;
- a 25 s timeout and a 1 MB response cap.

**Rate limits:**
- 429 and 503 become typed transient errors. Retry-After is honoured only as numeric seconds ≤300.
- The runner waits `max(Retry-After, 5 s × 2^retry)`, and only if the wait fits the 60 s run budget. Otherwise it stops (`retry_wait_exceeds_time_budget`).

**Where network code may live:** only this module may contain network code. In `app/discovery`, only `osm.py` and `cli.py` reference it. Static tests enforce this, and every discovery test runs under a socket egress guard.

### 5. Runner changes (backward compatible with SOURCE-01…10)

- **Policy re-check:** policy is re-checked before **every** adapter call. A provider disabled mid-run stops with `policy_revoked`, and nothing more is stored.
- **New stop reasons:** `unavailable`, `response_too_large`, `upstream_error`, `policy_revoked`.
- **Refusals:** each one leaves a `discovery.source_denied` log line and a `discovery.run_refused` audit.
- **Report fields:** `truncated`, `partial`, `completeness_note` and `attribution` are added, along with staged counts. Live runs are labelled "UNVERIFIED LISTINGS".
- **`SourceKey`:** now also allows `/` (keys such as `node/123`). It is still never a URL.

### 6. Staging (`discovery_candidates`, migration 0007)

- **Identity:** one row per `(organization, provider, external_key)`, status `unreviewed`.
- **Content:** only the permitted listing fields, plus provenance (a `source_records` row or a `source_imports` row; at least one is required).
- **Replays and revisions:**
  - An identical replay changes nothing: no timestamp refresh and no audit.
  - Changed permitted fields bump `revision` and write a `discovery.candidate_revised` audit with both digests.
- **Concurrency:** `ON CONFLICT DO NOTHING` plus a row lock make it safe.
- **Nothing else is created:** no accounts, facts or contacts.

### 7. CSV fallback, `operator_seed_csv` (rights policy `operator-declared-v1`, `metadata_only`)

- **Access:** owner only (ADMINISTER); `POST /api/v1/discovery/seed-imports` requires CSRF.
- **Required inputs:** a source label and a permission declaration (20–1000 characters).
- **File:** UTF-8 with an optional BOM; ≤256 KB; ≤500 rows.
- **Header:** exactly `school_name,city,locality,source_reference[,external_key]`. The city must be Lahore.
- **Row rejections:**
  - formula-like cells (`= + - @ | tab cr`) are refused, so nothing becomes a spreadsheet instruction later;
  - control and bidi characters are refused;
  - each rejected row is reported by row number only, never by content.
- **Idempotency:** per `(organization, provider, file_sha256)`. The same bytes replay as `replayed: true`.
- **No network use:** nothing is fetched, and a URL-like reference stays text.
- **Labelling:** rows are labelled "OPERATOR-SEEDED … not independently verified".

### 8. Read surface

`GET /api/v1/discovery/candidates` is organization-scoped, at most 50 items per page, with a keyset cursor. Every item reports:
- `verification: unverified`;
- origin, attribution, rights version, `expires_at` and `expired`;
- `location_precision`.

**At the time of this ADR there was no HTTP endpoint that started a live run.** P2.4 (ADR-015) later added `POST /api/v1/discovery/runs`, which uses the same source policy checks.

## Alternatives rejected

- **Public Nominatim:** its usage policy forbids systematic POI queries.
- **Google Places:** content caching is restricted.
- **Website crawling:** not reviewed.
- **Offline Geofabrik extract:** better for repeated bulk use, but out of P2.2 scope; it is the recommended next source if collection becomes regular.
- **Following redirects to allowlisted hosts:** unnecessary for Overpass and widens the attack surface.

## Consequences

- **LIVE-10 needs the owner.** It requires an explicit opt-in (the settings above), outbound network access and a re-read of the current Overpass instance terms. Until then, P2.2 is "implementation complete, live integration unverified".
- **The Overpass syntax has not been run against a live endpoint.** It is asserted against the documented template only. A real query is part of LIVE-10.

## Rollback

- **Disable OSM:** unset `HERMECIOUS_OSM_ENABLED`. Runs fail closed before any request, and a run in flight stops at its next policy check.
- **Disable CSV:** set `enabled=False` in the seed descriptor.
- **Revert code:** revert the P2.2 commits; the schema repairs forward.
- **Data:** keep `source_records` and `discovery_candidates` rows (organization-scoped, attributed). Downgrade 0007 only on a disposable database.
