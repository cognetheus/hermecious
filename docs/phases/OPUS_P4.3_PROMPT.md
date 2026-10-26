# OPUS 5.5 HIGH — HERMECIOUS P4.3: Channel Eligibility Engine

**ASSIGNMENT:** Implement **P4.3 only**. **Do not approve content, queue messages, send WhatsApp, or begin P4.4. STOP after verified evidence.**

## Your context and prerequisites

Read in this order:
1. `CLAUDE.md` / `AGENTS.md`; repository ADRs, `EXECUTION_LEDGER.md`.
2. `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` (especially P4, sending decision, policy boundaries).
3. `docs/phases/HERMECIOUS_BATCH_06_P3.4-P4.2.md` (P3.4 quality gate and P4.1/P4.2 contracts).
4. `docs/phases/HERMECIOUS_BATCH_07_P4.3-P4.5.md` sections **0, P4.3, 4, 5**.
5. Inspect actual P1.1 sessions/RBAC, P1.2 `contacts` / `contact_permissions` / `suppression_entries`, P1.5 job registry, P4.1 campaigns, P4.2 draft schema. All previous docs describe intentions, NOT proof the code exists.

Before editing, print actual SHA, branch, dirty worktree, Docker/DB availability, migration head, related module inventory, baseline test command/results and gaps. Do not overwrite uncommitted work. If existing predecessor is missing, implement only a **safe boundary-compatible** P4.3 slice with fixture/integration tests and record blocked integration honestly; do not recreate all earlier phases.

## Outcome, not a feature wishlist

Build a **versioned deterministic server-side policy evaluator** that returns `allow_for_simulation | deny | defer`, reason codes, policy revision, permission/suppression revisions, evaluated timestamp and `live_send_authorized=false` for all decisions. Provide minimal owner-controlled evidence review, recipient suppression/revocation, status UI and scoped API. Public school phone != permission. Research priority != consent. An inbound service inquiry != marketing opt-in.

No WhatsApp SDK, no API access token, no unofficial QR/browser automation, no active sender or outbound job type. All data remains tenant/org scoped and masked. Default to deny on missing/uncertain policy settings, expired or unverifiable proof.

## Implementation sequence — execute in this order

1. **Inventory and contract reconciliation.** Determine canonical existing permissions, account/contact normalizations, source proofs, encrypted fields, audit helpers, org scoping, campaign statuses. Write ADR only for meaningful decisions. Build `ELIG-01..10` matrix against actual test locations. Do not duplicate existing tables with new service names.
2. **Data model expansion.** Use additive migration to capture specific channel/purpose/named business permission basis, source/capture method, consent wording version, minimal encrypted proof reference, effective/revoked/expiry dates, reviewer ID, review timestamp and version. Add scoped recipient suppression keyed by canonical E.164 + keyed HMAC digest; document key rotation and archival/retention. Reject any migration that loses current suppressions. Enforce uniqueness/foreign keys across org. Avoid exposing personal/student data.
3. **Evidence capture and verification.** `record_permission_evidence` creates **pending**, never verified; owner must validate an authentic record demonstrating opt-in to this named business, channel and purpose. UI must display source/recorded timestamp and verification actor; mask address and limit evidence access. Bad, missing, future-dated, mismatched or fabricated-looking metadata must fail review. API path should not allow a client to send `verified=true`; strip/reject. No LLM decision or auto-grant. Revoke and suppress independently, with suppressions dominating all campaigns.
4. **Typed `ChannelEligibilityService`.** Start with explicit `Channel=whatsapp` and `Purpose=marketing|utility|service_reply`. Testable, injected clock (UTC), policy version and local schedule (`Asia/Karachi`). Use deterministic precedence: kill/pause, suppression, verified permission, scope/purpose, proof freshness, template/work-window rules, campaign/quality gate, human owner, quiet hours and caps. For free-form service reply use **official inbound context** where available; in P4.3 synthetic signed fixture only, never a user-controlled `last_inbound_at`. In-window vs out-of-window boundary at 24h precisely. Business initiation requires suitable opt-in and provider-approved template; until P5, **only synthetic fixture can assert template verified for simulation**; operator-entered template state is unverified. Always `live_send_authorized=false`.
5. **API and UI.** Adapt `/api/v1/contacts/{id}/permissions`, permission `:verify` and `:revoke`, contact `:suppress`, `/api/v1/channel-eligibility/evaluate` to repo patterns. Owner verification; operator/owner capture/revoke/suppression; observers read masked status only; auth/CSRF/expected revision/idempotency. Compact audit records store actor, typed reason, input digest, policy revision, never plaintext address/proof. UI labels `Simulation eligibility only — sending disabled` and shows why blocked.
6. **Secure retry/race behavior.** Transactionally enforce suppressions and revocations. Evaluate current DB after permission changes; no cached allow tokens. Campaign pause/source-rights/offer/quality-gate invalidation are blocking; use version-sensitive readings. Concurrent updates must fail safely; interrupted verification must not partially grant.
7. **Prove then stop.** Unit tests each policy branch, DB integration for permissions/suppressions and org isolation, API RBAC/CSRF, timezone boundary, injection handling, concurrency and replay. Test `ELIG-01..10` and regress core auth/campaign/draft behavior. Inspect P1.5 registries and DB outbox: zero outbound send capability introduced. Update `EXECUTION_LEDGER.md` with observed evidence and actual commands.

## Mandatory acceptance IDs (each must map to a real test)

| Gate | Proof requirement |
|---|---|
| `ELIG-01` | Public number with no opted-in permission is denied |
| `ELIG-02` | Missing/unverified/wrong business or purpose proof fails closed |
| `ELIG-03` | Only explicit verified scoped permission with synthetic verified-template fixture may allow **simulation**; never live authorization |
| `ELIG-04` | Opt-out/suppression beats approvals across campaigns and races |
| `ELIG-05` | Revoked/expired/edited permissions invalidate former preflight result |
| `ELIG-06` | 24-hour inbound service boundary works; no marketing consent inferred |
| `ELIG-07` | Missing/rejected/unverified/wrong-category template denies business initiation |
| `ELIG-08` | Business schedule/timezone/cap produce correct deferred decision, no queue |
| `ELIG-09` | CSRF/RBAC/tenant checks, evidence attack and PII masking are verified |
| `ELIG-10` | Kill/pause/stale quality or source/campaign state always blocks; zero provider/send jobs |

## Hard prohibitions

Do **not** (a) insert fabricated consent for real Lahore schools, (b) send testing messages, (c) add worker `send_message`, (d) mark unverified operator-added WhatsApp template as provider approved, (e) make preflight decision a reusable bearer authorization, (f) grant consent because a contact wrote `hello` once, (g) implement P4.4 or P4.5.

## Deliverable report template

- Repo SHA + branch + baseline results; exact files changed and additive migrations.
- Data/endpoint/schema contracts with examples **using only synthetic contacts**.
- `ELIG-01..10` table: test name, command, observed result, status (`VERIFIED|FAILED|BLOCKED|NOT-RUN`).
- Negative-path, race and redaction evidence. Policy reference/version and trust boundary proof.
- Zero send/outbox/network checks, rollout feature flag, safe rollback, unresolved blockers and quality-gate status.
- `P4.4 implementation-ready?` vs `real WhatsApp production-ready?` (second MUST remain **NO**).

**STOP AFTER P4.3. Do not continue to P4.4 without a new prompt.**
