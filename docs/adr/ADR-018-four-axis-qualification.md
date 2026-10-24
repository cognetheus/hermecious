# ADR-018: Qualification is four separate ordinal dimensions with fixed precedence; contact_now is a research priority only

- **Status:** Accepted
- **Date:** 2026-10-24
- **Source:** `OPUS_P3.3_PROMPT.md`; blueprint §4 P3.3. Batch 05 is absent from the repository (see the ledger).

## Decision

### 1. Rubric `school-qualification-1.0`

`app/qualification/rubric.py` is pure. Each dimension is `strong`, `moderate`, `weak` or `unknown` and carries a reason, cited fact ids and open questions. `unknown` (no evidence) is never `weak`.

**`customer_fit`**

| Value | When |
|---|---|
| `weak` | A cited source states a chain campus whose decisions sit with a head office (central mandate) |
| `unknown` | Sources disagree on size |
| `strong` | A cited source states ≥2 campuses or ≥2 levels |
| `moderate` | Any observed operations signal |
| `unknown` | Otherwise |

**`need_evidence`** (reasons always say "workload evidence, not a confirmed problem or purchase intent")

| Value | When |
|---|---|
| `strong` | Two or more observed areas, including operational complexity |
| `moderate` | One observed area |
| `weak` | Only hypotheses |
| `unknown` | Otherwise |

**`accessibility`** (a route is never permission to send marketing)

| Value | When |
|---|---|
| `weak` | Decisions sit with a head office |
| `strong` | A form or email route plus a cited owner or principal as decision maker |
| `moderate` | A form or email route only |
| `weak` | Only a generic phone number or social page |
| `unknown` | Otherwise |

**`delivery_fit`** (no invented capabilities)

| Value | When |
|---|---|
| `unknown` | No offer |
| `weak` | The offer is unpublished, for another vertical, or has no sales-approved capability |
| `strong` | A published capability (mapped by code) matches an observed area |
| `moderate` | A published offer with no matching area |

### 2. Precedence

1. `exclude` only on a current, auditable `hard_disqualifier` fact (new P1.2 claim type).
2. `nurture` only on a current, auditable `review_deferral` whose `until` date is still in the future (new P1.2 claim type). No reminder is created.
3. `contact_now` only if fit, need and access are each ≥ moderate, delivery is strong, no P3.2 key is conflicting or has stale facts, and no unverified possible disqualifier exists.
4. Otherwise `investigate`, listing what blocks `contact_now`.

There is no percentage and no composite. `channel_eligibility` is always `not_evaluated` (a database check enforces it). The UI reads: "Research priority: contact candidate — channel eligibility not checked."

### 3. Persistence (migration 0012, `assessments`)

- **Append-only revisions** per account, numbered under an account row lock.
- **Each revision records:**
  - origin (`rubric` or `override`);
  - the four dimensions and the decision;
  - rubric version and input digest;
  - the P3.2 snapshot id;
  - offer id, published revision id and capability version;
  - the machine explanation and questions.

**`POST /accounts/{id}/assess`:**
- It first refreshes the P3.2 brief.
- It adds a revision only when the input digest changes; otherwise it returns the latest revision (machine or reviewer). The digest covers the brief digest, the offer's published revision and capabilities, and deferral validity.
- Reads flag `needs_reassessment`.

### 4. Override

`POST /accounts/{id}/assessments/{assessment_id}/override` (owner or operator, CSRF).

**Requires:**
- the latest assessment id and `expected_revision`, otherwise 409;
- a reason;
- typed changes to the decision or dimensions (extra fields give 422; no change gives 400);
- evidence ids that are current facts of the account.

**Refused:** any decision other than `exclude` while a cited hard disqualifier exists (409).

**Effect:** a new revision that keeps the machine explanation and machine values, with an `account.assessment_overridden` audit holding before and after values.

## Consequences

Accuracy is an **unmeasured hypothesis** until P3.4's evaluation. The synthetic fixtures prove only the rules.

## Rollback

- **Stop:** stop assessing.
- **Keep:** assessments are history.
- **Rubric changes:** require a new version.
- **Schema:** downgrade 0012 only on a disposable database.
