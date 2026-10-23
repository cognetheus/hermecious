# HERMECIOUS — Batch 02: P1.1–P1.3

**Status:** Implementation specification, NOT implemented or tested.  
**Executor:** Claude Opus 5.5 High, exactly ONE subphase per run.  
**Parent:** `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` (v1.0); accepted ADRs and repository code are authoritative for implementation details.  
**Market:** Lahore, Pakistan; initial vertical independently operated schools.  
**Dependency chain:** `P0.1 → P0.2 → P0.3 → P0.4 → P1.1 → P1.2 → P1.3`.  
**Next after this batch:** P1.4 (accounts CRUD + evidence UI), NOT included here.

## 0. Engineering contract and dependency resolution

### 0.1 Scope and non-goals

This batch establishes (1) secure, persistent operator identity and authorization; (2) a traceable, rights-aware core sales data model; and (3) a versioned catalog of sales-ready offers that cannot silently promote proposed features into approved product claims.

Out of scope: real source scraping, a Lahore school lead collection run, account CRUD UI (P1.4), job/outbox (P1.5), autonomous agents, campaigns, WhatsApp, vector DB, multi-tenant signup, payments, customer/parent/student records, unrestricted outbound communications. No code may send a message or fetch third-party business content in this batch.

### 0.2 Critical sequencing correction — authorization needs data

The master blueprint names organizations in P1.2 but authentication in P1.1. **Resolve this without disposable/in-memory auth**:

- **P1.1 owns initial migrations for:** `organizations`, `users`, `auth_sessions` and the first owner bootstrap operation. This is the minimum durable identity substrate. P1.1 also defines role checks and server-owned authentication.
- **P1.2 reuses these exact tables and adds:** `verticals`, `areas` (minimal reference schema), `accounts`, `source_records`, `account_aliases`, `account_facts`. Do NOT re-create organizations or users; do NOT replatform sessions.
- **P1.3 owns:** `offers`, `offer_revisions` (or an equivalently immutable/versioned design). Do not create campaign or messaging tables.

This is a **documented sequencing clarification**, not permission to change unrelated blueprint requirements. Add a short ADR/decision-log entry explaining the correction. If P0 code/ADRs already define equivalent entities, reconcile with existing schema and avoid duplication.

### 0.3 Repository conventions — adopt actual P0 outcomes

Before each subphase inspect `AGENTS.md`/`CLAUDE.md`, `.env.example`, the actual API mount, existing router style, DB models/migrations, P0.4 error envelope and request ID naming, P0.3 fixture/CI harness, lockfiles and Compose service names. Suggested paths below are **targets**, not proof the repo contains them. Never create a second settings module, alternate ORM base, parallel migration tree, second password/session framework, or second error format.

The master blueprint suggests `/api/v1`, UUID IDs, timezone-aware UTC data, business timezone `Asia/Karachi`, SQLAlchemy 2, Alembic, typed errors, PostgreSQL as system of record. **Follow the actual accepted P0.4 response envelope**, currently illustrated in Batch 01 as `{"error":{"code":"...","message":"...","request_id":"...","retryable":false}}`; don't silently substitute the blueprint's older top-level error example.

### 0.4 Shared invariants

1. Postgres, not Redis or browser local storage, owns authoritative user, account, source, fact and offer records.
2. The API enforces authentication and authorization. A Next.js route/page guard is UX only and NEVER substitutes for backend enforcement.
3. Every organization-owned row is scoped by `organization_id`; cross-organization references and unauthorized reads are rejected, even if only one organization is active initially.
4. Secrets, session tokens, passwords, raw contacts, sensitive source payloads and user-supplied data must not appear in logs, error bodies or the build output.
5. Published offer claims must be from an owner-reviewed snapshot with substantiating evidence. An aspirational capability is never a sellable claim.
6. All schema changes via Alembic; migration and rollback evidence uses a disposable database, with backup/forward-repair guidance for non-disposable data.
7. Source-licensing limitations apply to any saved business data. Public access does NOT establish permission to store, reuse, enrich or contact.
8. Every claimed pass in `EXECUTION_LEDGER.md` must include executed command/test and observed result. `BLOCKED` and `NOT RUN` are honest statuses.
9. No subphase runs the next automatically. Each run ends with its own completed/blocked report.

### 0.5 Gate and evidence matrix

