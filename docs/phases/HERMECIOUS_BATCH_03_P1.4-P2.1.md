# HERMECIOUS — Batch 03: P1.4–P2.1

**Status:** Technical execution specification; not a claim of implemented or tested application code.  
**Executor:** Claude Opus 5.5 High, one subphase per execution.  
**Market:** Lahore, Pakistan. **Vertical:** independently operated schools.  
**Authority precedence:** accepted repository ADRs + actual verified contracts > this batch's recommendations for implementation details; product and security invariants of `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` remain binding. Conflicts require explicit ADR and human review, not silent rewrites.

## 0. How to use this batch

1. Copy this file to `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` and the prompts to `docs/prompts/` (or a consistent repository documentation directory). Keep master blueprint at `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`.
2. First confirm **P0.1–P0.4 and P1.1–P1.3 are VERIFIED** in `EXECUTION_LEDGER.md` with executed evidence. A completion statement from a model is not evidence. If prerequisite code or tests do not exist, STOP and report the exact gap; do not reconstruct it as a side quest.
3. Execute **P1.4**, close and independently review; then **P1.5**; then **P2.1**. Each prompt forbids advancing to the next task.
4. Adapt suggested paths to actual repository layout; avoid auto-scaffolding empty modules. Preserve all user changes and never reset a dirty worktree to make tests pass.
5. Use synthetic Lahore-like sample names and fabricated contact-free data in tests. No unapproved web scraping, external sends, production data fetches, real customer contact data or added AI agent workflows in this batch.

### 0.1 Dependency contract and phase boundaries

| Slice | Must already exist | Owns now | Must NOT build |
|---|---|---|---|
| **P1.4** | P1.1 session/CSRF/RBAC, P1.2 accounts/sources/facts/rights, P1.3 offer catalog | Account API and admin UI, manual evidence entry/corrections, audit trail | Web crawling, qualification, campaigns, bulk imports, WhatsApp, background scheduler |
| **P1.5** | P0 worker/Redis/Postgres, P1.1 actor org, P1.2 scoped domain models, P1.4 API | Durable `jobs` + `outbox_events`, worker claiming, replay/retry, observability | Messaging providers, model calls, arbitrary code executor, agent orchestration, distributed broker migration |
| **P2.1** | P1.2 source rights/provenance, P1.5 durable job substrate | Typed `SourceAdapter` contracts, fixture adapter, registry, budgets and provenance-preserving fixture ingest | Live provider connection, live web search, arbitrary URL fetch, school crawling, deduplication/lead scoring |

### 0.2 Invariants across the batch

- **Organization scoping is server-derived.** A client-supplied `organization_id` never authorizes cross-organization access. Composite scoped FKs and scoped queries persist across new tables.
- **Facts, hypotheses and corrections are different.** A manually typed assertion is `hypothesis` unless backed by a permitted, dated source and valid evidence; correction never silently deletes previous provenance.
- **Licensing first.** Source URL/source key/observation itself is stored only if provider/source policy permits it; storage classification is not a sending/contact permission.
- **A returned success means persisted state.** `POST` write results must commit before responding; worker/job notifications are advisory, not primary persistence.
- **No hidden side effects.** All eventual outbound messaging must pass future deterministic send authorization; nothing in this batch sends to businesses.
- **Untrusted material remains data.** UI escapes source text and facts. Later model prompts cannot receive instructions from those values as authority.
- **No accidental bulk deletion.** Never run destructive Compose volume deletion, unreviewed production migration downgrades, or auto-clear the database on worker errors.
- **Observed evidence matters.** Each test must execute and record final DB/UI/job state after the failure, not just an HTTP status or mocked assertion.

### 0.3 Shared conventions

- API prefix `/api/v1`, UUID identifiers, JSON bodies, server-authenticated actor, session-bound CSRF for mutations, errors `{code,message,trace_id,retryable}`, times UTC RFC3339 at API boundary and `Asia/Karachi` for display.
- Backend FastAPI + Pydantic + SQLAlchemy 2 + Alembic; frontend Next.js + TS; Postgres source of truth; Redis used for optional wake-up, never as sole job storage.
- Use P0.4 trace ID + redaction. Do not log account evidence excerpts containing sensitive data by default.
- If P1.1 defines owner/operator/observer roles, owner+operator may create/edit, observer reads. Owner-only destructive/admin operations; per-right adjustments require ADR.
- Cursor pagination must be keyset based with a stable order and opaque authenticated/filter-bound cursor or equivalent validated scheme; no unbounded scans exposed via API.
- Each changeset has a migration strategy if schema changes, explicit negative tests, rollback path, and an `EXECUTION_LEDGER.md` section with command outputs/execution status.

### 0.4 Cross-slice contract index

