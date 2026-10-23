# HERMECIOUS — Batch 04: P2.2–P2.4

**Status:** Implementation specification, not evidence of implemented functionality.  
**Product:** Hermecious — self-hosted, single-organization-first sales research operating system.  
**Target:** Lahore, Pakistan; `school` vertical; 30-candidate initial-run ceiling.  
**Executor:** Claude Opus 5.5 High, **one independently verified subphase per run**.  
**Authority:** `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, accepted repo ADRs, P0–P2.1 code, and this scoped batch specification.  
**Document version:** 1.0, 2026-10-23.

## 0. Order, safety and integration agreements

**Read P2.1 actual code/contracts before editing anything.** The source DTOs below are illustrative and should map onto proven P2.1 names, not trigger a rewrite. Do not fake VERIFIED prerequisite records or assume that a generated prompt has already been implemented.

| Phase | Prerequisite | Owner | Deliverable | Strictly excluded |
|---|---|---|---|---|
| P2.2 | P2.1 VERIFIED; prior P0/P1 ledger proof | Backend/source integration | One permission-reviewed live-source adapter for bounded Lahore schools; manually provided seed import fallback; source audit | Accounts created automatically, fuzzy dedup, scraping Google/other restricted sites, AI analysis, contact discovery, outreach |
| P2.3 | P2.2 VERIFIED or source-compatible imported fixture gate | Backend/domain integrity | Conservative account identity resolution, suggestions, reversible reviewed merges, 20+ ground-truth fixtures | Auto-merging fuzzy candidates; business scoring; treating schools in a chain as the same campus |
| P2.4 | P2.3 VERIFIED, P1.1 auth, P1.4 accounts, P1.5 durable jobs | Full-stack/reliability | Operator discovery-run creation, result/review UI, admission to accounts and honest progress | Messaging, campaign enrollment, automated qualification, scraping beyond allowlisted providers |

### Immutable cross-phase rules

1. **Source rights first:** Descriptor must be explicitly enabled, reviewed, operation-licensed and have documented allowed storage class, retention, quotas, attribution and allowed hosts. Unknown rights fail closed. No bypass via fixtures/imports/worker.
2. **Public school listing is not buying intent.** School type, ownership, number of campuses, budget, ERP, principal identity and software need remain **unknown** unless separately evidenced. A public phone number is not marketing opt-in.
3. **Candidate ≠ Account ≠ Contact.** P2.2 creates reviewable, source-backed candidates/provenance, not CRM accounts; P2.3 creates identity decisions; P2.4 creates an account only on a documented, authorized review action.
4. **No external sends** of WhatsApp, SMS, email or any campaign-related call. No live outreach in these phases.
5. **Organization-scoped** queries, keys, jobs, audits and exports; do not trust `organization_id` or roles from client payloads. Honor existing CSRF/session authorization.
6. **Postgres owns durable state**, Redis may wake worker but is never sufficient proof of enqueue/completion. Jobs are at least once; every ingestion/accept effect must be idempotent.
7. **Use P2.1 `search(SourceQuery,limit,cursor)` / `fetch(source_key)`** and its budget/policy/provenance services. Any modification to a shared DTO is backward-compatible with `SOURCE-01…SOURCE-10`; document an ADR for substantial change.
8. **No invented locations or contacts.** Use a verified/cited administrative area boundary or an explicitly supplied and sanity-checked operator bbox; an area *name* must not imply known polygon geometry.
9. **Preserve provenance and lifecycle:** provider + external id + observation timestamp + rights policy version + expiry + source URL only when permitted. For disallowed content keep only permitted minimal identifiers or aggregate counts.
10. **Every acceptance ID is either VERIFIED with observed evidence, FAILED with remediation or BLOCKED / NOT-RUN**; never claim green merely because the code compiles.

### Reference contract snapshot (adapt to repository; do not assume file locations)

```python
class SourceAdapter(Protocol):
    @property
    def descriptor(self) -> SourceDescriptor: ...
    async def search(self, *, query: SourceQuery, limit: int, cursor: str | None) -> SourcePage: ...
    async def fetch(self, *, source_key: str) -> SourceObservation: ...