| Subphase | Prerequisites | Concrete output | Must-prove gate |
|---|---|---|---|
| P1.1 | P0.1–P0.4 VERIFIED | Owner bootstrap, persistent sessions, protected API/UI, RBAC, CSRF protections | Forged, invalidated, expired and unauthorized sessions fail closed; restarts retain valid sessions until expiration |
| P1.2 | P1.1 VERIFIED | Core account/source/fact schema, revisions/constraints, migrations, fixture repository | Valid facts have attributable allowed sources; cross-org links/duplicates/invalid state fail in DB or service; reversible disposable migrations |
| P1.3 | P1.2 VERIFIED | Versioned offer catalog and approved capabilities, API/operator review flow | Unsupported/unapproved/expired feature claims cannot appear in a sales-ready offer; published snapshots cannot be silently mutated |

---

# P1.1 — Persistent authentication, sessions and authorization

**Purpose:** A single-owner private product that can be safely extended to owner/operator/observer without building a consumer identity platform.

**P1.1 prerequisites:** P0.4 VERIFIED and stable P0 database + error handling. Stop on unresolved architectural conflicts or missing migrations. Do not invent test results.

## P1.1.1 Domain and persisted schema

Minimum SQLAlchemy 2 + Alembic schema (use repo naming conventions):

```text
organizations
  id UUID PK
  name VARCHAR(200) NOT NULL
  timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Karachi'
  status VARCHAR CHECK IN ('active','suspended') NOT NULL
  created_at TIMESTAMPTZ NOT NULL

users
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  email_canonical VARCHAR(320) NOT NULL
  display_name VARCHAR(160) NULL
  password_hash TEXT NOT NULL
  role VARCHAR CHECK IN ('owner','operator','observer') NOT NULL
  active BOOLEAN NOT NULL DEFAULT TRUE
  credentials_changed_at TIMESTAMPTZ NULL
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  UNIQUE(organization_id, email_canonical)

auth_sessions
  id UUID PK -- lookup ID, not proof of login by itself
  user_id UUID NOT NULL FK users(id) ON DELETE CASCADE
  verifier_hash CHAR(64) NOT NULL -- SHA-256 of CSPRNG verifier, never verifier
  issued_at TIMESTAMPTZ NOT NULL
  last_seen_at TIMESTAMPTZ NULL
  idle_expires_at TIMESTAMPTZ NOT NULL
  absolute_expires_at TIMESTAMPTZ NOT NULL
  revoked_at TIMESTAMPTZ NULL
  created_request_id VARCHAR NULL
  indexes on user_id, absolute_expires_at
```

**Important:** `auth_sessions` uses `session_id.verifier` (or an equivalent reviewed server-session implementation); cookie contains an opaque identifier plus high-entropy verifier, DB stores only verifier **hash**, compare in constant time. A randomly generated opaque token + hashed lookup is also acceptable if supported by the current architecture; make the chosen scheme explicit in ADR. At least 128-bit entropy for the secret, ideally >=160-bit. No signed role claims trusted from a client, no JWT/localStorage MVP, no session data in Redis as sole authority.

Owner bootstrap must create only one named initial organization and its owner and must require interactive password input (no hardcoded/sample password, CLI flag containing password, or default seed credential). Must refuse to overwrite an existing owner and work via safe DB transaction. Use password `Argon2id` with secure per-hash salt and benchmarked settings (start at OWASP minimum m=19 MiB, t=2, p=1 or stronger if VPS allows). Do not log email/password/hash. No public registration, invitation, password reset, user-management UI or OAuth in this task.

## P1.1.2 Session lifecycle and login endpoints

Versioned endpoints with final actual route shape following P0:

| Method and path | Auth | Semantics |
|---|---|---|
| `POST /api/v1/auth/login` | anonymous + rate limited | Validate normalized email/password; issue **new** session cookie and CSRF value; same response for unknown account/bad password/disabled user (except rate-limit status) |
| `GET /api/v1/auth/me` | required | Return safe user summary `{id,display_name,email,role,organization_id}`; never hash/token |
| `POST /api/v1/auth/logout` | required | Require CSRF, revoke server session and clear cookie; replay safe |
| `GET /api/v1/auth/csrf` | session required | Issue/refresh session-bound CSRF value for authenticated unsafe requests; never grant authentication |
| `GET /api/v1/auth/session-status` | optional, only if actually needed | Avoid duplicating `/me`; if omitted document intentional omission |