| Producer | Contract guaranteed | Downstream consumer |
|---|---|---|
| P1.4 | Account list/detail + sourced fact/hypothesis/revision read model, version checks | P2.1 preview/UI eventually, P3 evidence/qualification |
| P1.4 | Provenance-preserving correction history and source rights checks | P3 researcher + evidence verifier |
| P1.5 | `enqueue_job()` DB transaction, bounded executor, idempotent job, dispatchable outbox | P2.1 fixture ingestion and later P2/P4/P5 jobs |
| P1.5 | At-least-once execution + durable retry/dead state, not exactly-once external effects | Every later provider adapter must implement its own side-effect idempotency |
| P2.1 | SourceCandidate/SourceObservation + provenance/rights/budget shape | P2.2 provider adapter, P2.3 dedup, P3 extraction |

---

# P1.4 — Account management API and evidence-first admin interface

**Outcome:** An authenticated operator can create a synthetic Lahore school account, inspect it, attach a permitted source-backed fact or visibly unverified hypothesis, correct an incorrect fact with traceable history, and still see the result after process restart.

**Prerequisite:** P1.3 VERIFIED; P1.2 schema is authoritative, including account `version`, `source_records` and `account_facts`. **Executor role:** one backend+frontend engineering slice with API, migrations only if necessary, and E2E evidence.

## P1.4.1 Scope and suggested affected modules

Inspect actual paths and only add missing pieces near existing repository conventions:

- `apps/api/app/api/accounts.py` (or current versioned router) — authenticated scoped HTTP routes.
- `apps/api/app/services/accounts.py` — create/list/patch/soft-archive, fact add/correct, source rights checks, audit.
- `apps/api/app/persistence/` — scoped repositories and projections using existing P1.2 models.
- `apps/api/app/domain/` — typed request/update fields, valid lifecycle transitions, Pydantic validators.
- `apps/web/.../accounts/` — list, create, detail, evidence card, correction form, states/errors.
- `tests/unit/`, `tests/integration/`, `tests/contracts/`, `tests/e2e/` — fixtures and tests.
- `docs/contracts/account-management.md`, `EXECUTION_LEDGER.md`; Alembic revision **only if a contract needs a genuine schema adjustment**.

Do not invent table names different from P1.2; prefer existing `account_facts` and their status fields. For corrections use an append-only status/audit service, and a small targeted migration only if required for a chain (`supersedes_fact_id` nullable scoped FK or a purpose-built audit row, explicitly choose based on existing P0 audit patterns).

## P1.4.2 API contract

All routes require authenticated actor; all mutations need role permission plus CSRF; account IDs/filters are scoped by actor.organization_id. Response field names should remain consistent with existing P1.2 Pydantic models. The following is minimum observable behavior (implementation can choose request type names):

| Method | Route | Semantics | Failure modes |
|---|---|---|---|
| `POST` | `/api/v1/accounts` | Create account with `vertical_id`, name, `city='Lahore'` initially, optional locality; response 201 with UUID/version | 400/422 invalid; 403 role; 409 logical conflict only if stable key constraint; no silent name-only merge |
| `GET` | `/api/v1/accounts` | Scoped list, bounded `limit` (default 25, max 100), cursor, `city`, `vertical_id`, `status`, search | 400 invalid cursor/oversized limit; 401/403 scope |
| `GET` | `/api/v1/accounts/{id}` | Account+aliases+facts projected with provenance/verification/staleness labels; rights-aware omission | 404 nonexistent or other-org (no existence leak) |
| `PATCH` | `/api/v1/accounts/{id}` | Allowlist `canonical_name`, `locality`, `status` where permitted; require `expected_version` or `If-Match`; increment `version` atomically | 409 version conflict, 422 invalid transition |
| `POST` | `/api/v1/accounts/{id}/facts` | Add validated hypothesis or source-supported fact; rights/freshness checked through P1.2 services | 422 invalid type/claims; 403 forbidden source rights |
| `POST` | `/api/v1/accounts/{id}/facts/{fact_id}/corrections` | Atomic correction: new claim/status with reason + actor/time and linkage to prior fact; prior fact retained and marked disputed/superseded in read projection | 404 cross-org fact, 409 racing correction, 422 missing reason |
| `POST` | `/api/v1/accounts/{id}/archive` | Owner-only safe archive/exclude of account from active operator work, no hard delete of evidence; adapted to existing `excluded` state | 403 role, 409 concurrent change |

**No public delete endpoint** in MVP. Corrections of canonical account information use versioned PATCH + audit; facts retain original source assertions. If P1.2 rejects all raw source additions from public input, source-record creation is a privileged manual evidence workflow that reuses `add_source_record` and enforces URL/rights validation. It must not fetch the URL. Avoid making a public arbitrary source registration endpoint; authorize through the account evidence form/service.

**Create example (illustrative, typed contract, not actual live request):**

```json
{
  "vertical_id": "<UUID-from-verticals>",
  "canonical_name": "Sample Model School — Gulberg (synthetic)",
  "city": "Lahore",
  "locality": "Gulberg"
}
```

