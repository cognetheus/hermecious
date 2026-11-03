# WhatsApp Cloud API contract (Batch 08)

Decision records: [ADR-026](../adr/ADR-026-whatsapp-cloud-api-adapter.md) (P5.1). P5.2 and P5.3 extend this file. Code: `apps/api/app/whatsapp/`.

> **Production outreach is not enabled.** No route, job or campaign dispatches a WhatsApp message. `HERMECIOUS_LIVE_OUTBOUND_ENABLED=true` refuses to start.

## P5.1 types (`whatsapp-contracts-1.0`)

All types are strict: unknown fields are refused and every time is timezone-aware UTC.

| Type | Key fields | Notes |
|---|---|---|
| `SendIntent` | `operation_id, organization_id, provider_connection_id, purpose, recipient_ref, kind, template_name, template_language, template_components, draft_revision_digest, approval_id, policy_revision, created_at_utc, idempotency_key` | There is no phone or URL field. Parameters are plain text only |
| `SendResult` | `outcome` (`accepted`, `definitive_rejected` or `indeterminate`), `provider_message_id`, `provider_message_status`, `provider_error_code`, `error_class`, `retriable` | `accepted` ≠ delivered |
| `DeliveryUpdate`, `IncomingMessage` | Webhook observations | Populated in P5.2 |
| `TemplateDescriptor` | `waba_id, template_id, name, language, category, provider_status, components_digest, body/header_parameter_count, fetched_at_utc, source` | The provider's strings are stored as returned |
| `ProviderConnectionView` | `connection_id, organization_id, waba_id, phone_number_id, graph_version, mode, enabled, credential_ref` | IDs are digits only |

### Error classes

- `validation`, `authn`, `authz`, `policy_denied`;
- `provider_bad_request`, `provider_auth`, `provider_quota`, `provider_transient`, `provider_uncertain`;
- `webhook_signature`, `webhook_unmapped`, `payload_invalid`;
- `storage_unavailable`, `concurrency_conflict`, `unknown`.

### Graph error mapping (send)

| Response | Class | Retriable |
|---|---|---|
| 401, 403, or codes 10/190/200 | `provider_auth` | no |
| 429, or codes 4/17/32/613/80007/130429/131048/131056 | `provider_quota` | yes |
| 5xx | `provider_transient` | yes |
| Other 4xx | `provider_bad_request` | no |
| Malformed or oversized 2xx, or a timeout or reset after the write | `indeterminate` (`provider_uncertain`) | **never resent** |
| Connection failed before the write | `definitive_rejected` (`provider_transient`) | yes |

## P5.2 webhook ([ADR-027](../adr/ADR-027-signed-webhook-inbox.md))

| Request | Result |
|---|---|
| `GET …/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<1-128 [A-Za-z0-9_-]>` | 200 `text/plain` challenge, otherwise a bodyless 403 |
| `POST …/webhook` with a valid `X-Hub-Signature-256`, JSON, ≤256 KiB | 200 `{"status":"received","accepted":n}` after a durable commit |
| Bad or missing signature | 401 `webhook_signature` (nothing stored) |
| App secret unset / storage down | 503 `webhook_not_configured` / `storage_unavailable` (Meta retries) |
| Wrong content type / too large | 415 / 413 |
| Signed but foreign, malformed or unmapped | 200, recorded as a quarantined envelope (no tenant data) |

**Projected statuses:** `sent` → `delivered` → `read` (never downgraded). `failed` before delivery becomes `failed`; after delivery it is flagged `failed_after_delivered`. A success after `failed` is flagged `success_after_failed`.

## P5.3 test send ([ADR-028](../adr/ADR-028-owner-confirmed-test-send.md))

All routes are under `/api/v1/integrations/whatsapp`. They need a session, and CSRF on POST. Request bodies reject unknown fields with 422.