**Cookie and transport:** Production cookie with host-only prefix `__Host-hermecious_session`, `Secure`, `HttpOnly`, `Path=/`, `SameSite=Lax` (or Strict with documented usability impact), no `Domain`; HTTPS across entire operator session. Local HTTP on loopback may use a separately named `hermecious_dev_session` with explicit dev-only insecure mode; production startup rejects insecure cookie or broad CORS settings. Use an established, same-origin browser-to-API arrangement via configured Next rewrites/reverse proxy where needed. Avoid wildcard credentialed CORS. Do not trust proxy headers unless forwarded by explicitly trusted proxy infrastructure.

**Session behavior:** session rotation on login and privilege/credential change; server-enforced idle and absolute timeout (recommend initial 8h idle, 24h absolute, adjust via validated config); logout/revocation immediately effective; inactive or suspended org/users blocked; rotate CSRF on newly authenticated session; no privileged caching in a shared/browser public cache. Bound `last_seen_at` updates to avoid a write on every request. Expiration is compared using UTC-aware time. Store `Cache-Control: no-store` on sensitive auth responses.

## P1.1.3 CSRF, origin and authorization

- For cookie-authenticated unsafe methods (`POST/PUT/PATCH/DELETE`), require session-bound CSRF proof (header such as `X-CSRF-Token`) AND validate same-origin `Origin`/`Referer` in a documented fail-closed way; define compatible behavior for legitimate same-origin requests with stripped headers. Enforce `Content-Type` expectations where applicable. `SameSite` alone is not sufficient.
- Apply CSRF to logout and privileged mutations; ensure login also has a concrete login-CSRF mitigation (strict allowed-origin validation plus appropriate pre-auth challenge/origin policy). Authentication webhooks in future must use separate provider verification, not cookie auth.
- Protect all private `/api/v1/*` business routes by default (explicit allowlist for health, login and any genuinely public endpoints); auth guard on `apps/web` private screens, with server route authorization still authoritative.
- Define `get_current_user`, `require_roles(...)`/capability predicates without client-supplied org or role trust. Role contract: `owner` can bootstrap/administer/publish; `operator` may view/work accounts and create draft offers but not publish; `observer` read-only. Until role-specific endpoints exist, enforce owner-only access for mutations unless explicitly specified. Never ship an anonymous admin endpoint.
- Rate-limit repeated bad login attempts with bounded windows and no account enumeration; do not allow a Redis outage to produce unlimited authentication attempts without mitigation. Document exact failure mode and run an integration test.

## P1.1.4 Implementation tasks and suggested code regions

1. Inventory current API mounts, existing login/session libs, migrations, middleware, Next proxy strategy and error schema.
2. Write failing tests for protected routes, anonymous rejection, role denial, password verification, login-CSRF, session tampering/expiration and logout.
3. Add migrations/models for `organizations`, `users`, `auth_sessions` with FK/index/uniqueness and migration smoke.
4. Implement password service, token/session repository, policy dependencies, CSRF/origin verifier and bounded login rate limiting.
5. Build owner bootstrap CLI without any default or exposed password.
6. Add `/login` UI and minimal authenticated landing/protected routing, without account/offers pages or unrelated design work.
7. Extend P0.4 safe logging with event names/counts only (`auth.login_denied`, `auth.logout`, `auth.session_revoked`), never credentials/contact data.
8. Document initial account creation, dev loopback and production cookie/HTTPS mode in `docs/runbooks/auth.md`; update ADR/ledger.

Suggested existing paths to adapt: `apps/api/app/auth/{models,repository,service,dependencies,security,routes}.py`, `apps/api/app/persistence/*`, `apps/api/alembic/versions/*`, `apps/web/app/login/*`, `apps/web/middleware*` only if compatible with installed Next version, `tests/{unit,integration,contracts}/auth_*`.

## P1.1.5 Contract fixtures and acceptance tests

| ID | Test/evidence | Required result |
|---|---|---|
| AUTH-01 | Disposable DB migrate, run bootstrap, attempt bootstrap again | One active organization/owner; duplicate bootstrap rejected, no default credentials |
| AUTH-02 | Wrong password / nonexistent email / disabled user | Uniform safe denial, no enumeration or secret leakage; bounded rate limit works |
| AUTH-03 | Successful login and `/me` | Opaque HttpOnly cookie, safe user response, no token stored in browser localStorage |
| AUTH-04 | Cookie tamper, unknown ID, known ID with wrong verifier, expired session | `401`, session not silently created or prolonged |
| AUTH-05 | Logout then replay old cookie; revoke/disable owner then request | `401` after revocation; no stateless token bypass |
| AUTH-06 | Wrong/missing CSRF token + cross-origin request on mutation/logout | `403` safe envelope; no DB mutation; SameSite alone not used as proof |
| AUTH-07 | Owner/operator/observer fixture exercising authorization | Read/mutate/publish capability checks deny lower roles; no user-supplied org escalation |
| AUTH-08 | Restart API/Redis while persisted session still valid; exceed idle/absolute limit | Session continues only until server expiry; Redis outage behavior bounded/observed |
| AUTH-09 | Production config with insecure cookies/HTTP or wildcard credentialed origins | Startup/config validation rejects unsafe combination |
| AUTH-10 | P0 smoke, lint, type, unit/integration migration suite | Existing required checks still pass; record exact commands and exit codes |