**Fact projection semantics:** Return `verification_status`, `confidence_label`, `observed_at`, `expires_at`, `is_stale`, `source` with rights-allowed `provider/source_url`, and correction/supersession reference if one exists. UI must not label `hypothesis` as verified; a source URL alone does not imply support for any statement. Fact excerpts are sanitized and length-capped. `source_supported` and `is_stale` can both be true; staleness is computed from time and revocation/expiry, not quietly rewritten as “unsupported.”

**Cursor:** For `updated_at DESC, id DESC`, encode and validate tuple + filter digest + org scope with tamper-safe signed token or documented equivalent; cursor rejects changed filters/tenant. If search requires trigram/FTS not already available, start with bounded indexed normalized-name search and explain limitations. Avoid `%...%` unbounded full-table scans without bound/plan.

**Concurrency:** `UPDATE accounts ... WHERE id=:id AND organization_id=:org AND version=:expected_version`, plus version increment and `RETURNING`. Detect 0-row due to conflict vs nonexistent while keeping no cross-org existence oracle. Update correction pair/history under one DB transaction; lock prior fact or use unique `(org_id, supersedes_fact_id)` to prevent double correction (the design should allow future chain revisions).

## P1.4.3 Admin UI slice

Build authenticated pages/components for accounts list and account detail only, using existing Next.js app shell/session pattern. The list supports city/status/vertical filters and keyset next page; no unsupported “all city” or large bulk selection. A create modal/page validates fields and displays inline API errors. Detail page has sections: identity, evidence, hypotheses/unknowns, corrections, and audit metadata. Evidence cards clearly show source, observed time, staleness and verification. Correction action requires a reason and confirms that prior evidence is retained. Observer role sees read-only controls; operator sees editing; owner can archive. UI can display labels in English; do not localize prematurely. Basic keyboard accessibility, screen reader labels, loading/empty/error states, long strings, XSS-safe rendering, and responsive detail layout.

## P1.4.4 Implementation work breakdown

- **P1.4.1 Inventory/contracts:** Compare P1.2 entities, auth capabilities, exact cursor/version conventions, source policy registry, P0 logging and P1.3 UI design. Write focused API+UI acceptance tests before functionality.
- **P1.4.2 Account services/routes:** Implement typed scoped list/get/create/edit/archive with optimistic lock; use allowlisted fields, state guards and uniform errors. Reject owner/organization spoofing.
- **P1.4.3 Evidence/correction services:** Reuse P1.2 rights/typed fact registry, append correction history atomically, audit actor/time/reason, project stale/uncertain states accurately. Add migration only if required; rehearse migration safely.
- **P1.4.4 UI and state tests:** Build list/detail/create/correction, ensure session-bound HTTP and UI state for no access, filter changes, optimistic conflicts and errors. Add contract and Playwright E2E.
- **P1.4.5 Verification/documentation:** Execute matrix below with real DB/client; restart API/Compose retaining volumes; document API+workflow, migration/rollback and ledger commands. Stop.

## P1.4.5 Required acceptance matrix

| ID | Action / executed evidence | Expected result after action |
|---|---|---|
| **ACCOUNT-01** | Log in as operator; create synthetic Lahore school through UI/API and reload | 201, UUID/version and persisted scoped account, list/detail agree |
| **ACCOUNT-02** | Add permitted, not-expired synthetic source record and source-supported campus-count fact; reload | UI displays correct fact, source, time, verification and licensing; retained after restart |
| **ACCOUNT-03** | Add unsupported/unknown-ERP hypothesis | UI explicitly displays hypothesis/unknown; never presents verified software absence |
| **ACCOUNT-04** | Correct ACCOUNT-02 fact with reason and actor, reload + inspect DB | Historical assertion retained, linked successor appears, current view not ambiguous |
| **ACCOUNT-05** | Submit concurrent/old-version PATCH and double correction | Exactly one valid winner, second 409; no overwritten update or two “current” facts |
| **ACCOUNT-06** | Owner/operator/observer/unauthenticated, missing CSRF mutations | Roles correct, unsafe/anonymous mutation denied, observer read-only, no writes persist |
| **ACCOUNT-07** | Cross-organization URL, facts, source-reference and raw scoped lookup | Other-org accounts hidden as 404, FKs/service prevent cross-org linkage |
| **ACCOUNT-08** | Invalid cursor/filter/limit, bad state, invalid/stale/forbidden source | Typed error with trace ID; zero invalid writes, rights stay enforced |
| **ACCOUNT-09** | HTML/script payload, very long/Unicode name/excerpt, mobile + keyboard UI | Safe text rendering, no executable injection, bounded validation and usable controls |
| **ACCOUNT-10** | Restart app/DB client (preserve volumes), run migrations + prior suites | Account/facts/correction/audit persist, old P1.1–P1.3 behavior unchanged |

