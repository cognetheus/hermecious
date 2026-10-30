# ADR-027: The Meta webhook is HMAC-authenticated, durably stored before 2xx, and processed idempotently

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-10-30
- **Source:** `HERMECIOUS_BATCH_08_P5.1-P5.3.md` §P5.2 and §4.

## Decision

### 1. Endpoints

They are public by design, because Meta has no session. They are the only entries in `PUBLIC_API_PATHS` besides login, and the startup guard still fails on any other unprotected route.

- **`GET /api/v1/integrations/whatsapp/webhook`:**
  - requires exactly `hub.mode=subscribe` and a constant-time `hub.verify_token` match;
  - the challenge must match `^[A-Za-z0-9_-]{1,128}$` and is returned as `text/plain`;
  - anything else is a bodyless 403. The token is never echoed.
- **`POST …/webhook`:**
  - unset app secret → 503 (fail closed);
  - not `application/json` → 415;
  - body over **256 KiB** → 413 (Meta batches are small; the cap bounds parse time);
  - `X-Hub-Signature-256` is verified as `sha256=<hex>`, HMAC-SHA256 over the **exact raw bytes** with the app secret, compared in constant time. Missing, malformed or wrong → 401, and **nothing is stored**;
  - storage failure → 503 (Meta retries). 200 only after commit.
- **Logs:** request logs carry the path only. The redactor now also masks any key *ending* in a sensitive word (`hub.verify_token=`, `app_secret:`).

### 2. Binding comes from configuration, never from the payload

- A change is attached only if `metadata.phone_number_id` is the configured phone, `entry.id` is the bound connection's WABA, the connection is enabled, and its mode matches the configured mode.
- Anything else counts as `unmapped`: no tenant data is stored, only a counter on the envelope.
- `organization_id` is never read from the payload.

### 3. Storage (migration 0021)

- **`provider_webhook_envelopes`:** one row per delivery. It holds a body digest and counts, with no tenant data. The raw body is **not** retained.
- **`provider_event_items`:**
  - one per logical fact, unique per connection on `logical_key`:
    - a message: `msg:connection:wamid`;
    - a status: `status:connection:wamid:status:timestamp:error`;
    - other: a canonical digest;
  - a redelivered or overlapping batch inserts only its new items;
  - `arrival_seq` (DB identity) gives processing order;
  - signed but unusable items are stored `quarantined` with a reason: a future timestamp (more than 5 minutes ahead), a stale one (over 8 days), an invalid id, or an unsupported field.
- **`provider_status_observations`** (append-only): every genuine observation.
- **`provider_message_status`:** the projection.
- **`provider_inbound_messages`** (append-only):
  - unique per connection and wamid;
  - the sender as a P4.3 keyed digest plus a masked hint;
  - **no text body** (only kind, length and a STOP flag);
  - `assignment` is `contact` or `unassigned`.
- **`provider_service_windows`:** for a known contact, `max(prior, verified provider timestamp)`.
- **Retention:** no raw bodies or texts are stored. Envelopes, items and observations are audit history; a purge policy is deferred to P5.4 with the inbox UI.

### 4. Processing (`provider_inbox.process` v1, an allowlisted P1.5 job, enqueued in the receive transaction)

- **Claiming:** one pending item per transaction, claimed `FOR UPDATE SKIP LOCKED`; the domain change and the processed marker commit together.
- **Failures:** a storage error leaves the item pending and the job retries; any other error parks only that item as `failed`; the lease is renewed between items (ADR-025).
- **Projection rules** (`inbox.project`):
  - sent < delivered < read; never downgraded;
  - `failed` after delivered or read → kept, with conflict `failed_after_delivered`;
  - success after `failed` → success, with conflict `success_after_failed`;
  - `unknown` adds no information.
  - Statuses for wamids with no local send are kept as observations and a projection, but no fake message row is created.
- **Inbound:**
  - A known contact (digest match) updates the service window. That is service-reply provenance used by P4.3 `decide()`, **never marketing consent**.
  - An unknown sender stays `unassigned`: no contact, account or consent is created.
  - An authenticated STOP or unsubscribe (English or Urdu) inserts a P4.3 suppression (contact or bare number, `opt_out`), audited with `source: whatsapp_inbound_stop` under the connection owner. Suppressions are never reopened automatically.
- **No replies:** nothing replies, sends, or enqueues a template or campaign.

## Consequences

- **The P4.3 service-reply window can be real.** It is still simulation-only; P5.3 governs the only send.
- **Earlier guards were refined.** Guards that proved "no message tables" now name the two P5.2 inbound tables explicitly (`INBOUND_PROVIDER_TABLES`) rather than matching on the word.

## Rollback

- **Stop receiving:** unsubscribe the callback at Meta (operator action), or unset the app secret (POST → 503, GET → 403).
- **Data:** keep all stored evidence.
- **Schema:** downgrade 0021 only on a disposable database.
