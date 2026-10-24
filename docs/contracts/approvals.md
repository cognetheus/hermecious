# Approval Studio contract (P4.4)

Decision record: [ADR-023](../adr/ADR-023-content-approval-studio.md). Code: `apps/api/app/approvals/` and the edit path in `apps/api/app/drafts/`. UI: the Draft Studio page, `/campaigns/{id}/accounts/{account_id}`.

> **Content approval only — simulation only.** It is never consent, never queued, never sent and never a WhatsApp template approval. Every receipt has `simulation_only: true`.

## Endpoints

All commands require owner or operator, CSRF and an `idempotency_key`. Replays return 200 with `replayed: true`; the same key with a different request returns 409. Other organizations get 404.

| Route | Behaviour |
|---|---|
| `POST /api/v1/drafts/{id}/revisions` | `{edited_text, reason, expected_revision}`. 201 with a new revision (`origin: edited`). 409 if `expected_revision` is not the latest or the draft is blocked. 422 `UNGROUNDED_TEXT: <fragment>`, `DUPLICATE_SENTENCE`, `UNCHANGED` or `VALIDATION_FAILED: …` |
| `POST /api/v1/drafts/{id}/approve` | `{content_digest, contact_id, template_ref, reason}`. 201 receipt. 422 `NO_CONTACT_SELECTED`, `NO_TEMPLATE_SELECTED` or `CONTACT_NOT_FOR_ACCOUNT`. 409 on a digest mismatch, `cannot approve: <reasons>`, `not simulation-eligible: <P4.3 codes>`, an already-approved or rejected revision, or a concurrent reviewer |
| `POST /api/v1/drafts/{id}/reject` | `{content_digest, reason}`. 409 while approved (revoke first) or if already rejected |
| `POST /api/v1/drafts/{id}/revoke-approval` | `{approval_id, reason}`. Only the current approval; otherwise 409 |
| `GET /api/v1/drafts/{id}/reviews` | Any role: `{status, items: [receipt, newest first]}` |
| `GET /api/v1/drafts/{id}` and the drafts list | Also return `content_digest`, `origin`, `latest` and `approval` (the computed status) |

## Computed status (synthetic example)

```json
{
  "state": "approval_stale",
  "stale_reasons": ["campaign_changed", "campaign_paused"],
  "review": {
    "decision": "approved_content",
    "draft_revision": 2,
    "content_digest": "<64 hex>",
    "contact_id": "…",
    "template_ref": "fx_tpl_marketing_intro_v1",
    "eligibility_decision": "allow_for_simulation",
    "reason": "Grounded and polite",
    "expires_at": "…",
    "version_vector": {"campaign_revision": 1, "permission_revision": {"id": "…", "version": 2}, "policy_version": "eligibility-policy-1.0"}
  },
  "simulation_only": true,
  "queued": false,
  "sent": false,
  "whatsapp_template_approved": false,
  "production_ready": false
}
```

`state` is one of `not_reviewed`, `approved_content`, `approval_stale`, `rejected` or `revoked`.

### Stale reasons

| Source | Codes |
|---|---|
| Approval | `approval_expired` (7 days), `newer_revision_exists`, `campaign_changed`, `permission_changed`, `production_approval_unavailable` |
| Draft Studio | `campaign_paused`, `excluded`, `evidence_changed`, `offer_not_published`, `cited_fact_*`, … |
| Grounding | `grounding_changed_*`, `verifier_*` |
| P4.3 eligibility | `eligibility_<P4.3 code>` |

## Sample synthetic revision lineage

1. **Revision 1:** `generated` (introduction template).
2. **Revision 2:** `edited`, "Shorter, no observation". The observation sentence is dropped, so the content digest changes.
3. **Revision 2 receipts:** seq 1 `approved_content` (contact `+92 ••••••• 102`, `fx_tpl_marketing_intro_v1`).
4. **After the campaign is paused:** status `approval_stale` (`campaign_paused`, `campaign_changed`).

Revision 1's earlier approval, if any, reads `newer_revision_exists` forever.