**Additional negative paths:** Postgres loss mid-request; failed archive with active materialized data (none expected yet); UI cache showing stale version; changing filters while paginating; duplicate school names across localities, source URL SSRF shape validation (no fetch); expired facts display stale. Observability logs use IDs rather than raw evidence bodies.

**Rollback:** Prefer reverting API/UI deployment and forward migration repair if data exists; optional schema backout on disposable DB only. Preserve all account and evidence history. Prove migration compatibility if you added a column/index. **STOP after P1.4: no jobs/outbox/discovery implementation.**

---

# P1.5 — Durable background jobs, transactional outbox and safe worker execution

**Outcome:** A committed business transaction can create a durable job and event. Redis may go offline, workers may crash, and duplicate dispatch attempts may occur without losing committed jobs or running a logical DB effect twice.

**Prerequisite:** P1.4 VERIFIED; P0 worker container already present; P1.1 org-scoped principal and P0.4 log/errors reused. **Executor role:** backend/persistence reliability slice; UI limited to existing operator diagnostics if essential. **Not a messaging reliability guarantee yet.**

## P1.5.1 Explicit architecture resolution

Choose **PostgreSQL as the durable queue and outbox authority**, with Redis as an optional notification/wake-up accelerator. Do not make a Redis publish a prerequisite for job processing or authoritative queue state. A single DB transaction may mutate a domain row, insert an idempotent `jobs` record and an `outbox_events` record. After COMMIT, an outbox publisher can notify Redis; workers must also poll Postgres so notification outage never strands work.

```text
HTTP/domain service
   └─ ONE PostgreSQL transaction
         ├─ domain state / audit
         ├─ jobs row (durable intent)
         └─ outbox_events row (durable event)
   └─ commit -> return acknowledged job ID

worker: Postgres SKIP LOCKED claim -> handler -> transactional terminal state
              ↑
      optional Redis wake-up from outbox publisher
      + periodic DB polling independent of Redis
```

**At-least-once is the actual contract.** If the handler writes to Postgres, it must commit the logical DB effect and job terminal acknowledgment in one guarded transaction, or use an independent unique effect-idempotency constraint; repeated claims then preserve exactly-once *logical DB effects* where that constraint is demonstrated. External providers cannot be assumed exactly once across send/ack failures; later P5 implements provider IDs and reconciliation. Prohibit any real external send handler now. For outbox, explicitly define whether `dispatched_at` means successfully offered to the optional notification sink (NOT job processed). Do not treat Redis notification as durable consumption. Outbox event consumers must dedupe by event UUID; a payload field `event_schema_version` allows evolution.

## P1.5.2 Minimum data contract (map onto current models if already present)

```text
jobs:
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  job_type TEXT NOT NULL
  job_schema_version INTEGER NOT NULL DEFAULT 1
  payload_json JSONB NOT NULL    -- validated typed payload, no arbitrary Python/class/function references
  payload_digest CHAR(64) NOT NULL
  status enum/check('pending','running','retry_wait','succeeded','dead','cancelled')
  attempts INTEGER NOT NULL DEFAULT 0
  max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 10)
  available_at TIMESTAMPTZ NOT NULL
  lease_owner TEXT NULL
  lease_expires_at TIMESTAMPTZ NULL
  started_at/finished_at TIMESTAMPTZ NULL
  last_error_class TEXT NULL    -- safe taxonomy only, never secrets/PII
  idempotency_key TEXT NOT NULL  -- caller-provided or derived stable logical operation key
  correlation_id TEXT NULL
  created_at/updated_at TIMESTAMPTZ NOT NULL
  UNIQUE(organization_id, job_type, idempotency_key)
  index(status, available_at, lease_expires_at, id)

outbox_events:
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  aggregate_type TEXT NOT NULL
  aggregate_id UUID NOT NULL
  event_type TEXT NOT NULL
  event_schema_version INTEGER NOT NULL DEFAULT 1
  payload_json JSONB NOT NULL   -- non-sensitive normalized event payload
  idempotency_key TEXT NOT NULL
  dispatched_at TIMESTAMPTZ NULL
  attempts INTEGER NOT NULL DEFAULT 0
  next_attempt_at TIMESTAMPTZ NOT NULL
  lease_owner/lease_expires_at TIMESTAMPTZ NULL
  created_at TIMESTAMPTZ NOT NULL
  UNIQUE(organization_id, event_type, idempotency_key)
  index(dispatched_at, next_attempt_at)
```

If P0/P1 has `jobs/outbox_events` already, ALTER in place, do not recreate tables or generate conflicting migrations. Use actual P0-selected worker framework ADR (Dramatiq or RQ) for host runtime only if it can operate with Postgres-authoritative execution; if that framework *requires* Redis as queue truth, keep the library for future integrations but implement a tiny bounded Postgres poller for these durable domain jobs, recording the deviation/ADR. Avoid running two authoritative queues. Timestamp lease ownership must be DB-clock-based, not worker wall clock; all claims and terminal state updates should be guarded by ownership token/attempt or fencing token so expired workers cannot overwrite results of new owners.