# Stable source identity = (provider, element_type, element_id), not just a name.
# `source_records` and P1.4 accounts/facts are authoritative for persistence.
# P1.5 supports allowlisted versioned job types and atomic DB enqueue/outbox.
```

### Database evolution discipline

Inspect migrations and model constraints before creating tables. **Use existing `source_records`, `accounts`, `account_aliases`, `account_facts`, `audit` and jobs whenever compatible.** Add tables for candidate queue/merge suggestions/discovery runs only when each phase needs them. For organization isolation: scope foreign keys and service joins to organization as actually modeled (composite key or guarded lookup); do not treat an org field in API JSON as authorization. All user-meaningful state changes require actor, timestamp, correlation ID and reason where relevant.

---

# P2.2 — First real, rights-aware Lahore school discovery input

## 2.2.0 Goal, deliverable and bounded proof

**Outcome:** An operator can deliberately enable one documented lawful source and ingest a bounded set of real, *unverified as prospects*, Lahore school listings. A local user-supplied seed file provides a usable alternative if no approved live endpoint is available. Output retains source identity, applicable licensing, capture time and clear unknowns. No automatic school-account creation or speculative decision-maker details.

**Recommended first source:** OpenStreetMap (OSM) school POIs through a **small, deliberate Overpass read-only query** with a configured endpoint and explicitly validated Lahore-area geometry. A licensed, offline OSM extract is the better route if repeated systematic collection is needed. An operator-provided CSV is the fallback and is not advertised as independently verified data. **Do not use public Nominatim for systematic POI acquisition or reverse-geocoding grids.**

OSM is licensed ODbL; record attribution requirements and derivative-database implications for future external distribution. Public Overpass endpoints are shared infrastructure, not an unlimited free API; configure conservative request/time/byte bounds and honor endpoint-specific rate limits, 429/503 and Retry-After. Official references in §5.1.

**OpenStreetMap ≠ proof of school autonomy**: `amenity=school` is a map tag, not a buying qualification. Do not imply that all Lahore schools are represented, still active, private, independent, receptive, or reachable.

## 2.2.1 Exact API and adapter design

- Reuse P2.1 `SourceDescriptor`, `SourceQuery`, `SourceCandidate`, `SourceObservation`, `SourcePage`, `DiscoveryBudget`. Register **one** real-source descriptor `osm_overpass_schools` with `source_kind=live`, disabled by default. Store `terms_url`, `licence_url`, `attribution_text`, `rights_policy_version`, `last_reviewed_at`, reviewer, `allowed_hostnames`, `permitted_operations`, `storage_class`, expiry/retention and conservative request quota.
- Add explicit operator/admin configuration for the allowed Overpass hostname; no user-entered endpoint or arbitrary URL. HTTPS only, no redirects to untrusted domains, block private/link-local/loopback/cloud-metadata addresses even after DNS resolution, refuse proxy/environment URL override; preserve allowlist through DNS rebinding defenses. No LLM-accessible URL fetch.
- Use server-produced, parameterized Overpass QL assembled only from validated bounded numeric bbox and fixed school tag. No raw user-supplied query string, arbitrary regex, unbounded `around`, worldwide queries, area-name based implicit geocoding or browser automation. Example logical query: `[out:json][timeout:20];nwr["amenity"="school"](S,W,N,E);out center 30;`. Confirm actual Overpass syntax in integration tests; cap output bytes and parse with bounded JSON. A ways/relations center is representative, not an exact school footprint.
- Only accept `node`, `way`, `relation` with valid positive element id, valid tag structure, sanitized useful `name`, and source key `{element_type}/{element_id}`. Build provenance URL from a validated OSM element key using the official OSM element path, not arbitrary incoming URL. Missing name ⇒ discard or flag for review; do not synthesize names. Coordinates, if present, must be valid finite ranges and within the configured allowed area after considering representation limitations; do not infer street address from map center. No personal details or marketing contacts.
- `SourcePage`: Overpass may not support cursor paging; deliberately return `next_cursor=None` for one bounded query and `has_more_unknown`/partial-limit warning as a separate report field when possible. **30 accepted candidates is a local maximum, not a claim of exhaustive search.** If response has more items than requested/allowed, preserve a truthful truncation status. No grid-sweeping to accumulate hidden extra records.
- For item `fetch(source_key)`, use an approved provider-resolved operation or observation captured in that current search, not arbitrary URLs. Decide whether a second remote request is necessary; avoid it if search already supplies permitted fields. Cache only per source rights policy; never fake a refresh timestamp.
- Record allowed `source_records` with external key and source/license/policy, observed_at (ingestion time) plus upstream OSM data timestamp if provided, and expiration. Store only allowlisted OSM fields needed to display a school listing. No raw unrestricted blobs, contributor identities, cookies, restricted provider values or PII in logs.
- Implement the user-provided CSV fallback as a **separate, explicitly marked manual import source**, requiring `source_label`, permission/use declaration, file checksum, import_actor, capture timestamp and optional provenance URL per row if lawful. CSV schema minimal: `school_name, city, locality, source_reference, external_key(optional)`; optional website only if the owner asserts source rights. Validate UTF-8/BOM/Urdu, size and row count; reject macro/files/formula payloads from being used as instructions; prevent spreadsheet formula execution on later exports; no URL fetching, guessed phone or contact extraction. Use a distinct descriptor policy, not OSM licensing for user data.
- Store source version and deterministic import idempotency `(org,provider,source_key,source_snapshot_or_file_hash)` as appropriate. Repeated same source snapshot does not multiply review candidates; newer observations may update permissible metadata with an audited revision. **No contact creation or campaign enrollment**.

### P2.2 controlled ingestion flow

```text
operator policy review -> enable one provider -> resolve validated area/bbox
   -> check credentials/config, rights, quotas, egress
   -> bounded SourceAdapter.search() (or validated seed import)
   -> validate item type, scope, identity, licensing and allowed fields
   -> stage review candidates + append allowed source provenance
   -> report accepted / rejected / truncated / partial and errors
   -> STOP (no account creation, no messaging)
