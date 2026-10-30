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