**Payload control:** Registry of allowlisted `job_type` to pinned Pydantic schema version. MVP executable job kinds: `diagnostic.noop` in test/dev only and `account.audit_snapshot` that writes a sanitized idempotent audit marker (or another benign local DB-only domain action consistent with existing P1.4 model). Production must not allow an operator to enqueue arbitrary class/function names or run unrestricted shell/code. Cap payload bytes (e.g., 16 KiB), no credentials or raw contact data, structured redacted logs.

**Retries:** claim with `SELECT ... FOR UPDATE SKIP LOCKED` in small batches, bound concurrency per worker, explicit transient/permanent error classification, exponential backoff + bounded jitter, retries up to `max_attempts`, then `dead` with sanitized error class. Never retry permanent schema/policy failure. Reclaim timed-out leases with bounded policy and record observed attempt; do not mark dead on process restart without retry logic. Cancellation of unstarted jobs is optional narrowly scoped owner action; cancellation of running jobs is cooperative only and must not retroactively undo a committed effect.

**Outbox semantics:** Enqueue only after durable commit. Publisher claims undelivered outbox rows with lease; redis notification failure leaves event undispatched/retryable; `dispatched_at` is only a notification-delivered timestamp, not proof that job executed. If notification is disabled, either don't require it (mark event as no external sink with explicit internal dispatch status) or keep `dispatched_at` null and bound backlog visibility. Prefer a documented internal no-op sink in environments without Redis and still poll jobs independently. Test that two publishers don't create harmful duplication; downstream consumers must be idempotent.

## P1.5.3 Internal service APIs

```python
# All services accept a DB session / UnitOfWork and authenticated server context.
# They must NOT commit transactions internally.
enqueue_job(*, tx, actor, job_type: str, schema_version: int,
            payload: TypedJobPayload, idempotency_key: str,
            available_at: datetime | None = None) -> JobReceipt

record_outbox_event(*, tx, organization_id, aggregate_type, aggregate_id,
                    event_type, event_version, payload, idempotency_key) -> EventId

claim_due_jobs(*, worker_id, max_items: int, now_db: datetime) -> list[ClaimedJob]
complete_job(*, job_id, lease_token, result_digest) -> None
fail_job(*, job_id, lease_token, error_class, retryable) -> None
```

**Idempotency:** Repeat same `(org,job_type,key)` + identical canonical payload/version returns the same persisted job receipt; same key with different payload digest or schema version yields typed 409 conflict. Insert collision handling must survive concurrent transactions. A `job_runs` table is not necessary until observability needs it; store bounded attempt metadata in job columns and action audits. A job creates an outbox event exactly once for its initial logical enqueue (use stable key and uniqueness).

**One owner principle:** Distinguish *job owner* (worker lease) from *account operator* (business auth). Worker may run only registered safe handlers; actor context is validated on enqueue, not blindly inferred from an untrusted job payload. Workers must recheck policy when a sensitive future handler runs; no such handlers are in this phase.

## P1.5.4 Implementation work breakdown

- **P1.5.1 Review and ADR:** Inspect existing worker runtime, migrations, transaction unit-of-work, logs; record Postgres authority and outbox meaning; write `docs/contracts/job-outbox.md`.
- **P1.5.2 Migration & typed registry:** Add scoped tables/constraints, narrow handler map and versioned payload validators. Test migration upgrade/downgrade on disposable DB.
- **P1.5.3 Transactional enqueue:** Implement `enqueue_job` + `record_outbox_event` using caller transaction; ensure rollback removes both; concurrency collision is idempotent.
- **P1.5.4 Worker:** Bounded polling/claiming, lease expiration/reclaim, terminal updates with fencing/ownership validation, error taxonomy, retry/dead state, metrics + redacted trace.
- **P1.5.5 Outbox publisher/failure tests:** Optional Redis notification + DB polling fallback; test commit-crash, publish-failure, concurrent workers, lease expiry and replay; documentation/ledger. Stop.

## P1.5.5 Required acceptance matrix

| ID | Action / executed evidence | Required persisted outcome |
|---|---|---|
| **JOB-01** | Enqueue allowed DB-only job with domain update + outbox in transaction, COMMIT | Domain/job/outbox all committed with same org/trace/operation key |
| **JOB-02** | Inject transaction exception before commit | Domain/job/outbox all rolled back; no phantom receipt or dispatched event |
| **JOB-03** | Kill producer after commit before notification; restart worker | Worker finds unprocessed job by DB poll; job succeeds once logically |
| **JOB-04** | Disable Redis and notification dispatcher; run worker | DB polling completes due job despite Redis unavailability; no lost work |
| **JOB-05** | 2+ worker instances race for same due job | Exactly one active lease claim at a time, result/audit not duplicated |
| **JOB-06** | Repeat same idempotency key/payload, then reuse with different payload | Same receipt for exact replay; 409 collision for payload mismatch |
| **JOB-07** | Crash worker after local DB side effect but before acknowledgment, reclaim lease | Idempotent DB effect occurs once; stale worker cannot overwrite winner |
| **JOB-08** | Transient failure, then permanent failure; advance injected clock | Bounded exponential retry then `succeeded` or `dead`, sanitized error only |
| **JOB-09** | Duplicate/reordered outbox publisher attempts and timeout | Events never lost, deduped by event UUID/logical key; state accurately distinguishes notify vs process |
| **JOB-10** | Cross-org job inject/read, malicious/oversized payload, unsupported job type; run regressions | Fail closed; no external sends, no secret logs, P1.1–P1.4 tests still pass |

