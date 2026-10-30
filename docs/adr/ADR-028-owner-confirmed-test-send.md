# ADR-028: One owner-confirmed real test template, to one allowlisted operator-owned number

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-10-30
- **Source:** `HERMECIOUS_BATCH_08_P5.1-P5.3.md` §P5.3, §2 and §4.

## Context

Batch 08 lets the system send exactly one kind of real message: a Meta-approved template sent to a test number the owner controls, so the P5.1 transport and the P5.2 status path can be proven end to end. Prospect outreach stays off: `HERMECIOUS_LIVE_OUTBOUND_ENABLED=true` refuses to start, and P5.5 owns the go/no-go decision.

## Decision

### 1. One sender, reachable from one route

- `app/whatsapp/test_sends.py` is the only module that imports the transport and the only caller of `send_template`. The WAAD-10 unit test enforces both, and pins the exact list of WhatsApp POST routes.
- No job type, campaign, draft, account, contact or simulator path reaches it.
- There is no route that takes a phone number, body, campaign, account or URL. Request bodies use `extra=forbid`.

### 2. Modes and switches (all must hold at confirm time)

- `HERMECIOUS_WHATSAPP_MODE` is `provider_test`, or `contract_test` for automated tests, where a fake Graph layer is injected and no socket opens.
  - `simulation` and `production` refuse with 409.
- `HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED=true` is a separate test kill switch. It is never a production override and is refused in any other mode.
- The organization's connection is bound and matches the configured WABA, phone and mode. Its version is unchanged since the preview.

### 3. Recipients come from a server-side allowlist

- `HERMECIOUS_WHATSAPP_TEST_RECIPIENTS` lists at most 5 E.164 numbers. It is a `SecretStr` because it is personal data, and is kept in the untracked `.env`.
- An owner registers a number only if all of these hold:
  - it is on that list;
  - it is not a sourced contact in any key generation;
  - it is not suppressed.
- Registration stores a 20–500 character consent statement.
- Only a keyed digest and a mask (`+92 ••••••• 201`) are stored. At confirm time the number is recovered by matching the digest against the allowlist, so it is never read from a request or the lead database.
- Revoked recipients are never reactivated automatically.

### 4. Provider-authoritative catalog

- An owner sync reads `GET /{WABA}/message_templates`. It is paginated and stops after 10 pages.
- Meta's strings (status, category) are stored exactly. A template missing from a sync becomes `NOT_RETURNED`; nothing is kept as approved by default.
- A template is usable for a test only if it is:
  - fresh (fetched within 15 minutes);
  - `APPROVED`;
  - `UTILITY` or `MARKETING`;
  - free of header parameters and unsupported components.
- `AUTHENTICATION`, `PAUSED`, `PENDING`, stale templates and media headers are refused.
- No template is assumed to exist. The fixture name `hermecious_test_ping` is synthetic.

### 5. Two steps: preview, then owner confirmation

The spec's states `created → preflight_passed → awaiting_confirmation` are collapsed into one transaction: a preview that fails preflight is never stored.

1. **`POST /test-sends`** (owner or operator, CSRF) creates a non-sending preview and returns it once:
   - an exact preview digest covering the phone and WABA IDs, the template id, name, language, category and components digest, the parameters and the recipient;
   - a 10-minute expiry;
   - a one-time confirmation nonce. Only its SHA-256 is stored.

   The same idempotency key with the same payload returns the same record without a nonce. A changed payload returns 409.
2. **`POST /test-sends/{id}/confirm`** (owner only, CSRF) runs in this order:
   1. locks the row and checks the digest and nonce in constant time;
   2. re-checks mode, kill switch, binding, recipient (active, allowlisted, not suppressed, not a sourced contact) and the daily cap (3 attempts per Asia/Karachi day);
   3. re-fetches the template from Meta by name: it must still be `APPROVED` with the same components digest;
   4. **reserves** the row and commits;
   5. makes **exactly one** Graph call;
   6. records `provider_accepted`, `definitively_rejected` or `indeterminate`.

   - Any failed re-check ends the preview as `denied` with a reason, makes zero Graph calls, and requires a new preview.
   - A partial unique index allows only one `reserved` row per connection.
   - A replayed confirmation, including one that lost a race, returns the recorded outcome and never sends again.
3. The session is not re-authenticated: the repository has no step-up auth. The owner role, CSRF and the one-time nonce are the controls.

### 6. Outcomes are honest

- **Acceptance is not delivery.**
  - `provider_accepted` stores the `wamid` and shows `accepted_unknown_delivery`.
  - `sent`, `delivered` and `read` come only from signed P5.2 webhooks, joined by `(connection, wamid)` when the record is read. A status that arrived before the confirm returned is therefore reconciled too.
- **No outcome triggers a resend**, whether a timeout, a malformed 2xx or an oversized response (`indeterminate`/`provider_uncertain`), a 429 (`provider_quota`) or a 401 (`provider_auth`).
- **Stale reservations:** a reservation older than 2 minutes, for example after a worker crash, can only be marked `indeterminate` by an owner.
- **Audit:** every preview, confirmation, registration, revocation, sync and manual mark is audited.

### 7. UI

`/integrations/whatsapp` shows:

- the connection status;
- the catalog with freshness;
- masked recipients;
- the preview form;
- a confirmation dialog titled **"This will send a REAL WhatsApp message to my registered test number."**, which needs a checkbox before the owner-only send button is enabled;
- a timeline of webhook statuses.

Observers see redacted status only and no controls. There is no "send to account", campaign, bulk or free-form recipient control.

## Consequences

- **Evidence:** WATEST-01..09 are verified offline, against Postgres and a fake Graph layer. **WATEST-10 (a real receipt) is BLOCKED_EXTERNAL** until the owner supplies Meta test credentials, a Meta test phone number and a verified test recipient, and performs the confirmation. It is never marked verified from mocks.
- **Rollback:** set `HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED=false`, which denies confirms immediately, or switch the mode back to `simulation`. Migration 0022 is additive and downgrades cleanly.
