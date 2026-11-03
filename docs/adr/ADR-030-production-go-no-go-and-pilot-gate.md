# ADR-030: Production go/no-go, owner attestations and a separately gated 1:1 pilot

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-11-02
- **Source:** `docs/phases/OPUS_P5.5_PROMPT.md` and blueprint §4 P5.5. The cited Batch 09 document is not in the repository.

## Decision

### 1. Readiness is computed from evidence and is never a permission

`POST /api/v1/release/whatsapp/readiness/evaluate` (owner) stores an **immutable** assessment. It is append-only (a database trigger), lasts 24 hours and is bound to a digest. Each check reports `VERIFIED | FAILED | UNKNOWN | BLOCKED_EXTERNAL`, an evidence reference, a reason and who can resolve it.

| Check | Source |
|---|---|
| provider identity | a bound **production** connection on a configured production phone, with a token and app secret. A Meta test number is FAILED |
| meta business verification, pakistan legal review, operations readiness | **owner attestations** only: a statement plus an evidence reference, append-only, 90 days. A bare boolean is refused (422) |
| real test receipt (WATEST-10) | a local P5.3 send proven `delivered`/`read` by a signed webhook, **or** an attestation (the P5.3 test runs on a separate non-production deployment) |
| webhook health | signed callbacks for the connection in the last 7 days |
| template catalog | a fresh (24 h) APPROVED, supported MARKETING/UTILITY template read from Meta (`POST …/catalog/sync`, owner, **read-only**) |
| school evidence audit | the P3.4 gate (a real, finalized, PASSED 30-school audit, not older than 90 days) |
| opt-in evidence | at least one verified P4.3 permission |
| approved content | a P4.4 approval bound to `meta:<template id>` that P4.4 still reports as current |
| operator inbox, kill switch, deployment identity | P5.4 deployed; the kill switch clear; `HERMECIOUS_BUILD_SHA` set |

**Status:** any FAILED or UNKNOWN → `no_go`; otherwise any BLOCKED_EXTERNAL → `blocked_external`; otherwise `ready_for_operator_review`. The response always says `grants_sending: false`.

The digest covers only stable evidence (check codes, statuses, evidence references, identity fingerprints, environment, build). Raw IDs and secrets are never stored or exported; only 16-hex-digit fingerprints are.

### 2. Three independent gates, all required at confirmation time

1. **Deploy-time live gate.** `HERMECIOUS_LIVE_OUTBOUND_ENABLED=true` now refuses to start unless all of these hold:
   - `HERMECIOUS_ENV=production`;
   - `HERMECIOUS_WHATSAPP_MODE=production`;
   - `HERMECIOUS_BUILD_SHA` is set;
   - `HERMECIOUS_LIVE_OUTBOUND_APPROVED_BY` and `_APPROVED_AT` (not in the future) are set.

   Test, development and CI therefore can never enable it. The committed `.env.example` and `compose.yaml` keep it `false`.
   **This relaxes the Batch 07/08 "always refuses" rule, which said it would hold only until P5.5. The owner must accept it.**
2. **Owner pilot authorization** (`POST …/pilot`):
   - it needs a fresh `ready_for_operator_review` assessment whose digest still matches a recomputation;
   - the owner types the exact acknowledgement;
   - the scope is one connection and one purpose, at most **3** messages per Asia/Karachi day, and at most **14** days;
   - only one live authorization per connection;
   - it can be paused (`human_takeover`, `quality_alert`, `investigation`, `opt_out_review`), resumed or revoked (final);
   - it is audited.
3. **Per-send checks** (below).

No model, job, CSV import or UI preview can set the live flag. The agent did not set it.

### 3. The pilot send (preview, then owner confirmation)