**Critical distinction:** `JOB-07` is only expected to demonstrate once-only *local transactional/idempotent DB effect*. Do not claim universal exactly-once effect for future WhatsApp, email or HTTP adapters. Test DB-lease clock behavior and a stale process attempting completion after lease takeover. Include observed queue backlog + dead job info in ops logs/metrics, avoiding raw payloads.

**Rollback:** Restore earlier worker image while leaving durable rows intact; old workers must not execute unknown job schema versions (fail closed, leave pending/dead review as designed). Data-bearing migration rollback requires backup/forward repair; no deleting pending work or wiping volumes. **STOP after P1.5: no real source adapters or active campaigns.**

---

# P2.1 — Rights-aware discovery SourceAdapter framework (fixture only)

**Outcome:** Hermecious can execute a bounded, **offline synthetic** discovery against a fixture adapter, validate typed school candidates and observations, record allowed provenance through the P1.2 source service, and produce an auditable usage report. No live website or directory access yet.

**Prerequisite:** P1.5 VERIFIED. **Executor role:** backend/data integration + contract testing. No requirement for new frontend page in this slice (P2.4 owns discovery UI).

## P2.1.1 Source interface and DTO contracts

Prefer a small `Protocol`/ABC with clear sync-or-async convention matching current FastAPI/worker runtime. These names represent behavioral contracts, adapt module names to the repo.

```python
class SourceAdapter(Protocol):
    @property
    def descriptor(self) -> SourceDescriptor: ...
    async def search(self, *, query: SourceQuery, limit: int,
                     cursor: str | None = None) -> SourcePage: ...
    async def fetch(self, *, source_key: str) -> SourceObservation: ...

class SourceQuery(BaseModel):
    city: str                # Lahore first; allow explicit filter
    vertical_slug: str       # school
    area: str | None         # neighbourhood/locality, not precise guessed coords
    keywords: list[str]      # bounded, sanitized, never a raw executable query

class SourceCandidate(BaseModel):
    provider: str
    external_key: str | None
    display_name: str
    city: str
    locality: str | None
    source_url: str | None     # present only if storage permitted
    observed_at: datetime
    claim_hints: list[str]    # unverified, never account_facts by themselves

class SourceObservation(BaseModel):
    provider: str
    external_key: str | None
    observed_at: datetime
    source_url: str | None
    permitted_storage_class: Literal['metadata_only','derived_only','full_allowed']
    rights_policy_version: str
    expires_at: datetime | None
    data: dict               # allowlist/restricted content as dictated by policy

class SourcePage(BaseModel):
    candidates: list[SourceCandidate]
    next_cursor: str | None
    reported_cost_units: int
```

**Important URI boundary:** The original blueprint's `fetch(url)` is an interface *intent*, not authorization for arbitrary egress. Prefer `fetch(source_key)` bound to registered provider-allowed observations to eliminate unconstrained SSRF; if adapters genuinely require `fetch(url)`, it MUST be validated against the registered provider's allowed host/path policy with DNS/redirect/IP enforcement. Record this interpretation as an ADR/contract clarification without weakening source access. No generic arbitrary URL fetch interface exposed to LLMs or operator requests.

**Descriptor contract** (versioned and operator-reviewed): `provider`, `adapter_version`, `terms_url`, `rights_policy_version`, `permitted_operations` (`search`, `fetch`, `store_metadata`, `store_derived`, `store_full`), `storage_class`, `retention_ttl`, `request_quota`, `result_limit`, `rate_limit`, `allowed_hostnames`, `requires_credentials`, `enabled`, `last_reviewed_at`, and `source_kind` (`fixture` for this phase). Default `enabled=false` unless fixture/test configured. Missing terms/review/rights policy disables the adapter (fail closed); for fixture tests use a synthetic fixture-policy identifier and a non-fetchable sample HTTPS URL such as `https://school.fixture.example/record/1` (or null when URLs are not allowed), never imply the policy applies to real providers. The policy identifier need not be a URL and must not be sent to a network client.