```

**Durable candidate staging:** If existing schema does not provide review-ready candidate rows, add a minimal `discovery_candidates` staging table during P2.2 with: `(id, organization_id, provider, external_key, source_record_id_nullable, display_name, city, locality, observed_at, rights_policy_version, status='unreviewed', source_payload_digest_nullable, created_at, updated_at, constraint UNIQUE(org,provider,external_key))`. Store *only rights-permitted* fields. P2.4 will add `discovery_run_id` association via many-to-many `discovery_run_candidates` if a candidate can recur across runs; **do not prematurely require a P2.4 run record**. If existing equivalent exists, reuse it; no duplicate tables. For sources allowing no persistent candidate fields, don't stage them: report aggregate and mark source unsuitable for durable lead discovery until rights resolved.

## 2.2.2 Work breakdown

- **P2.2.1 — Inventory & policy ADR:** Inspect real P2.1 registry, rights metadata, jobs/source records, error shapes. Record provider decision, ODbL attribution, permitted operations/retention and live-run enablement. Freeze allowed field list and risk matrix.
- **P2.2.2 — Area and transport guard:** Validated operator area geometry; single query builder; HTTPS allowlist + SSRF/redirect/DNS checks; response size/time ceilings. Network client disabled in tests except hermetic stub.
- **P2.2.3 — OSM adapter:** Parse/normalize node/way/relation; provenance; stubbed response fixtures for success, empty, excess, 429, 5xx, malformed, stale and changed tags. Honor P2.1 budgets including attempted calls/retries.
- **P2.2.4 — Durable import/fallback:** Staging, safe source record writing, idempotency, manual CSV adapter with documented rights declaration and row validation; DB integration tests.
- **P2.2.5 — Controlled real-source smoke:** Only after explicit operator opt-in and actual network availability, run **one limited Lahore school query** with a real configured source. Record endpoint, policy version, query bounds, counts, redacted evidence and source attribution. If blocked by provider/ops, mark LIVE-10 **BLOCKED**; offline tests may be verified but subphase's real-source outcome remains unverified. No bypass or fake live data.

## 2.2.3 Acceptance matrix — LIVE-01…LIVE-10

| ID | Test / evidence | Pass requires |
|---|---|---|
| LIVE-01 | Disabled/unreviewed provider, expired rights review, forbidden operation | No network request, no persisted restricted item, typed denied event |
| LIVE-02 | Mock Overpass returns named `node`, `way`, `relation` | Stable `{type}/{id}` keys, typed candidates, source attribution, correct role of `center` |
| LIVE-03 | Malicious name/URL, unknown geometry, invalid IDs/tags and non-Lahore area | Reject/escape; no arbitrary fetch and no guessed locality/site/contact |
| LIVE-04 | 31+ rows, oversize response, huge bbox, excessive runtime | Max 30 accepted, ceiling enforcement, truthful truncated/partial flags and usage |
| LIVE-05 | 429/Retry-After, timeout, 503 and rate-policy disable mid-run | Bounded retries if permitted; no retries past budget; safe partial terminal state |
| LIVE-06 | Rights classes / attribution / retention / expiry, inspect DB + logs | Only licensed allowlisted data persists; OSM notice shown on surfaced data; TTL visible |
| LIVE-07 | Replay exact OSM response or CSV checksum / concurrent import | Same logical candidate identity; no duplicate data or contradictory audit events |
| LIVE-08 | Bad CSV columns, >limit, formula/Unicode/BOM, restricted row | Safe rejection/encoding, explicit source declaration, zero unlicensed row persistence |
| LIVE-09 | Unauthorized org/user, server URL spoof, SSRF/redirect/DNS, old SOURCE gates | No cross-org records or network egress; fixture P2.1 suite remains green |
| LIVE-10 | Explicitly permitted real provider canary on verified Lahore bounds | Observed real result or truthful empty result; actual trace/policy/rights evidence, no fictitious leads |

**Definition of DONE:** LIVE-01…10 verified with logs/test proof. If LIVE-10 cannot be run, report *implementation complete, live integration unverified*, **BLOCKED**, not VERIFIED. A manual seed file is a viable operational fallback but does not substantiate an Overpass live-canary claim. Never fabricate realistic-looking school contact details in test fixtures.

**Rollback:** Disable source descriptor immediately; halt new fetches and mark in-flight attempts cancelled best-effort. Retain only legally permitted existing provenance and operations audit. Revert application changes while preserving review candidates/audit, and repair schema forward if populated; test downgrade only on disposable DB. Record ODbL/source rights if exporting/removing derived data.

**STOP P2.2:** No fuzzy identity resolver, UI, account auto-creation, enrichment/AI, messaging, search outside the reviewed source.

---

# P2.3 — Conservative, inspectable, reversible school identity resolution

## 2.3.0 Goal and explicit errors to avoid

**Outcome:** Repeated listings for the *same physical school campus* are identified without collapsing unrelated schools, branches or similarly named institutions. Automatic action only for exact repeated **provider identity** (idempotent reobservation). Cross-provider and fuzzy name matches become **human-review suggestions**, not automatic merges.

False-positive merge cost is high: one incorrect school identity can contaminate evidence, sales status and later consent. Favor unresolved duplicates over silently wrong merges.

## 2.3.1 Identity definition and decision policy

- **Account identity:** organization + independently identifiable **physical campus/site**, not just school brand. A single school with multiple campuses must remain multiple accounts (future parent/school-group relationship may be modeled separately when evidence exists). Franchise name does not imply same buying authority.
- **Exact observation:** `(organization_id, provider, external_key)` within reviewed source; exact repeats return the existing candidate/account association as applicable. Shared name alone is never sufficient.
- **Cross-source suggestions:** Normalize Unicode (NFKC only where safe for script), whitespace/punctuation, case-fold English, common school suffixes conservatively, and Urdu/English script as separate similarity features; preserve original spelling/aliases. Never rely on aggressive transliteration or strip identifying branch numbers/locality tokens.
- **Evidence features:** exact/near normalized name; confirmed same locality/address; source ID; bounded genuine coordinates/distance when **both points have licensed verified coordinates**; known website/domain only as weak hint unless site is directly evidenced. Missing value stays `unknown`, not match.
- **Disqualifiers:** conflicting explicit campus branch, different verified city/physical site, chain campuses, disjoint license or rights scope, distinct verified school identity. Same website domain for chain branches is *not* a merge signal by itself. A coordinate for a way `center` may indicate a broad campus area, not exact matching.
- **Policy:** `same_provider_same_external_key` => idempotent observation update. Otherwise `suggest_review`, `distinct`, or `insufficient_evidence`. Never auto-merge on arbitrary score cutoff. Ambiguous suggestions must not create conflicting provenance or rewrite records.
- **Versioned deterministic algorithm** produces feature-level explanation, conflicts and algorithm version for audits. No LLM-driven entity merging in P2.3. Do not call a model to infer principal/owner.

```python
class IdentitySuggestion(BaseModel):
    organization_id: UUID
    left_candidate_id: UUID
    right_candidate_id: UUID | None = None
    existing_account_id: UUID | None = None
    resolution: Literal['exact_reobservation','suggest_review','distinct','insufficient_evidence']
    reason_codes: list[str]
    evidence_source_record_ids: list[UUID]
    algorithm_version: str
    features: dict[str, str | float | None]  # no unrestricted upstream text