**Failure simulations:** parallel logins, simultaneous logout/request, session fixation, clock-edge expiry, CSRF token replay after session rotation, log-injection strings, malformed cookie, DB transient outage, Redis limit-store outage. A test that asserts only HTTP status without verifying mutation absence is insufficient for CSRF and authorization.

**Rollback:** Auth migration downgrade on disposable DB; production rollback requires reviewing live sessions/users and backup/forward fix (do not blindly delete them). Application revert must fail closed for private routes; no reverting to anonymous access. Do not drop volumes.

**P1.1 STOP:** Complete ledger with `AUTH-*` evidence and terminate; P1.2 is separate.

---

# P1.2 — Core account, source, provenance and facts database

**Purpose:** Establish the minimum trustworthy data substrate for Lahore account research, while staying source-rights-aware and organization-scoped. This is schema and repository functionality, **not** the Accounts UI (P1.4) or real-source fetcher (P2).

**Prerequisite:** P1.1 VERIFIED. Use exactly its `organizations` and auth scoping. If code is not available, do not manufacture evidence.

## P1.2.1 Domain migrations

Proposed schema, using UUID PKs, UTC `TIMESTAMPTZ`, normalized slugs/enums/checks and DB-enforced key constraints:

```text
verticals
  id UUID PK
  slug VARCHAR(80) UNIQUE NOT NULL  # `schools` first
  name VARCHAR(160) NOT NULL
  qualifier_config_version VARCHAR(80) NOT NULL DEFAULT 'unconfigured'
  status VARCHAR CHECK ('active','inactive')

areas
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  city VARCHAR(120) NOT NULL  # Lahore
  district_name VARCHAR(160) NULL
  source_query VARCHAR(400) NULL
  timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Karachi'
  created_at TIMESTAMPTZ NOT NULL
  UNIQUE(organization_id, city, district_name) [design around nullable semantics]

accounts
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  vertical_id UUID NOT NULL FK verticals(id)
  canonical_name VARCHAR(250) NOT NULL
  normalized_name VARCHAR(250) NOT NULL
  city VARCHAR(120) NOT NULL
  locality VARCHAR(160) NULL
  status VARCHAR CHECK ('discovered','researching','assessed','shortlisted','investigate','nurture','excluded') NOT NULL
  discovered_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  version INTEGER NOT NULL DEFAULT 1
  UNIQUE(organization_id,id)  # composite FK target for scoped children
  indexes (organization_id, vertical_id, city, status)

source_records
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  provider VARCHAR(100) NOT NULL
  external_key VARCHAR(300) NULL
  source_url TEXT NOT NULL  # sanitized/rights-permitted; no credentials or secret params
  observed_at TIMESTAMPTZ NOT NULL
  permitted_storage_class VARCHAR CHECK ('metadata_only','derived_only','full_allowed') NOT NULL
  source_payload_reference TEXT NULL
  rights_policy_version VARCHAR(80) NOT NULL
  expires_at TIMESTAMPTZ NULL
  UNIQUE(organization_id,id)
  unique (organization_id, provider, external_key) WHERE external_key IS NOT NULL
  CHECK payload ref only when rights allow; other policy checks in service

account_aliases
  id UUID PK
  organization_id UUID NOT NULL
  account_id UUID NOT NULL
  normalized_name VARCHAR(250) NOT NULL
  source_record_id UUID NULL
  created_at TIMESTAMPTZ NOT NULL
  composite FK (organization_id,account_id) -> accounts
  composite FK (organization_id,source_record_id) -> source_records when not null
  UNIQUE(organization_id,account_id,normalized_name)

account_facts
  id UUID PK
  organization_id UUID NOT NULL
  account_id UUID NOT NULL
  claim_type VARCHAR(100) NOT NULL
  typed_value_json JSONB NOT NULL
  confidence_label VARCHAR CHECK ('strong','moderate','weak','unknown') NOT NULL
  verification_status VARCHAR CHECK ('source_supported','hypothesis','disputed','rejected') NOT NULL
  source_record_id UUID NULL
  evidence_excerpt TEXT NULL  # excerpt rights and length gate, e.g., <= 1000 chars
  observed_at TIMESTAMPTZ NOT NULL
  expires_at TIMESTAMPTZ NULL
  created_at TIMESTAMPTZ NOT NULL
  composite FK (organization_id,account_id) -> accounts
  composite FK (organization_id,source_record_id) -> source_records when not null
  CHECK source_record_id required for source_supported
  indexes (organization_id,account_id,claim_type,observed_at)
```