**Storage rights interpretation:** `metadata_only` permits only defined minimal identifiers/provenance (if explicitly licensed); `derived_only` permits only allowed extracted/derived facts (and minimum provenance if permitted), not original page or restricted text; `full_allowed` permits allowlisted captured content within TTL, not unlimited future use. Every actual source action must evaluate `permitted_operations` and retention/TTL. Do not store restricted raw text in Postgres, logs, error messages, Redis, fixture uploads or exception captures.

## P2.1.2 Budget, pagination and policy enforcement

- A `DiscoveryBudget` counts *calls*, *results*, *elapsed time*, and optional provider-defined cost units independently. Initial fixture limits: maximum 30 candidates, maximum 5 `search` pages, maximum 20 `fetch` calls, 60-second execution wall-clock timeout; make configurable lower, **never higher without policy**. Set budgets before any adapter invocation, including retries.
- Search clamps `limit` to the remaining **result and provider quota**; an adapter returning more records than requested is a contract violation, rejected or truncated deterministically and counted. No unbounded recursion or “next page until empty.”
- Cursor is opaque and provider-scoped; detect repeated cursor and repeated result key in one run. `next_cursor` must not embed credentials/PII in logs; log an irreversible cursor digest if needed.
- All adapters use source registry allowlist, validated descriptor policy, approved operations, and egress policy. Fixture adapter **never makes network requests**. Production network clients remain disabled/unimplemented until P2.2.
- Type-check and size-limit every source record; each persisted record needs a provider-scoped stable external key or a rights-permitted stable source identity (otherwise reject); reject malformed/deceptive provider responses; source timestamps timezone-aware. `source_url` if present is a URL *for a source*, not assumed contact consent or proof of the claimed business need.
- Candidate city/school vertical are validated against query and no invented contact details. Reject unsupported city/vertical fixture query rather than returning fabricated nearby accounts.

## P2.1.3 Integration with P1.2 and P1.5

1. Register exactly one synthetic `fixture_lahore_schools` descriptor and versioned fixture dataset, e.g., `fixtures/sources/lahore_schools_v1.json`. It contains 6–10 fictional accounts with duplicate names, mixed localities, missing URLs, stale observations, restricted storage classifications, pagination and a malicious-instruction string. No real school contact/phone/email data.
2. Through an internal **developer/test-only** service or CLI, start a bounded fixture run with explicit query/budget, optionally using P1.5 registered safe job type `discovery.fixture_preview` when P1.5 job registry supports opt-in. If adding a job type, register typed payload version and idempotency; production should not expose it as a public generic enqueue endpoint.
3. Persist only allowed source provenance via P1.2 `add_source_record` after validating policy and TTL, using actor's org. If provider rights permit no record at all, store **only operational aggregate counters** without source identifiers, or reject that item; never bypass P1.2 constraints to "make the demo pass".
4. Return a `DiscoveryFixtureReport`: `run_id`, query/area, adapter id/version, rights policy version, examined_count, accepted_count, rejected_count, budget_consumed, rejection reason codes, candidate previews with explicit `unverified` labels and only rights-allowed source metadata. Tests assert log redaction and DB records match policy. `run_id` can be an ephemeral correlation UUID; **P2.4** owns durable discovery-run management UI/schema. Do not create campaigns or business contacts.
5. **Do not create or merge accounts automatically in P2.1.** P2.2 will enable real permitted source input; P2.3 owns identity deduplication; P2.4 owns review UI. The fixture integration tests can explicitly create synthetic accounts via P1.4 after showing source evidence, but framework must not assert identity based only on display name.

## P2.1.4 Implementation work breakdown

- **P2.1.1 Contract/tests first:** Inspect source services, existing worker APIs and precise rights policy. Define DTO versions, descriptor registry and bad-input fixtures.
- **P2.1.2 Adapter registry:** Implement allowlisted provider descriptor + explicit enabled/rights review enforcement; fixture adapter and offline-only guard. No real HTTP adapter.
- **P2.1.3 Budget runner:** Build bounded search + optional fetch, cursor protection, schema validation, usage counters and safe reject reasons.
- **P2.1.4 Provenance integration:** Connect allowed observations to P1.2 `source_records`; rejected rights leave no restricted content; optional safe typed P1.5 job only for fixture run.
- **P2.1.5 Verification and handoff:** Run fixtures, inspect rows/logs/restart behavior, document source contract for P2.2 (`docs/contracts/source-adapters.md`) and run ledger. Stop.

## P2.1.5 Required acceptance matrix