class ResolveDecision(BaseModel):
    suggestion_id: UUID
    action: Literal['confirm_same_campus','mark_distinct','defer','undo']
    expected_version: int
    reason: str
```

Actual schemas are adapted to verified P1.2/P1.4 persistence and P2.2 staging. `undo` must link the original decision and restore distinct candidate/account provenance associations **without erasing source or correction history**. If a previously merged account has acquired later unrelated facts, use a safe reallocation review instead of blindly moving facts.

### Persistence/invariants

Minimal `identity_suggestions` table if not already present: `(id,org_id,left_candidate_id,right_candidate_id_nullable,existing_account_id_nullable,algorithm_version,feature_summary_json,reason_codes_json,status [pending|confirmed|distinct|deferred|superseded|undone],reviewer_user_id_nullable,reviewed_at_nullable,decision_reason_nullable,version,created_at)`. Add `identity_decisions` append-only event log including actor, prior and next status, source IDs and reversal references, correlation ID. Guard `UNIQUE(org,left,right,algorithm_version)` with canonical ordered pairs; candidate and account FKs scoped to org. Avoid hard-deleting duplicate entities or their source records. **Decision must be idempotent** for identical command key and fail 409 on stale version/different payload.

Cross-provider merge creates an *association* after review; do not delete one candidate. If accepted into P1.4 accounts later, use a separate `candidate_account_links` table with documented uniqueness and source provenance. If a source cannot legally be persistently associated, don't create the link. Migrations only when needed, rehearsed on a disposable DB.

### Candidate fixture contract — >=20 examples (ground truth)

```
01–03 identical source ID reobserved; name changed, same provider
04–05 spelling/whitespace/punctuation differences, same campus (suggest only)
06–07 Lahore vs Gujranwala, same generic school name (distinct)
08–09 same brand, different Lahore campuses (distinct)
10–11 same brand/domain, different franchise operators (distinct unless evidenced)
12–13 Urdu vs English script alias, partial unknown (review/insufficient)
14–15 same address with different school brands (review, never automatic)
16 missing city; 17 missing locality; 18 missing valid source key (reject upstream)
19–20 GPS coordinate conflict / way-center ambiguity
21 one school renamed, proof direct-source alias (review)
22 same name and locality, distinct school IDs, insufficient evidence
23–24 malicious instruction/name collision, duplicated candidate under concurrency
```

No real individuals/phone numbers; explicit `expected_resolution`, evidence, negatives, and fixture version. Include adversarial false positives. Exact duplicate class is only for repeated identical `(org,provider,key)` observations—not the vague statement that two names “look identical.”

## 2.3.2 Work breakdown

- **P2.3.1 — Baseline and test dataset:** inspect P2.2 real staging, P1.2 evidence/corrections, normalized account aliases and P1.4 optimistic locks; encode >=20 gold pair outcomes before implementation.
- **P2.3.2 — Deterministic resolver:** implement pure feature normalization/decision logic with explainable reason codes and disqualifiers, no network/model dependencies. Benchmark small candidate pool to avoid O(N²) brute force where reasonable; local blocking by city/name token to propose pairs.
- **P2.3.3 — Suggestion persistence:** append-only review decisions and constrained associations, organization isolation, unique keys, concurrency handling and algorithm version.
- **P2.3.4 — Safe review service:** typed service/API for confirm distinct/defer/undo using existing role/CSRF, `expected_version`, and reason; P2.4 can render UX. Human confirmation when cross-provider identity is ambiguous; no automatic deletion/reparenting.
- **P2.3.5 — State/reversal tests:** 20+ fixture evaluation, concurrent operators, stale source updates, undo with post-merge evidence, scope leakage, regression and ledger. Stop.

## 2.3.3 Acceptance matrix — IDENTITY-01…IDENTITY-10

| ID | Test / evidence | Pass requires |
|---|---|---|
| IDENTITY-01 | Re-ingest same provider+key with changed name | One logical candidate identity; updated licensed observation with history |
| IDENTITY-02 | Near-identical name and site from separate providers | Review suggestion with reason codes, no automatic merge |
| IDENTITY-03 | Same name in different cities or proven distinct Lahore campus | Distinct, no merge even if website/brand overlaps |
| IDENTITY-04 | Franchise/chain branch aliases + shared domain | Separate campus identities and explicit uncertainty on buying autonomy |
| IDENTITY-05 | Missing locality, Urdu/English variants, tricky punctuation/suffixes | Unknown/review not fabricated match; original aliases retained |
| IDENTITY-06 | Confirm same campus with authorization and version; replay command | Audited, idempotent association; source provenance remains intact |
| IDENTITY-07 | Stale version/double reviewer/undo with new facts | 409 on conflicts; reversible association; ambiguous facts held for review |
| IDENTITY-08 | Cross-organization pair/foreign IDs, observer mutation, missing CSRF | Denied and unchanged; no cross-org data or suggestion leakage |
| IDENTITY-09 | Run >=20 labeled pair fixtures, malicious strings and long inputs | Explicit gold expectations all pass; stable deterministic explanations |
| IDENTITY-10 | Restart/migrate then rerun resolver and SOURCE/LIVE gates | No duplicate suggestions or lost decisions, earlier integrations preserved |

**Rollback:** Disable new suggestion generation; preserve all audited decisions. Revert association feature by reversible application-side compensation or manual correction with history, never cascade-delete source records/accounts. Schema down migrations only on disposable/empty environment after proving safety.

**STOP P2.3:** No discovery-run UI, automated account admission, qualification, contact enrichment, campaign or messaging.

---

# P2.4 — Operator discovery runs, reviewable candidates and explicit admission

## 2.4.0 User journey and hard boundary

**Outcome:** A logged-in operator selects `school`, a verified Lahore area, an enabled permitted source, and a downward-bounded research budget; sees durable progress and a maximum of **30 reviewed candidates per initial run**; inspects source evidence and dedup suggestions; manually admits selected candidates to P1.4 accounts without a false assertion that contactability or need is verified.

**This is a first usable vertical slice** but not a qualified lead pipeline: P3.1–P3.4 will research operational signals and assign suitability later. Offer matching and outreach are still excluded.

```text
[New Discovery Run]
    choose: Lahore area / schools / allowed provider / 1–30 candidates / quota
    -> Preview rights/attribution and dry-run limits -> Start
    -> 202 Accepted + run ID; P1.5 job committed atomically
    -> worker source adapter -> licensed staging + resolved suggestions
    -> UI: progress, error/partial states, evidence, match suggestions
    -> reviewer: Accept as new campus / Attach to existing (confirmed) /
                 Mark distinct / Reject / Defer
    -> P1.4 account creation or verified association + audit
    -> STOP. No outreach, no auto qualification.