**Important reconciliation points:** Adopt `accounts` from blueprint. No unconditional unique constraint on normalized school name: two separate schools can share a name and two campuses of a chain can be distinct accounts (P2.3 resolves identity later). Enforce exact duplicates only for stable source keys, and keep fuzzy matching as non-destructive suggestions. Avoid an unconditional area unique constraint on nullable district; choose normalized key or a documented partial index. `source_records` with `metadata_only` may only store permitted metadata; `full_allowed` must not mean automatically permitted to contact. If source rights forbid even a URL/source record, reject ingestion rather than storing it.

**Cross-org protection:** At minimum, use composite `(organization_id,id)` FK targets for facts/aliases and scoped repository queries. Do not rely solely on an ORM filter; integration test raw inserts that try linking org A facts to org B accounts/sources. For a single-org MVP, PostgreSQL RLS is not required unless already part of accepted ADR; revisit before actual SaaS expansion.

## P1.2.2 Domain services and data contracts

Minimum typed repository/application methods (names adapt to repo conventions):

```python
create_account(*, actor, organization_id, vertical_id, name, city, locality=None) -> Account
add_source_record(*, actor, organization_id, provider, source_url,
                  observed_at, storage_class, rights_policy_version,
                  external_key=None, payload_reference=None,
                  expires_at=None) -> SourceRecord
add_account_fact(*, actor, account_id, source_record_id=None, claim_type,
                 typed_value, confidence_label, verification_status,
                 observed_at, expires_at=None, evidence_excerpt=None) -> AccountFact
get_account_with_evidence(*, actor, account_id) -> AccountEvidence
```

**Rules:** `actor.organization_id` dictates org scope; never accept an unchecked organization_id from web request. `source_supported` needs permitted source and `observed_at`; reject expired or rights-restricted evidence for new factual assertions. `hypothesis` can have no source but is visibly different from a supported fact. Keep `unknown` as unknown, don't silently convert absence into a negative claim. Sanitized `source_url` validation: absolute HTTPS preferred, HTTP only where policy permits; no userinfo, local/private/metadata-service hosts, fragments or secret-containing query params. This is an ingestion-level validation baseline; outbound network/SSRF protection will be implemented at P2.1 and P11.1, not faked in P1.2.

`confidence_label` describes evidence quality, not an invented likelihood to buy. Typed fact values follow a small allowlisted claim registry with per-claim Pydantic validators (e.g., campus_count >=1 when known; ownership/decision_authority are explicitly unknown until supported; public_workflow_signal with bounded text). Unknown claim types may be quarantined/rejected, not blindly stored as arbitrary sales facts. Validate excerpt licensing and byte length.

Only *minimal* service/repository and fixture routes used for contract tests. Public account APIs, filters, pagination, evidence UI and manual operator editing are **P1.4**, not P1.2. If a test harness needs a route, use authenticated test-only route compiled out of production or invoke application services directly; do not sneak in unfinished customer API.

## P1.2.3 Tasks

1. Inspect P1.1 schema/base, test fixtures and accepted auth scoping.
2. Write migrations in a single Alembic revision or deliberately ordered minimal revisions; no autogenerate applied blindly.
3. Implement typed models with constraints, composite FKs, indices, optimistic version field on accounts.
4. Add source rights policy classification and a narrow typed fact registry; enforce service-level source/expiry/permission rules.
5. Add repositories that accept authenticated actor context; no cross-org reads or writes.
6. Create **synthetic** Lahore-like school fixtures and factory helpers; no real school contact/person data.
7. Add migration upgrade/downgrade and integration tests, failure simulations, and dependency audit.
8. Update technical schema documentation (`docs/contracts/core-domain.md`), ADR if changed, and ledger.

## P1.2.4 Acceptance gates