| Route | Roles | Result |
|---|---|---|
| `GET /connection` | all | mode, Graph version, bound (masked phone ID), matches configuration, kill switch, `live_outbound_enabled: false` |
| `POST /connection/bind` | owner | binds the configured IDs |
| `GET /templates` | all | Meta's catalog: status and category as returned, `fresh` (≤15 min), `usable_for_test` |
| `POST /templates/sync` | owner | reads Meta (paginated, ≤10 pages); missing templates become `NOT_RETURNED`; 409 outside test modes |
| `GET /test-recipients` | all | masked; consent details are hidden from observers |
| `POST /test-recipients` | owner | `{address, label, consent_statement}`: 422 `NOT_ALLOWLISTED`, 409 for a sourced contact or a suppressed number |
| `POST /test-recipients/{id}/revoke` | owner | final |
| `POST /test-sends` | owner, operator | `{recipient_id, template_id, parameters[], idempotency_key}` → 201 preview with a one-time `confirmation_nonce`; a replay returns 200 without a nonce; a changed payload returns 409 |
| `POST /test-sends/{id}/confirm` | owner | `{preview_digest, confirmation_nonce}` → one Graph call; 409 `test send denied: <reason>`; a replay returns `replayed: true` |
| `POST /test-sends/{id}/cancel` | owner, operator | only while `awaiting_confirmation` |
| `POST /test-sends/{id}/mark-indeterminate` | owner | only for a `reserved` row older than 2 minutes |
| `GET /test-sends`, `GET /test-sends/{id}` | all | observers get `{id, state, delivery, created_at, real_message, label}` only |

**States:** `awaiting_confirmation` → `reserved` → `provider_accepted` | `definitively_rejected` | `indeterminate`. A preview can also end as `denied`, `expired` or `cancelled`.

**Delivery** (separate from the state): `accepted_unknown_delivery` until a signed webhook shows `sent`, `delivered`, `read` or `failed`. The value never regresses.

**Denial reasons:**
- `not_test_mode`, `test_outbound_disabled`;
- `connection_mismatch`, `connection_changed`;
- `recipient_revoked`, `recipient_not_allowlisted`, `recipient_suppressed`, `recipient_is_sourced_contact`;
- `daily_cap_reached`;
- `template_check_failed_<error_class>`, `template_changed`.

## P5.4 read-only inbox ([ADR-029](../adr/ADR-029-read-only-inbox-and-sealed-inbound-text.md))

All routes are under `/api/v1/inbox/whatsapp`. Only owners and operators can use them; observers get 403. Every response carries `Cache-Control: private, no-store`.

| Route | Result |
|---|---|
| `GET /threads?cursor=&limit≤50` | `{items: [{id, party: {type, label, address (masked), conflict, suppressed, environment}, last_activity_at, unread, last_inbound_seq, reviewed_through_seq, reviewed_at, version}], next_cursor}`. Newest activity first; keyset paging. A bad cursor or limit → 422 |
| `GET /threads/{id}?before=&limit≤100` | `{thread, entries, before_cursor, read_only: true}`. Entries are in chronological order |
| `POST /threads/{id}/review` | `{through_seq}` → `{reviewed_through_seq, version, changed}`. Monotonic and clamped; audited once |
| `POST /rebuild` (owner) | 202 `{job_id}`: the `inbox.rebuild` job recomputes threads from the source tables |

**Entry shapes:**
- **inbound:** `{type: "inbound", id, at, seq, kind, text|null, content, truncated, stop_signal, provenance: "verified_inbound"}`. `content` is one of `available`, `not_retained`, `expired`, `unreadable` or `not_text`.
- **test outbound:** `{type: "test_outbound", id, at, state, template, provider_message_id, error_class, delivery, statuses[{status, at, error_code, provenance: "signed_webhook"}], provenance: "provider_test"}`.

## P5.5 production go/no-go ([ADR-030](../adr/ADR-030-production-go-no-go-and-pilot-gate.md))

All routes are under `/api/v1/release/whatsapp`. Only owners and operators can read them; observers get 403. Every response carries `private, no-store`. Request bodies reject unknown fields with 422.