```

## 2.4.1 Persistence and API contracts

Add a **minimal durable run/read model** by inspecting existing P2.2 staging and P1.5 job receipt. Suggested structures, adapt to actual schema:

```text
discovery_runs:
 id UUID, organization_id UUID, created_by UUID, vertical_slug TEXT,
 area_id UUID, provider TEXT, descriptor_version TEXT, rights_policy_version TEXT,
 budget_snapshot_json JSONB, filter_snapshot_json JSONB, status ENUM,
 examined_count INT, staged_count INT, rejected_count INT, displayed_count INT,
 truncated BOOLEAN, partial_reason_code NULLABLE, error_code NULLABLE,
 started_at, finished_at, requested_cancel_at, job_id UUID, version INT,
 created_at

# run association is many-to-many; candidate may appear in repeat runs
discovery_run_candidates:
 organization_id, run_id, candidate_id, source_record_id_nullable,
 display_status [pending|accepted|rejected|deferred],
 review_note_nullable, reviewed_by_nullable, reviewed_at_nullable,
 UNIQUE(organization_id, run_id, candidate_id)

# if P2.3 built candidate-to-account links, reuse them (don't duplicate)
```

State machine: `pending → running → {completed,partial,failed,cancelled}`; `pending → cancelled` permitted. `completed` means bounded source processing finished, **not exhaustive discovery**. `partial` includes sources unavailable or source-capped; `cancel_requested` may be an intermediate field/state. Terminal states immutable except separate audited correction/review state; no `completed` after a committed cancellation. Leases/fencing from P1.5 protect against late workers writing terminal run state.

### HTTP interface (proposed names; adapt naming to existing versioned API)

| Method and path | Auth | Payload contract / semantics |
|---|---|---|
| `POST /api/v1/discovery/runs` | owner/operator + CSRF | `{area_id,vertical_slug:'school',provider_id,budget:{max_candidates:1..30,max_pages,max_fetch,max_seconds},idempotency_key}`. Resolve area+provider server-side; never accept arbitrary network URL/bbox from front-end. Commit run, budget snapshot, outbox and `discovery.run.v1` job atomically. 202 + `run_id`, job ID. |
| `GET /api/v1/discovery/runs` | owner/operator/observer | Scoped cursor-paginated list, compact progress/status/error code, never secret payload. |
| `GET /api/v1/discovery/runs/{id}` | owner/operator/observer | Run state with version, budget usage, source policy, timestamps, terminal/partial reason. 404 on other org. |
| `GET /api/v1/discovery/runs/{id}/candidates` | owner/operator/observer | Scoped cursor pagination, max 30 admitted/displayed results, rights-allowed evidence + attribution + match/explanation + review status. |
| `POST /api/v1/discovery/runs/{id}/cancel` | owner/operator + CSRF | Idempotent cancellation; sets request flag; worker checks before/after source attempt/DB batch and doesn't commit new accepted account actions post-cancel. |
| `POST /api/v1/discovery/runs/{id}/candidates/{candidate_id}/decision` | owner/operator + CSRF | `{action:'accept_new'|'attach_existing'|'reject'|'defer'|'mark_distinct', existing_account_id?, expected_version, idempotency_key, reason}`. Validate P2.3 identity decision when attaching. Result account ID or rejection confirmation; no hidden auto-merge. |

**Service invariants:** Accepting a candidate creates a `school` account using P1.4 service *inside a transaction that records allowed provenance, source link and operator decision*. A candidate must be licensed/still permissible at review time; expired/missing rights blocks admission or requires a newly permitted observation. Repeat identical decision returns same account; changed payload with reused idempotency key => 409; simultaneous approval by two operators converges to one admission. Account statuses default `unverified/pending_research`, not `qualified`. No contact, consent, school principal, pricing, needs, campus count, or delivery-fit fields inferred. If attaching to existing account, require explicit reviewed same-campus proof and preserve individual candidate/source records.

### UI requirements

Pages/components integrated into existing authenticated Next.js shell:

- Discovery landing: runs table, created by, area, source, status, completed/partial labels and quota counters; visible retry/cancel affordances only for eligible states.
- New-run screen: accessible area and source selection, rights summary with attribution/license, exact budget constraints and initial `max_candidates<=30`; no hidden geo grid scanning. Show preflight errors before starting.
- Run detail: progress from durable DB state (polling sufficient; no WebSocket infrastructure), truthful empty / error / partial / cancelled states; inspected and displayed counts; source timestamp, direct source link only when allowed, stale/unknown badges, no speculative ownership/ERP/phone.
- Candidate review: source metadata and permitted evidence, identity suggestion reasons, possible campuses, `accept as new`, `attach existing` requiring confirmation, `distinct`, `reject`, `defer`; version conflict explains refresh. Operator actions preserve audit trail. Observer read-only.
- Accessibility/resilience: keyboard actions, screen reader labels, responsive layouts, Unicode/Urdu names, XSS-safe text, sanitized URLs and CSV formula-safe export if export already exists. Show source OSM/ODbL attribution when relevant.

### Budget/partial/cancellation semantics

- Operator budget can only **tighten** approved source and platform maxima; enforce in API, durable job payload, worker and adapter again (TOCTOU). Never rely on disabled submit button.
- Hard initial maximum **30 candidates displayed in the run**. Incoming 31+ records must set `truncated`/partial reason or be rejected appropriately, not silently claim full city coverage. Distinguish `examined_count`, `staged_count`, `distinct_displayed_count`, `rejected_count`, `accepted_as_accounts_count`, and `budget_consumed`.
- Run requests are idempotent by `(org, actor/operation, idempotency_key, canonical payload hash)`. One logical job/transaction per run. Crash after commit does not orphan run or double-process user admission.
- Rate limit/circuit break per provider; on 429 or source down expose `partial` with safe reason. On worker restart resume from valid checkpoint only when source adapter supports repeatable deterministic cursor/snapshot; for Overpass no cursor, restart as a **new attempt of same logical run with dedupe**, not a claim of complete continuation.
- Cancellation is cooperative: an in-flight external request cannot always be physically revoked, but no further attempts should begin once cancellation is committed. Preserve already-processed candidate reviews; never delete account records as a side effect of cancelling a discovery run.

## 2.4.2 Work breakdown

- **P2.4.1 — Contracts and migrations:** review real P2.2/P2.3 schema and P1.5 job version; build API DTOs and state invariants/tests; add narrowly scoped run+join schema where required.
- **P2.4.2 — Bounded run backend:** typed endpoints; allowlisted `discovery.run.v1` handler; transactional run/job enqueue; stable snapshot/policy precheck; budget tracking; state transitions, cancellation, idempotency/locks.
- **P2.4.3 — Review decisions:** rights check at review time, P2.3 suggestions confirmation, P1.4 service account admission/association, audit/optimistic concurrency, safe correction paths.
- **P2.4.4 — UI:** searchable runs and detail/candidate list, budget form, source rights, reviewer actions, role-dependent controls and accessibility. Reuse existing design system/test tools; no new frontend framework.
- **P2.4.5 — End-to-end proof:** full synthetic discovery run using P2.1 fixture and a permitted P2.2 recorded/live canary as available; assert no outreach, restart recovery, no data leakage; update ledger and stop.

## 2.4.3 Acceptance matrix — RUN-01…RUN-10

| ID | Test / evidence | Pass requires |
|---|---|---|
| RUN-01 | Operator creates Lahore/school run using permitted source and budget <=30 | 202, scoped durable run+job/outbox transaction, correct budget snapshot |
| RUN-02 | Unauthorized, observer, CSRF-free POST and cross-org source/area | Denied before enqueue, no run/job, no leak via GET |
| RUN-03 | Worker processes bounded fixture/allowed source, reload UI | Correct progress, accepted/rejected/examined, source attribution and trace |
| RUN-04 | 31+ upstream, 429, 503, stale policy and empty results | Hard budget; truthful `partial/truncated/failed/empty` status, no invented leads |
| RUN-05 | Replay create with same/different idempotency payload, 2 workers | Single logical run for identical request; collision 409; no duplicate staged review items |
| RUN-06 | Reviewer accepts as new campus then replays/concurrent accepts | One scoped P1.4 account with source proof and unknown needs; audited decision |
| RUN-07 | Confirm/reject/attach distinct campus; cancel then late worker | No automatic fuzzy merge, no unsafe state resurrection; already-admitted records survive |
| RUN-08 | Expired/unlicensed candidate, stale version, cross-org account attachment | No admission, safe 409/403/404 and no foreign source association |
| RUN-09 | Keyboard/Urdu/long input/observer UI, app restart with volumes | Accessible, sanitized UX; persisted run, evidence/decision history after restart |
| RUN-10 | E2E UI → API → job → source → candidate → reviewer → account | Reproducible with fixtures, previous P0–P2.3 suites green, zero outbound sends |

**Rollback:** Disable run creation/source; pause job handler via allowlist flag while keeping pending rows visible, stop worker cleanly, preserve source/decision/audit history, roll back UI/API deployment, forward-repair populated migrations instead of destructive down scripts. Restore from backup only through existing P0/P1 runbook. Never delete jobs/accounts to manufacture a passing clean run.

**STOP P2.4:** No scraping more sources, no lead scoring, no model calls, no campaigns, no WhatsApp, no autonomous follow-up. Next allowed work begins at **P3.1 evidence extraction** after gate signoff.

---

# 5. Handoffs, R&D decision record, and completion proof

## 5.1 Source policy evidence and verification links (checked 2026-10-23)

1. OSM database licensing and attribution: https://www.openstreetmap.org/copyright and https://osmfoundation.org/wiki/Attribution_Guidelines ; ODbL obligations apply to permitted uses, derived databases and public outputs subject to licence terms.
2. OSM's own API policy distinguishes its editing API from Overpass read-only querying, and warns large/frequent data users to use downloads: https://operations.osmfoundation.org/policies/api/ (or https://openstreetmap.github.io/owg-website/policies/api/).
3. Overpass bounded tag+bbox query examples: https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_API_by_Example . Instance-specific usage/limits must be rechecked when enabled; **do not assume a universal free quota**.
4. For repeated/bulk collection, Geofabrik Pakistan OSM extract and licence: https://download.geofabrik.de/asia/pakistan.html and https://www.geofabrik.de/data/download.html . Downloader/importer is **not** implemented in this batch.
5. Public Nominatim API has restrictive use policy, forbidding systematic all-POI/grid queries: https://operations.osmfoundation.org/policies/nominatim/ ; public Nominatim is **not** used.
6. Google Places content storage/caching and other conditions are restricted: https://developers.google.com/maps/documentation/places/web-service/policies ; **do not scrape Google Maps or construct a durable CRM database from restricted Google Places content**.

These references inform architecture, **not a blanket legal approval**. Before activation of a real endpoint, record operator review of that endpoint's current terms, ODbL attribution and storage rights. Do not copy assumptions about source permissions to other providers or use robots.txt as standalone proof of permission.

## 5.2 Cross-subphase end-to-end contract checkpoints

| After | Run this | Evidence expected | Next-phase constraint |
|---|---|---|---|
| P2.2 | source fixture + 1 authorized small real canary (if available) | Licensed, bounded Lahore school candidates with provider IDs and rights | P2.3 reads stable scoped candidates and source records; no duplicate source identity creation |
| P2.3 | 20+ labeled pair fixtures + concurrent correction/reversal | Explainable merge suggestions and reversible reviewed associations | P2.4 never bypasses review when moving a candidate to an account |
| P2.4 | logged-in run → worker → results → explicit reviewer admission → account view | Stable account and source audit with at most 30 displayed run candidates; no sends | P3 uses only reviewed approved accounts and verified evidence |

## 5.3 Standard Opus execution harness — mandatory for every prompt

1. Read blueprint, batch file, accepted ADRs, `AGENTS.md`/`CLAUDE.md` if present, prior ledgers and actual code; print current git branch/SHA/status, migration head, dependency versions and baseline check results. Do not assume repo paths shown in examples exist.
2. **Gate prerequisites**: check required previous subphase VERIFICATION with executed commands/results. On missing evidence, do not silently recreate upstream implementations; identify the minimum blocker and STOP if prerequisite actually absent.
3. Create acceptance ledger with per-ID `requirement / module / test ID / negative path / observed result` before editing. Scope proposed changes to current subphase, including allowed migration and backwards-compatible API contracts.
4. Implement by small units: schema/contracts → services → adapters/worker/UI as applicable → tests. Pin dependencies; no unrelated refactors, network privileges, new queues or unneeded libraries.
5. Run formatter/lint/typecheck, unit and contract tests, DB integration tests and migration upgrade/downgrade-on-disposable DB where needed, E2E only where relevant. Inject errors and confirm **persisted state after failure**, not only response codes.
6. Self-review security (scope, SSRF, XSS, CSRF, injection, policy, data retention), concurrent transactions, budget overshoot, idempotency, at-least-once replay, source and error redaction, permission changes, schema compatibility and truthful reporting.
7. Record exact commands, exit codes and select sanitized logs/evidence for every acceptance ID. Use **VERIFIED, FAILED, BLOCKED, NOT-RUN**, never speculative PASS. Update `EXECUTION_LEDGER.md`, source/contract docs and any ADR with observed outcomes.
8. **STOP at subphase boundary.** Provide short final report: changed paths, migrations, tests, failures, unresolved external blockers, rollback, release verdict, next safe subphase. Do not auto-start next phase.

## 5.4 Batch acceptance ledger seed

| Requirement family | IDs | Count | Demonstration |
|---|---|---:|---|
| Rights-aware live source | LIVE-01 to LIVE-10 | 10 | Policy gate, constrained OSM source or seed fallback, DB provenance, 1 live smoke |
| School identity resolution | IDENTITY-01 to IDENTITY-10 | 10 | 20+ labeled pair fixtures, conservative merge, concurrency, undo |
| Discovery-run experience | RUN-01 to RUN-10 | 10 | Authenticated UI, limited job run, licensed evidence, human account admission |
| **Total** | | **30** | All three subphases independently verifiable |

### Explicit status disclaimer

This is a **planning and execution package**. No application source code has been modified, no repository CI/test was run, and no real Lahore school search was executed in producing this document. Opus must provide its own observed implementation evidence.