| ID | Test/evidence | Required result |
|---|---|---|
| DATA-01 | Migrate empty disposable DB to head, repeat upgrade | Repeatable no-op second upgrade; all expected tables, keys and indices present |
| DATA-02 | Downgrade P1.2 on disposable populated fixtures then re-upgrade | P1.1 users/sessions preserved; clean migration path or explicitly safe forward-repair strategy |
| DATA-03 | Create Lahore school account and permitted source-supported fact | Fact joins to valid account, source, rights classification, observation time |
| DATA-04 | Fact with `source_supported` but no source ID | DB/service rejects; no incomplete fact persists |
| DATA-05 | Cross-org raw insert for account facts/source references and repository read | FK rejects mismatched org; scoped API/repo returns no leakage |
| DATA-06 | Duplicate stable provider external key and exact alias reinsert | No duplicate source or alias; uniqueness conflict handled safely, no 500 leakage |
| DATA-07 | Two different schools or campuses sharing normalized names | Both allowed; never auto-merged due only to name |
| DATA-08 | Forbidden storage rights, expired source, private/metadata URL, excessively long excerpt | Ingestion rejected or quarantined according to documented policy; nothing illicit persisted |
| DATA-09 | Hypothesis vs supported fact, uncertain campus count/ERP status, negative/invalid typed value | No unsupported fact marked verified, invalid values rejected; uncertainty preserved |
| DATA-10 | P0/P1.1 regression, migration/schema lint and fixtures | CI-equivalent checks executed with status; no anonymous data read routes exposed |

**Additional failure paths:** interrupted migration, transient DB loss, nested transaction rollback, concurrent inserts, malicious Unicode strings, incorrect timestamp offset, source record expiration after a fact was created. Querying a now-stale fact must not present it as fresh; full re-verification UX later in P1.4/P3.

**Rollback:** Use ephemeral DB to demonstrate migration reverse while preserving P1.1 objects. For production-like data-bearing environments, take backup and prefer reviewed forward repair; never blindly drop fact/source tables to restore code. No `docker compose down -v`.

**P1.2 STOP:** No account UI, actual web adapter or lead discovery before review.

---

# P1.3 — Versioned offers and approved capability claims

**Purpose:** Hermecious must know what your actual products can do, what is planned, and which statements you authorize for sales. A sales draft must not turn a brainstorm into a promise.

**Prerequisite:** P1.2 VERIFIED. Reuse role guards, org scoping, P0.4 error semantics and migration harness.

## P1.3.1 Minimum model

Recommended lean relational + JSONB design, rather than a generic CMS or vector store:

```text
offers
  id UUID PK
  organization_id UUID NOT NULL FK organizations(id)
  vertical_id UUID NOT NULL FK verticals(id)
  code VARCHAR(100) NOT NULL
  audience VARCHAR(200) NOT NULL
  current_draft_revision_id UUID NULL  [set through reviewed migration if circular]
  published_revision_id UUID NULL
  status VARCHAR CHECK ('draft','published','archived') NOT NULL
  version INTEGER NOT NULL DEFAULT 1  # optimistic concurrency
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  UNIQUE(organization_id, code)
  UNIQUE(organization_id,id)

offer_revisions
  id UUID PK
  organization_id UUID NOT NULL
  offer_id UUID NOT NULL
  revision INTEGER NOT NULL
  state VARCHAR CHECK ('draft','published','retired') NOT NULL
  capability_version VARCHAR(80) NOT NULL
  approved_claims_json JSONB NOT NULL  # schema-validated, sales-ready claims only
  capability_matrix_json JSONB NOT NULL # includes planned/unverified and supported
  price_rules_json JSONB NOT NULL
  exclusions_json JSONB NOT NULL
  dependencies_json JSONB NOT NULL
  evidence_references_json JSONB NOT NULL
  created_by UUID NOT NULL (scoped user FK)
  approved_by UUID NULL (scoped user FK)
  approved_at TIMESTAMPTZ NULL
  published_at TIMESTAMPTZ NULL
  content_sha256 CHAR(64) NOT NULL
  created_at TIMESTAMPTZ NOT NULL
  UNIQUE(organization_id,offer_id,revision)
  composite FK (organization_id,offer_id) -> offers
```

An equivalent simpler design is allowed if it **proves immutable published snapshots** and stable lookups, avoids schema rewrites in P4/P6, and is documented in an ADR. Draft edits make a **new revision**, never mutate a published revision. If P0/other accepted code already has an offer schema, adapt it rather than duplicate tables.