| ID | Action / executed evidence | Required result |
|---|---|---|
| **SOURCE-01** | Run fixture search for Lahore/school with valid approved descriptor | Typed paginated candidates + report; no network calls; expected fixture count |
| **SOURCE-02** | Fetch valid fixture observation by allowed `source_key` | Observation typed, provenance+rights version recorded where permitted |
| **SOURCE-03** | Unknown/disabled/missing-terms descriptor, operation not licensed | Policy rejection before invoking adapter or storing content |
| **SOURCE-04** | `metadata_only`/`derived_only`/`full_allowed` fixture observations | Each retains only explicitly allowed content with TTL; no raw restricted leakage |
| **SOURCE-05** | 31+ candidates, repeated cursor, repeated source keys, oversized page | Bounded/rejected deterministic output; no infinite pagination |
| **SOURCE-06** | Wrong city/vertical, missing id, malformed URL, naive timestamp, invalid JSON/schema | Quarantined/rejected with safe typed errors; no phantom accounts |
| **SOURCE-07** | Budget reaches page/fetch/time/cost cap, transient fixture 429/timeout | No over-budget retry; bounded stop and truthful partial report with reason |
| **SOURCE-08** | External/private/loopback URL, unapproved host, redirect pattern, prompt injection data | No outbound network; data treated as data; unsafe URL rejected |
| **SOURCE-09** | Two organizations run identical fixtures with same keys; replay fixture safe job | Provenance scoped correctly, no cross-org read or duplicate stored source key |
| **SOURCE-10** | Full prior regression, DB inspection, log scan, restart and fixture replay | No production source fetching, no contacts or campaigns created, deterministic results |

**Critical acceptance subtlety:** A fixture provides no proof that any **real** school exists or is a qualified lead. Labels must say synthetic; externally reachable lead discovery begins at **P2.2** with explicit rights review. A fixture adapter may represent invalid/expired source-policy cases for negative tests, but the normal accepted fixture must be configured with internally authored data and explicit synthetic license policy.

**Rollback:** Disable fixture provider via registry flag/config (fail closed), revert adapter code while preserving permitted source metadata. If a new durable fixture-job type exists, old workers must not treat it as arbitrary work. No DB table required unless existing P1.2 needs a narrowly justified policy field; migrations rehearsed against disposable DB. **STOP after P2.1: no live sources, scraping, browser bots, deduplication, outreach or AI research.**

---

## 4. Integration sequence and regression gate

| Stage | Demonstration required | Persistent proof |
|---|---|---|
| P1.4 | Operator manually creates fake Lahore school; corrected sourced fact visible | `accounts`, `account_facts`, source link + audit/history after restart |
| P1.5 | Business state + durable safe job; producer/worker crash and Redis down | `jobs`, `outbox_events`, single logical DB effect, retries and trace logs |
| P2.1 | Offline Lahore school fixture produces bounded records and provenance | Only rights-approved `source_records` and safe run report; no real contacts |

### 4.1 Security and correctness review checklist

- [ ] Current verified P0–P1 prerequisites confirmed (actual ledger evidence).
- [ ] All API write auth+CSRF+role+org guards verified; foreign key cross-org checks tested.
- [ ] Corrections are append-only/audited; no source claim overwritten silently.
- [ ] Pagination stable, bounded, filter and org scoped; source URLs never fetched via admin UI.
- [ ] Jobs and outbox committed atomically; Postgres is durable authority; job types and payload versions allowlisted.
- [ ] Retry cap, lease fencing, failed/expired worker behavior and payload redaction verified.
- [ ] Source rights registry and source TTL default deny; fixture network egress disabled.
- [ ] Test fixture is purely synthetic and contains no sensitive real-world data.
- [ ] Unit + contract + integration + UI or worker E2E negative paths executed as applicable.
- [ ] `EXECUTION_LEDGER.md` includes command, exit code, observed evidence, status and rollback.

### 4.2 Required Opus completion report (per subphase)

```text
SUBPHASE / base SHA / resulting SHA:
DEPENDENCIES: phase ID | ledger proof | verified/blocked
DESIGN DECISIONS: accepted ADRs or newly proposed deviations
CHANGED FILES: path | purpose | requirement ID
GATES: ID | exact command / test | exit code | observed state | PASS/FAIL/BLOCKED/NOT-RUN
NEGATIVE PATHS: fault injection | expected state | observed state
SECURITY: org/role/CSRF, secret redaction, source rights, job policy (as relevant)
MIGRATIONS: upgrade/downgrade on disposable DB; live data strategy
ROLLBACK / FORWARD REPAIR:
EXECUTION_LEDGER.md entry:
VERDICT: VERIFIED / PARTIALLY VERIFIED / BLOCKED
STOP CONFIRMATION: following subphase not attempted
```

### 4.3 Explicit non-goals for this batch

Not building real Lahore leads, Google Maps scraping, SearXNG crawling, WhatsApp send/receive, contacts or consent flows, campaigns, qualitative scoring, RAG, model routing, multi-agent systems, autonomous action selection or customer SaaS tenancy UI. This batch is deliberately the operational substrate on which real prospect discovery and outbound policy checks will later depend.

### 4.4 Ready for next batch

**Batch 04:** P2.2 (one approved real source or user-supplied seed list), P2.3 (non-destructive account dedup), P2.4 (reviewable discovery-run UI). Those phases may consume *only* the validated P2.1 source adapter shape and must not bypass policy, provenance or budgets.
