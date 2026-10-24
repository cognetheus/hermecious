# Channel eligibility contract (P4.3)

Decision record: [ADR-022](../adr/ADR-022-channel-eligibility-policy.md). Code: `apps/api/app/contacts/` and `apps/api/app/eligibility/`. UI: `/accounts/{id}/contacts`.

> **Simulation eligibility only — sending disabled.** Every decision has `live_send_authorized: false` and `reusable: false`. A decision is a reading at `evaluated_at`, never an authorization.

## Endpoints

All mutations need a session, CSRF and an `idempotency_key`. Replays return 200 with `replayed: true`; the same key with a different request returns 409. Other organizations get 404.

| Route | Roles | Behaviour |
|---|---|---|
| `POST /api/v1/accounts/{aid}/contacts` | owner, operator | `{address, role, idempotency_key}`. Stores only a keyed digest and a masked hint. 422 `INVALID_ADDRESS`; 409 if the number is already a contact in the organization; 503 if no contact key is configured |
| `GET /api/v1/accounts/{aid}/contacts`, `GET /api/v1/contacts/{id}` | any | Masked view. Observers see each permission's `id, purpose, channel, status, version, expires_at` only |
| `GET /api/v1/contacts/{id}/permissions` | any | `{items, suppressed}` (same masking) |
| `POST /api/v1/contacts/{id}/permissions` | owner, operator | Records **pending** evidence (below). 422 `EVIDENCE_REJECTED: <problems>`. Supersedes the open row for the same purpose |
| `POST /api/v1/contacts/{id}/permissions/{pid}/verify` | **owner only** | `{decision: verified\|rejected, reason, expected_version, idempotency_key}`. The recorder cannot verify (403). 409 if not pending or the version changed. 422 if a re-check fails (`expired`, `suppressed`, …) |
| `POST /api/v1/contacts/{id}/permissions/{pid}/revoke` | owner, operator | `{reason, expected_version, idempotency_key}` |
| `POST /api/v1/contacts/{id}/suppress` | owner, operator | `{reason: opt_out\|complaint\|owner_request\|wrong_number, idempotency_key}`. Org-wide and permanent; repeats converge |
| `POST /api/v1/channel-eligibility/evaluate` | owner, operator | `{contact_id, channel: "whatsapp", purpose: marketing\|utility\|service_reply, campaign_id?, template_ref?, inbound_ref?}` (below) |
| `GET /api/v1/channel-eligibility/policy` | any | Policy version, named business, current consent wording versions and the fixture catalogue (empty in production) |

## Evidence request (synthetic example)

```json
{
  "purpose": "marketing",
  "business_name": "CoderzHunt",
  "capture_method": "signed_paper_form",
  "consent_wording_version": "optin-whatsapp-marketing-en-PK-v1",
  "proof_kind": "form_serial",
  "proof_reference": "FORM-SYN-0001",
  "captured_at": "2026-10-13T12:00:00+05:00",
  "idempotency_key": "evidence-0001"
}
```

- `capture_method` is one of `signed_paper_form`, `web_form_checkbox`, `whatsapp_opt_in_reply` or `recorded_call`.
- `proof_kind` is one of `form_serial`, `web_submission_id`, `message_id` or `call_recording_id`.
- The utility wording is `optin-whatsapp-utility-en-PK-v1`.

## Decision response (synthetic example)

```json
{
  "decision": "deny",
  "reasons": [{"code": "no_opt_in_permission", "explanation": "No opt-in is on record. A public phone number is not permission."}],
  "channel": "whatsapp",
  "purpose": "marketing",
  "contact_id": "…",
  "address": "+92 ••••••• 101",
  "campaign_id": "…",
  "policy_version": "eligibility-policy-1.0",
  "permission_revision": null,
  "suppression_revision": 0,
  "evaluated_at": "2026-10-23T07:00:00+00:00",
  "next_window_at": null,
  "input_digest": "<64 hex>",
  "live_send_authorized": false,
  "reusable": false,
  "notice": "Simulation eligibility only — sending disabled"
}
```

## Reason codes, in precedence order

| Stage | Codes |
|---|---|
| 1. Stop | `kill_switch_engaged`, `campaign_paused`, `campaign_cancelled` |
| 2. Suppression | `suppressed` |
| 3. Opt-in | `no_opt_in_permission`, `permission_unverified`, `permission_revoked`, `purpose_not_covered` |
| 4–5. Scope and freshness | `wrong_business`, `permission_expired`, `proof_future_dated`, `proof_stale`, `consent_wording_outdated` |
| 6. Template or window | `template_missing`, `template_unverified`, `template_rejected`, `template_wrong_category`, `fixture_requires_synthetic_account_outside_production`, `no_inbound_context`, `inbound_context_mismatch`, `inbound_context_invalid`, `service_window_closed` |
| 7. Campaign and gate | `campaign_required`, `not_approved_for_drafting`, `excluded`, `evidence_quality_gate_closed`, `rules_changed`, `offer_changed`, `offer_not_published`, `assessment_superseded`, `evidence_changed` |
| 8. Owner | `no_active_human_owner` |
| 9. Defer only | `outside_business_hours` (Mon–Sat 09:00–18:00 Asia/Karachi), `daily_cap_reached` (20 per organization per day), `contact_frequency_cap` (7 days) |

## Synthetic fixtures (signed; non-production; synthetic accounts only)

- **Templates:**
  - `fx_tpl_marketing_intro_v1` (marketing, approved);
  - `fx_tpl_utility_update_v1` (utility, approved);
  - `fx_tpl_marketing_pending_v1` (pending);
  - `fx_tpl_marketing_rejected_v1` (rejected).
- **Inbound messages:**
  - `fx_inbound_hello_v1` ("hello" from `+92 000 0000101` at 2026-10-23T05:00Z);
  - `fx_inbound_fee_question_v1` (from `+92 000 0000102`).

The numbers are zero-filled placeholders.
