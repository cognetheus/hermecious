# ADR-017: School operations brief is a pinned, pure rubric over current cited facts, stored as immutable snapshots

- **Status:** Proposed — implemented and verified, awaiting owner acceptance (an agent may not accept its own ADR; AGENTS.md)
- **Date:** 2026-10-24
- **Source:** `OPUS_P3.2_PROMPT.md`; blueprint §4 P3.2. Batch 05 is absent from the repository (see the ledger).

## Decision

### 1. Rubric `school-signals-1.0`

The rubric (`app/signals/rubric.py`) is pure and deterministic, with no model calls. It has exactly six keys, in this order:

| Key | Built from |
|---|---|
| `campus_footprint` | `campus_count` |
| `operator_autonomy` | `ownership_type`, `decision_authority` |
| `admissions_workflow` | workflow signal, area `admissions` |
| `fee_process` | workflow signal, area `fees` |
| `public_contact_route` | `public_contact_channel` |
| `operational_complexity` | student records, reporting and communication signals; `school_levels`; `software_in_use` only when a product is observed |

### 2. Inputs

The inputs are the account's **current** P1.4 facts (not superseded) plus the number of active reviewed P2.3 links. Each fact is classified by its eligibility now:

| Eligibility | Meaning |
|---|---|
| `usable` | Source-supported, and the source is current and not metadata-only |
| `stale` | Source rights have expired |
| `unauditable` | A metadata-only citation |
| `hypothesis` | Not source-supported |
| `disputed` | Marked disputed |
| `rejected` | Ignored |

### 3. States

| State | When |
|---|---|
| `conflicting` | Usable facts disagree on an exclusive value (count, ownership, authority), or a disputed fact exists alongside usable ones. Every reference is kept, with no winner |
| `observed` | One or more usable facts |
| `hypothesis` | Only unverified, unauditable or disputed evidence |
| `unknown` | Nothing usable. Stale facts are listed for re-checking |

A reviewed listing count is shown as context and is **never** a campus count.

### 4. Wording

Statements are fixed templates; any operator-entered signal text is quoted as data. Each key carries a caveat; for example:
- published fee instructions do not show reconciliation;
- a public channel is not consent;
- complexity is not need or budget.

Each key also carries one respectful discovery question. Nothing scores, ranks or qualifies (`ranking: null`).

### 5. Snapshots (`school_signal_snapshots`, migration 0011)

- **Immutable:** append-only, enforced by a trigger.
- **Deduplicated:** unique on `(organization, account, rubric_version, input_digest)`. The input digest covers each fact's id, type, verification status and eligibility now, plus the link count, so a source's rights expiring is enough to make reassessment due.
- **Generation:** concurrent or replayed generation returns the same row (201 when created, 200 when replayed).
- **Reads:** reads report `needs_reassessment` when today's digest differs from the latest snapshot's.

### 6. API and UI

| Route | Access |
|---|---|
| `POST /api/v1/accounts/{id}/school-signals/generate` | owner, operator (CSRF) |
| `GET /api/v1/accounts/{id}/school-signals` (latest, history and flag) | every role |
| `GET /api/v1/school-signal-snapshots/{id}` | every role |

The account page's **School Research** section shows six cards: state, statement, caveat, citations with sanitized https links and rights expiry, freshness, and the discovery question.

## Consequences

- Most schools will be mostly `unknown` until research and review add cited facts. That is the intended honest default.
- **P3.3 must read these states as they are:** `unknown` is not "weak", and an observation is not need or intent.

## Rollback

- **Stop:** stop generating briefs.
- **Keep:** snapshots are history.
- **Rubric changes:** require a new version, under which old snapshots remain readable.
- **Schema:** downgrade 0011 only on a disposable database.