**Capability claim object** (validate with Pydantic, not arbitrary strings):

```json
{
  "capability_code": "fee_tracking",
  "summary": "Tracks school fee payments",
  "readiness": "available",
  "approved_for_sales": true,
  "evidence_refs": ["internal-demo:fees-2026-10"],
  "limitations": ["Manual import only"],
  "approval_note": "Demoed against reviewed build"
}
```

Readiness enum: `available`, `limited`, `planned`, `unverified`, `not_supported`. **Only** `available` or properly constrained `limited` claims with nonempty substantiation, owner sign-off and explicit limitations may enter `approved_claims_json`. Planned/unverified/not-supported may appear in the internal capability matrix but never in the sales-ready claims response. Price rules must be explicit, reviewed and versioned; **absence means `pricing_unavailable`, not "$X"**. Similarly, delivery dates, integrations, migration guarantees and SLA may not be invented.

Represent evidence as permitted stable internal references (demo/repo/release note/owner review) with a type and timestamp; plain URLs alone are not proof of actual availability. Start with manual owner attestation and evidence reference, no automated product-code inspection required in P1.3. No personally identifying student/customer data in proof materials.

## P1.3.2 Offer publication workflow and APIs

Endpoints (adjust method naming to repository conventions, but maintain HTTP semantics):

| Method/path | Permission | Purpose |
|---|---|---|
| `POST /api/v1/offers` | owner/operator | Create draft offer (school vertical), return safe summary |
| `GET /api/v1/offers` | authenticated | List scoped offer summaries with current status/revision |
| `GET /api/v1/offers/{id}` | authenticated | Read draft and published revisions according to role, no cross-org lookup |
| `POST /api/v1/offers/{id}/revisions` | owner/operator | Validate/create a **new** draft revision; require `expected_version` |
| `POST /api/v1/offers/{id}/publish` | owner only + CSRF | Publish the selected reviewed revision if all claims have substantiation and allowed readiness; atomic version check |
| `POST /api/v1/offers/{id}/archive` | owner only + CSRF | Archive future selling, preserve history/audit |
| `GET /api/v1/offers/{id}/sales-ready` | authenticated internal/operator | **Only** published snapshot/approved claims; absent/revoked offer returns documented domain denial |

Public/AI caller must use the dedicated `sales-ready` service/response, **never** raw draft capability matrix. The P4 outreach generator must eventually consume only the published revision ID and content digest, and must invalidate pending drafts when that revision is archived or superseded; documenting that future integration contract is in scope, implementing the generator is not.

**Concurrency:** optimistic compare-and-swap on `offers.version` and selected revision number; two simultaneous publishers must not produce mismatched `published_revision_id`. Publication transaction writes reviewer + timestamp, immutable digest and status together. Archive never destroys a published snapshot; it makes it no longer selectable for new sends.

## P1.3.3 Human operator experience

Keep UI minimal: authenticated offers list, draft detail/capability checklist, create revision, owner-only publish/archive controls, clear `Available / Limited / Planned / Unverified / Not supported` distinction and validation errors. Reuse existing Next UI if present. No drag/drop workflow builder, product analytics, pricing calculator, demos or AI generation in this phase.

Default seed: an **unpublished draft** `school_admin_starter` under `schools` vertical, with candidate modules such as admissions intake, fee tracking and reporting all `unverified` until YOU/owner provide evidence. **Never** seed fake prices, live capability claims, verified customer references, implementation timing or business success numbers. The platform remains fully usable for drafts without publishing a speculative offer.

## P1.3.4 Implementation tasks

1. Inventory P1.2 `verticals`, auth roles, current route conventions, P0.4 errors, migrations and test seed.
2. Implement offer/revision migrations, check constraints and scoped FKs. Handle offer↔revision reference cycle with deliberate migration ordering or no circular FK design.
3. Define immutable typed offer DTOs and a service that partitions claims by readiness/approval; fail closed on invalid JSON, missing evidence, missing limitations for limited claims or unapproved price rules.
4. Implement draft creation/version editing, owner publish/archival, immutable version read and sales-ready projection.
5. Provide minimal authenticated offer admin screens (or API-first plus compact approved UI if established UI is not yet usable); preserve backend permission checks.
6. Seed safe school draft only, with unverified capabilities and unset prices.
7. Add negative authorization, publishing/immutability, race, cross-org, empty/unknown/unsafe claim tests and migration rehearsals.
8. Document `docs/contracts/offer-catalog.md` (capability schema, revisioning, P4/P6 integration boundary), update ledger.

