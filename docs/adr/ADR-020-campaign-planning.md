# ADR-020: Campaigns are internal planning bound to a published offer; approval is for drafting review only and is gated by evidence quality

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" after reviewing the audit; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-24
- **Source:** `OPUS_P4.1_PROMPT.md`; blueprint §4 P4.1. Batch 06 is absent from the repository.

## Decision

### 1. Campaign

Each campaign records:
- an organization, a name, schools in Lahore, and an optional district;
- a **pinned published offer revision** and its capability version;
- typed `campaign-rules-1.0` target rules: an allowlisted structure covering decisions, per-dimension minimums, localities and explicit exclusions; no expressions;
- downward-only local budgets: preview ≤30, approvals ≤10 per day, drafts ≤10 per day;
- a revision number;
- a mode, `live` or `fixture`.

**Status transitions:**

| Transition | Rule |
|---|---|
| `draft → active` | Live campaigns only, with the evidence-quality gate open and the offer still published |
| `active ↔ paused` | Pausing from `draft` or `active`; resuming re-checks the gate |
| any → `cancelled` | Terminal |

`active` means internal planning only.

### 2. Preview

The preview is a pure read and writes nothing. It covers every school account in the organization (up to 500), each evaluated with explicit reasons:

| Area | Reasons |
|---|---|
| Assessment | `unassessed`, `stale_assessment`, `assessed_against_other_offer`, `decision_*`, `below_minimum:<dimension>` (unknown never meets a minimum) |
| Account | `other_city`, `account_archived` |
| Provenance and mode | `synthetic_account` / `unsourced_account` (live mode); `real_account_in_fixture_campaign` (fixture mode) |
| Targeting | `manually_excluded`, `locality_*`, `beyond_preview_limit` |

Ordering is stable. Each item carries an `item_digest`, and the preview as a whole carries a digest; paging with a stale digest gives 409.

### 3. Membership

- **`approve`:** "approved for drafting", **never contact authorization** (`contact_authorized: false`).
  - Requires `expected_revision` and the previewed `item_digest`, plus an idempotency key; a reused key with a different payload gives 409.
  - Re-evaluated under the campaign lock: the campaign must be draft or active, the gate open (live mode) or the environment non-production (fixture mode), the offer still published, and the account still qualifying.
  - Consumes one unit of the atomic Asia/Karachi-day approval budget.
  - **Concurrent approvals converge.** An existing membership is checked first, and no budget is consumed again.
- **`exclude`:** always allowed, overrides an earlier approval, and **always wins** (a later approve gives 409).
- **Staleness:** approved members whose rules, offer, assessment or evidence changed are marked `stale` and `drafting_blocked` (P4.2 must honour this).

### 4. Budgets

`campaign_daily_usage` counters run on Asia/Karachi days, using an atomic `UPDATE … WHERE used < limit`. These are not channel limits.

### 5. Fixture mode

Fixture campaigns exist so P4.x can be built while the real P3.4 gate is closed.
- They are refused in production.
- They take synthetic accounts only and never activate.
- They are labelled test-only everywhere.

## Consequences

**No real (live) candidate can be approved anywhere until EVAL-07 passes.**

## Rollback

- **Stop:** pause or cancel campaigns.
- **Keep:** the history and the append-only command ledger.
- **Schema:** downgrade 0014 only on a disposable database.