| Route | Roles | Result |
|---|---|---|
| `GET /readiness` | owner, operator | latest assessment, attestations, authorizations, `live_gate` (`open` or a reason), banner, acknowledgement text |
| `POST /readiness/evaluate` | owner | 201 immutable assessment `{status: no_go\|blocked_external\|ready_for_operator_review, checks[], digest, expires_at, grants_sending: false}` |
| `POST /attestations` | owner | `{kind, statement (20–1000), evidence_ref (10–500)}` |
| `POST /catalog/sync` | owner | read-only Meta catalog for the production connection (production mode only) |
| `POST /pilot` | owner | `{assessment_id, acknowledgement (exact), purpose, max_per_day ≤3, days ≤14}`. Needs a fresh ready assessment whose digest still matches; another tenant's id → 404 |
| `POST /pilot/{id}/pause\|resume\|revoke` | owner | pause reasons: `human_takeover`, `quality_alert`, `investigation`, `opt_out_review`. Revoke is final |
| `POST /pilot-sends` | owner, operator | `{draft_id, parameters[], idempotency_key}` → a non-sending preview with a one-time `confirmation_nonce` |
| `POST /pilot-sends/{id}/confirm` | owner | `{preview_digest, confirmation_nonce, recipient_number}` → at most one Graph call; 409 `pilot send denied: <reason>`; a replay returns `replayed: true` |
| `POST /pilot-sends/{id}/cancel`, `/mark-indeterminate` | owner, operator / owner | as for P5.3 |

**Denial reasons:**
- `not_production_environment`, `not_production_mode`, `live_outbound_disabled`;
- `pilot_<pause reason>`, `pilot_not_active`;
- `connection_mismatch`, `connection_changed`;
- `daily_cap_reached`, `readiness_invalidated`, `approval_stale`;
- `eligibility_<deny|defer>:<codes>`;
- `template_check_failed_<class>`, `template_changed`;
- `stopped_before_send`.

## P6.1 intent observations ([ADR-031](../adr/ADR-031-intent-observations-for-human-review.md))

**Timeline:** each inbound entry from `GET /api/v1/inbox/whatsapp/threads/{id}` carries `intent`. It holds either the newest `intent.v1` observation for the current classifier version, or `null`. The observation contains:
- `primary_intent`, `secondary_intents`, `safety_flags`, `language`;
- `evidence[{start, end, text, reason}]`, `confidence`, `requires_human_review`;
- `recommended_action` (read-only), `reason_codes`;
- `classifier_version`, `rules_version`, `model_version: null`, `prompt_version: null`, `classified_at`;
- `observation_id`, `review`, `notice`.

| Route | Roles | Result |
|---|---|---|
| `POST /api/v1/inbox/whatsapp/messages/{message_id}/intent-review` | owner, operator (CSRF) | `{observation_id, decision: confirmed\|corrected, corrected_primary?, note?}` → 201. A correction equal to the label → 409; an unknown label → 422; another tenant's message → 404 |
| `POST /api/v1/inbox/whatsapp/intent/backfill` | owner | 202 `{job_id}`: the `intent.classify` job classifies signed inbound messages without an observation for the current version |

## Audit additions (2026-11-03)

| Route | Roles | Result |
|---|---|---|
| `POST /api/v1/integrations/whatsapp/inbox/requeue` | owner | `{requeued: n}`: parked (`failed`) inbound items back to `pending` (at most 1,000), plus a processing job; audited |

- **Webhook:** a signed body over the item limits → **413** `payload_invalid`, nothing stored. The unmapped quarantine reason is `webhook_unmapped`.
- **Error taxonomy:** `app/whatsapp/contracts.py` `ERROR_TAXONOMY` / `ProviderError` maps every Batch 08 §4 error class to a safe HTTP status and a retry class (`never`, `after_backoff`, `manual_investigation`). `provider_uncertain` is never retried blindly.
- **P5.3:** test sends record `simulated_transport`. Readiness counts only real-network sends as WATEST-10 evidence.
- **P5.5 pilot:**
  - after the reservation it re-reads the pilot status (pause or revoke) and the connection, as well as the stop and the live gate;
  - `provider_auth` or `provider_quota` automatically pauses the pilot (`pause_reason: provider_error`) until an owner resumes it.
- **P4.3 contacts:** creating a contact whose number is an active WhatsApp test recipient → 409.