## P1.3.5 Acceptance gates

| ID | Test/evidence | Required result |
|---|---|---|
| OFFER-01 | Seed unpublished school draft, list scoped offers | Draft visible, no default published claim or prices |
| OFFER-02 | Operator creates new draft/revision then attempts publish | Can draft; publish rejected with 403/appropriate safe auth error |
| OFFER-03 | Owner publishes a revision where `planned` or `unverified` appears in approved claims | Rejected; no publication or partial DB write |
| OFFER-04 | Owner publishes `available` or bounded `limited` claim with actual evidence and explicit exclusions | Exactly one atomic published snapshot, stable SHA digest and approver metadata |
| OFFER-05 | Modify draft after publication and read old published revision | Old published claims unchanged and digest stable; new draft does not silently replace |
| OFFER-06 | Two concurrent publish/update requests with stale `expected_version` | One succeeds (when valid), stale writer gets 409; no split-brain active revision |
| OFFER-07 | Archive an offer, then query sales-ready | No new selling permitted; past revision retained for audit |
| OFFER-08 | Access another organization's offer/revision | 404/403 per documented policy; no data leak; raw cross-org FK insert rejected |
| OFFER-09 | Offer with missing price info, invalid pricing, invented delivery time or integration claim | `pricing_unavailable` or rejected; no generated/visible sales-ready false commitments |
| OFFER-10 | CSRF bad/missing, anonymous mutation, malformed JSON, P0/P1 regressions | All denied safely; migration + lint/types/tests pass with observed results |

**Failure simulations:** attempts to alter published revision via ORM/SQL (application policy plus database protections where practical); workflow after archived status, malformed capability matrix, ambiguous capability names, duplicate offer code, race with publish/archive, database failure mid-transaction, malicious HTML/prompt injection in claim summary. Render text safely and do not execute Markdown/HTML entered by operator or copied from sources.

**Rollback:** On disposable database test downgrade/re-upgrade. Production rollback of versioned published offers requires backup/forward repair; never erase historical approved claims to simplify deployment. Existing approved revisions remain readable under intentional archival policy and authenticated audit access.

**P1.3 STOP:** Do not start P1.4, campaigns, AI-generated drafts or WhatsApp integration.

---

# 4. Cross-subphase integration contract

| Invariant | Established | Consumed by later phases |
|---|---|---|
| Authenticated actor + organization context | P1.1 | All operator services/routes |
| Immutable session verification / CSRF / role guard | P1.1 | P1.3 publish; P1.4 CRUD; P4 approvals |
| Source-rights + fact provenance | P1.2 | P2 discovery, P3 research, P4 personalization |
| Separate source-supported facts and hypotheses | P1.2 | P3 qualification and assessment |
| Stable offer revision + approved claim snapshot | P1.3 | P4 message drafting and P6 responses |
| Archived offer not eligible for new selling | P1.3 | P4 send-intent policy, P8 follow-up |
| App's shared config/log/error/test harness | P0.2–P0.4 | All phases |

**No premature cross-wiring:** P1.1 does not implement offers; P1.2 does not start crawling Lahore; P1.3 does not call any LLM, WhatsApp provider or messaging simulator. P1.3 may define a typed projection contract for later consumption but not implement downstream flows.

## 5. Standard Opus close-out report (mandatory per subphase)

```text
Subphase / Git SHA / base SHA:
Preflight prerequisites (each status + ledger evidence):
Changed files, with intended reason per file:
Requirements covered (AUTH-*/DATA-*/OFFER-*):
Acceptance ID | exact executed test/command | result summary | PASS/FAIL/BLOCKED/NOT RUN
Negative tests + failure-state observations:
Migration upgrade/downgrade + data safety:
Security/privacy review (auth/org/claims):
Unchanged scope and any deviations/ADRs:
Rollback or forward-repair plan:
EXECUTION_LEDGER.md entry:
VERDICT: VERIFIED / PARTIALLY VERIFIED / BLOCKED
STOP: next subphase was NOT attempted.
```

**Do not confuse file generation with verified implementation.** This package defines what Opus must do and how to prove it; it does not assert that P0 or P1 code currently exists.

## 6. Security references (reviewed for implementation guidance)

- OWASP Session Management Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- OWASP CSRF Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- OWASP Password Storage Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

Use the *current* official guidance and your tested runtime behavior rather than copying obsolete code snippets. Production release remains contingent on threat review in P11.
