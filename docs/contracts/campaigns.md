# Campaigns contract (P4.1)

Decision record: [ADR-020](../adr/ADR-020-campaign-planning.md). Code: `apps/api/app/campaigns/`. UI: `/campaigns`.

> **Channel permission not checked — do not contact from this screen.** Every response carries `notice`. Approvals carry `contact_authorized: false`.

## Endpoints

| Route | Roles | Behaviour |
|---|---|---|
| `POST /api/v1/campaigns` | owner, operator (CSRF) | `{name, offer_id, mode: live\|fixture, district?, rules?, budgets?}`. The offer must be published (409 otherwise). `fixture` is refused in production |
| `GET /api/v1/campaigns[/{id}]` | any | Campaign detail: members (with `stale` and `drafting_blocked`), usage and `approval_blocked_reason` |
| `PATCH /api/v1/campaigns/{id}` | owner, operator (CSRF) | `{expected_revision, name?, rules?, budgets?, repin_offer?}` |
| `GET /api/v1/campaigns/{id}/preview?limit≤30&cursor&digest` | any | `{preview_digest, total, qualifying, items[{account_id, qualifies, reasons, decision, dimensions, stage, item_digest}], approval_blocked_reason}` |
| `POST /api/v1/campaigns/{id}/activate`, `/pause`, `/cancel` | owner, operator (CSRF) | `{expected_revision}` |
| `POST /api/v1/campaigns/{id}/candidates/{account_id}/approve` | owner, operator (CSRF) | `{expected_revision, item_digest, idempotency_key, reason?}`. Responses: 409 for a closed gate, a stale preview, a paused campaign, an excluded account, a used-up budget or an unpublished offer |
| `POST /api/v1/campaigns/{id}/candidates/{account_id}/exclude` | owner, operator (CSRF) | `{reason, idempotency_key}`. Always wins |

## Rules shape (`campaign-rules-1.0`)

All fields are typed; extra fields give 422.

| Field | Values | Default |
|---|---|---|
| `decisions` | `contact_now`, `investigate` | `["contact_now"]` |
| `minimums` | per dimension: `strong`, `moderate` or `weak` (never `unknown`) | none |
| `localities_include`, `localities_exclude` | ≤20 plain names each | empty |
| `exclude_account_ids` | ≤100 | empty |
