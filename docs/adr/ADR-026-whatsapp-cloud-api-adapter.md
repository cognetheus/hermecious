# ADR-026: A typed Meta WhatsApp Cloud API adapter behind explicit, non-elevating modes

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-10-29
- **Source:** `HERMECIOUS_BATCH_08_P5.1-P5.3.md` §0 and §P5.1; blueprint §4 P5.

## Verified external facts (checked 2026-10-29)

- **Graph API versions:** v26.0 was released on 2026-07-29 and has no end date yet. v25.0 is supported until 2028-07-29. Source: <https://developers.facebook.com/docs/graph-api/changelog>.
- **Pinned version:** v26.0 by default; only {v25.0, v26.0} are accepted.
- **Send endpoint:** `POST https://graph.facebook.com/{version}/{phone-number-id}/messages`.
- **Send success shape:** `messages[].id`, where `message_status` is one of `accepted`, `held_for_quality_assessment` or `paused`. Source: Cloud API messages reference.
- **What a success means:** the call was accepted. It is **not** sent, delivered or read.
- **No idempotency key on Graph:** application idempotency is internal only. A timeout after the request was written has an unknown outcome.

## Decision

### 1. Modes are an explicit, fail-closed boundary (`HERMECIOUS_WHATSAPP_MODE`)

| Mode | Allowed | Refused at startup |
|---|---|---|
| `simulation` (default) | The P4.5 fake only | Any Meta ID or credential |
| `contract_test` | An injected local fake HTTP layer | A real access token, or any environment other than `test` |
| `provider_test` | One confirmed Meta *test* WABA and phone | The production environment; a phone listed in `HERMECIOUS_WHATSAPP_PRODUCTION_PHONE_NUMBER_IDS`; a missing `…_TEST_IDENTITY_CONFIRMED_BY`/`_AT` (an operator checklist record, never inferred from names) |
| `production` | Inbound webhooks and read-only templates (P5.2/P5.3) | Any environment other than `production`; a missing app secret or verify token |

- **`HERMECIOUS_LIVE_OUTBOUND_ENABLED=true` refuses to start.** It cannot be enabled before P5.5 and is never silently ignored.
- **`HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED`** (P5.3) is valid only in `provider_test`.
- **`build_transport` is the only constructor, and it never elevates a mode:**
  - `simulation` → `LiveTransportForbidden`;
  - `production` → `LiveTransportForbidden` (until P5.5);
  - `contract_test` → requires an injected fake;
  - `provider_test` → the bound connection must equal the configured WABA, phone and version exactly.

### 2. One organization per connection (migration 0020, `provider_connections`)

- **Uniqueness:** one connection per organization, and a phone-number ID belongs to exactly one organization.
- **IDs:** digits only, checked in the DB and in `ProviderConnectionView`, because they become URL path segments.
- **Credentials:** `credential_ref` names the secret source (`env:…`); the secret stays in the environment.
- **Binding:** `bind_connection` (owner only) binds the *configured* IDs; nothing comes from a request.
- **No fallthrough:** `connection_for` refuses when the stored binding differs from the configured credentials.

### 3. Transport (`app/whatsapp/transport.py`)

- **Template messages only.** `SendIntent` carries a `recipient_ref`, never a phone number or URL (`extra="forbid"`). The number comes only from a server-side `ResolvedRecipient` (the P5.3 registry).
- **Template parameters are plain text:** no links, numbers or control characters; at most 5 components, 10 parameters each, 200 characters per parameter.
- **Refused before any network call:**
  - not `APPROVED` (the provider's own string);
  - the provider category does not fit the purpose (`operator_test` → MARKETING or UTILITY; AUTHENTICATION and unknown categories fail closed);
  - a different WABA, a name or language mismatch, wrong placeholder counts;
  - a disabled connection, a cross-organization intent, a recipient mismatch, or `service_text`.
- **Outcomes:**
  - `accepted`: a valid `wamid`.
  - `definitive_rejected`: typed `provider_auth`, `provider_quota`, `provider_transient` or `provider_bad_request`, with a retry class. Only the numeric code is kept; the provider's message text never is.
  - `indeterminate`: a reset or timeout after the write, or a malformed or oversized 2xx. Never resent.
- **Egress:** the existing `PinnedHttpsClient` (ADR-013) gains `request_json`. It sends a Bearer header and JSON, returns the status for typed mapping, raises `UpstreamUncertain` once bytes may have been written, and is limited to three exact Graph paths per connection: messages, message_templates, and the phone-number resource for the health check.
- **No second HTTP client** and no new runtime dependency.
- **No dispatch in P5.1.** No route, job type or campaign path imports the transport. P5.3 adds exactly one guarded operator test caller.

## Consequences

- Contract tests run fully offline.
- The P4.5 simulator remains fake-only; its package never imports `app.whatsapp`.
- Production outbound cannot be configured at all.

## Rollback

- Set `HERMECIOUS_WHATSAPP_MODE=simulation` and clear the credentials.
- The `provider_connections` rows are inert identifiers; disable a row with `enabled=false`. Never delete history.