**Preview** (owner or operator):
- The request carries only `draft_id`, `parameters` and `idempotency_key`. `phone_number`, `template_status`, `skip_consent`, `campaign_send` and `account_id` are rejected (422).
- The recipient, purpose and template come from the **P4.4 approval of the exact draft revision**. The template must be the synced Meta row named by `meta:<template id>`, APPROVED, with no header parameters, and of the purpose's category.
- The preview stores an exact digest, a one-time nonce (hash only) and a 10-minute expiry.

**Confirm** (owner, CSRF, digest, nonce, and the number) re-checks in this order:
1. live gate;
2. authorization: active, not paused or expired, same connection;
3. daily cap;
4. readiness recomputed now equals the authorized digest;
5. the P4.4 approval is still current for this revision;
6. P4.3 `decide()` allows: consent scope and freshness, suppression, kill switch, Asia/Karachi quiet hours, campaign and P3.4 gate, human owner, provider template;
7. Meta's live catalog still has the template APPROVED with the same components.

Then it **reserves** (commit; one in flight per connection), re-reads the kill switch and live gate (a stop between the reservation and the call ends it as `stopped_before_send`), makes **exactly one** Graph call and records the outcome:
- `provider_accepted` means accepted, **not** delivered;
- otherwise `definitively_rejected` (401/429/5xx typed) or `indeterminate`.

There is never an automatic retry or resend. A stale reservation can only be marked `indeterminate` by an owner after 2 minutes. Delivery comes only from signed webhooks (P5.2).

### 4. The number is never stored

P4.3 keeps a contact's number only as a keyed digest, so no server-side plaintext exists. At confirmation the owner types the number. It must hash, under the contact's key, to the **approved** contact's digest. It is used once, in memory, and never stored or logged. A mismatch is a 409 that does not consume the preview.

This can reach only the opted-in contact named by the approval, never an arbitrary number. The alternative, sealing contact numbers at rest as ADR-029 does for inbound text, is an owner decision.

### 5. Read-only production catalog

`build_transport(…, purpose=…)`:
- `test` is P5.3 only and never touches a production connection;
- `production_read` is a client that cannot send;
- `production_send` exists only when the live gate is open in a production environment.

A test-mode connection never carries production traffic.

### 6. Interface gap: P4.4 has no production content approval

P4.4 approves **fixture campaigns only**: it refuses any non-fixture campaign with `production_approval_unavailable`, and its rows carry a `simulation_only` check. In production, fixture campaigns are blocked. So **no approval can be current in production today**: readiness reports `approved_content: BLOCKED_EXTERNAL`, and the pilot fails closed.

P4.4 was not changed (prompt scope; security-relevant). How production content is approved is an owner decision.

The pilot's own mechanics are tested through one narrow, documented test seam that drops only that one reason, with everything else real. A separate test proves the unpatched gate keeps production closed.

## Consequences

- **Result:** production outreach readiness stays **NO**. In the current repository the review evaluates to `no_go` / `blocked_external`. No real message was sent by this work, and every automated pilot send is recorded as `simulated_transport`.
- **To go live (owner only):**
  1. provide Meta production credentials and verification;
  2. record the attestations;
  3. complete WATEST-10;
  4. decide P4.4 production approval;
  5. complete the P3.4 real audit;
  6. obtain real opt-ins;
  7. deploy with the live gate and a named approval;
  8. evaluate, authorize, preview, confirm.
- **Rollback:**
  - pause or revoke the authorization;
  - set `HERMECIOUS_OUTREACH_KILL_SWITCH=true` or `HERMECIOUS_LIVE_OUTBOUND_ENABLED=false`.

  Meta cannot recall a message it has already accepted. Migration 0024 is additive.

## Amendment (2026-11-03, audit)

- **Between the reservation and the call**, the pilot re-reads the global stop, the live gate, **the pilot authorization** (paused for human takeover or a quality alert, revoked, expired) and **the connection** (disabled). Any change ends the attempt as `stopped_before_send`.
- **Circuit breaker:** a `provider_auth` or `provider_quota` outcome automatically pauses the pilot (`pause_reason: provider_error`). Nothing more reaches Meta until an owner resumes it.
