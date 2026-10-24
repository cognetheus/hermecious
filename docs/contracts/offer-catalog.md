# Offer catalog contract (P1.3)

Hermecious must know what the products can actually do, what is only planned, and which statements the owner has authorized for sales. A sales draft must never turn a brainstorm into a promise.

Code: `apps/api/app/offers/`. Migration `0004`. UI: `/offers`, `/offers/{id}`.

## Model

| Table | Purpose |
|---|---|
| `offers` | One sellable offer per `(organization_id, code)`, under a vertical (`schools`). `status` is draft, published or archived. `version` is the optimistic-concurrency counter. It holds pointers to `current_draft_revision_id` and `published_revision_id`, both organization-scoped composite FKs |
| `offer_revisions` | **Append-only** content snapshots, numbered `revision` 1, 2, … per offer. `state` is draft, published or retired. `content_sha256` is the SHA-256 of the canonical JSON content. Creator and approver are organization-scoped user FKs, and approval timestamps are recorded |

**Immutability is enforced by the database.** Trigger `offer_revisions_immutable` refuses:
- `DELETE`;
- any change to content columns or the digest;
- approval fields changing outside publication;
- any state transition other than `draft → published`, `draft → retired` (superseded or archived) or `published → retired`.

Edits always create a new revision. A CHECK requires published and retired-after-publish rows to carry `approved_by`, `approved_at` and `published_at`.

## Revision content (`RevisionContent`, strict, `extra="forbid"`)

```json
{
  "capability_version": "build-2026-10-20",
  "capability_matrix": [
    {
      "capability_code": "fee_tracking",
      "summary": "Tracks school fee payments",
      "readiness": "available",
      "approved_for_sales": true,
      "evidence_refs": ["internal-demo:fees-2026-10"],
      "limitations": ["Manual import only"],
      "approval_note": "Demoed against reviewed build"
    }
  ],
  "price_rules": [],
  "exclusions": ["Payroll is not included"],
  "dependencies": ["School provides a fee schedule spreadsheet"],
  "evidence_references": [
    {"ref": "internal-demo:fees-2026-10", "type": "internal-demo", "recorded_at": "2026-10-20T10:00:00Z",
     "description": "Fee tracking demoed against a reviewed build"}
  ]
}
```

- **`readiness`** ∈ `available`, `limited`, `planned`, `unverified`, `not_supported`. The internal matrix may hold any of them.
- **`capability_code`** must match `^[a-z][a-z0-9_]{2,63}$` and be unique within a revision. Ambiguous names such as "Fee Tracking" are rejected.
- **Evidence** is a stable internal reference `type:identifier` with `type` ∈ `internal-demo`, `repo`, `release-note`, `owner-review`, plus a timestamp and description. A plain URL is not accepted as proof. Every reference a claim or price uses must be listed in `evidence_references`. Proof material must not contain student or customer personal data.
- **Text fields** are plain text: no markup (`<`, `>`), no control or bidi characters, and bounded lengths. The UI renders them escaped.
- **`price_rules`**: `code`, `description`, `currency` (`PKR` only), `amount` (> 0, at most 2 decimals), `unit` ∈ `per_student_month`, `per_campus_month`, `per_year`, `one_time`, `approved`, `evidence_ref`.

## Publication rules (owner only, `assert_publishable`)

A revision publishes only if **all** of these hold. Otherwise the request gets 400 and nothing changes:

1. It is the offer's current draft and its stored content still matches `content_sha256`.
2. At least one claim is `approved_for_sales`.
3. Every approved claim:
   - has readiness `available`, or `limited` with at least one limitation;
   - has at least one evidence reference and an `approval_note`;
   - contains **no invented commitments**: delivery timing ("within 2 weeks", "go-live", "delivered in"), SLAs or uptime, guarantees, or "integrates with …".
4. Every price rule is `approved` with an `evidence_ref`, and contains no commitment text.

**Absence of approved prices means `pricing_unavailable`, never a number.**

## State machine and concurrency

| Action | Who | Effect |
|---|---|---|
| `POST /api/v1/offers` | owner, operator | New `draft` offer (`code` unique per org → 409 on duplicate) |
| `POST /api/v1/offers/{id}/revisions` `{expected_version, content}` | owner, operator | New draft revision `n+1`. The previous unpublished draft becomes `retired` |
| `POST /api/v1/offers/{id}/publish` `{revision, expected_version}` | **owner** (+ CSRF) | The draft becomes `published` with approver and timestamps. The previous published revision becomes `retired`. `offer.status = published` |
| `POST /api/v1/offers/{id}/archive` `{expected_version}` | **owner** (+ CSRF) | `offer.status = archived`. The published revision and any draft become `retired`. History is kept. Archived offers accept no further revisions or publication (409) |
| `GET /api/v1/offers`, `GET /api/v1/offers/{id}` | all roles | Observers see only revisions that were actually published |
| `GET /api/v1/offers/{id}/sales-ready` | all roles | See below |

Every change locks the offer row (`SELECT … FOR UPDATE`) and compares `expected_version`. A stale writer gets **409** "Offer was changed by someone else; reload and retry", so two publishers can never produce a mismatched `published_revision_id`. Another organization's offer always looks like **404**.

## Sales-ready projection (the only interface for later generators)

`GET /api/v1/offers/{id}/sales-ready` returns **409** `Offer has no published, sellable revision` unless the offer is `published` and its published revision is in state `published`. On success:

```json
{
  "offer_id": "…", "code": "school_fees_pro", "audience": "…",
  "revision_id": "…", "revision": 2, "content_sha256": "…", "capability_version": "…", "published_at": "…",
  "claims": [{"capability_code": "fee_tracking", "summary": "…", "readiness": "available",
              "limitations": [], "evidence_refs": ["internal-demo:fees-2026-10"]}],
  "exclusions": ["…"], "dependencies": ["…"],
  "pricing": {"status": "pricing_unavailable"}
}
```

It contains only approved claims from the published snapshot. Planned, unverified and not-supported capabilities, approval notes and draft content never appear.

### Integration contract for P4 (message drafting) and P6 (conversation replies). Not implemented here.

- Generators and models consume **only** this projection, never `capability_matrix` or drafts.
- Every generated draft records `(revision_id, content_sha256)`. Before sending, P4/P6 must re-read sales-ready and **invalidate** the draft if the offer is archived (409), or if `revision_id` or `content_sha256` no longer match (superseded).
- When `pricing.status` is `pricing_unavailable`, messages must not state or imply any price; price questions are escalated to a human.
- Claims are quoted from `summary` and `limitations` as-is. Generators must not add timelines, integrations, guarantees or capabilities.

## Default seed

`docker compose run --rm --no-deps api python -m app.offers.seed` creates, once, an **unpublished** `school_admin_starter` draft for the single active owner's organization:
- candidate modules `admissions_intake`, `fee_tracking`, `student_records` and `reporting`, all `unverified`;
- nothing approved for sales, no evidence and no prices.

The seed cannot be published as-is. The owner must add evidence-backed claims in a new revision.

## Rollback

On a disposable database, `alembic downgrade 0003` removes the offer tables, the trigger and the additive `users` constraint. On data-bearing databases, published revisions are historical approvals: back up and prefer a forward repair. **Never erase approved revisions** to simplify a deployment.
