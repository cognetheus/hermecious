# ADR-014: Campus identity is resolved by a deterministic matcher that only suggests; humans decide, and decisions are reversible

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" after reviewing the audit; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-24
- **Source:** Batch 04 §P2.3; `OPUS_P2.3_PROMPT.md`

## Context

P2.2 stages listings from more than one source: OpenStreetMap and operator CSV. The same physical school can appear twice, and different schools often share names: chains, franchises, numbered government schools, and Urdu versus English spellings. A wrong merge contaminates evidence and, later, consent. **An unresolved duplicate is cheaper than a wrong merge.**

## Decision

### 1. Identity

**An account is a physical campus or site, never a brand.**
- Chain and franchise campuses stay separate.
- A shared website domain is never evidence of one campus.
- Every comparison output carries `buying_authority: unknown`.

### 2. The only automatic outcome is `exact_reobservation`

This applies only to the same `(organization, provider, external_key)`. P2.2 staging already makes such a re-observation update one row, with `revision` and an audit holding the previous permitted values.

Every other pair produces one of three outcomes:
- `suggest_review`, which needs a human;
- `distinct`;
- `insufficient_evidence`.

### 3. Matcher `campus-match-1.0` (`app/resolution/matcher.py`)

The matcher is pure, deterministic and symmetric; it has no network or model calls.

**Normalisation:**
- NFKC, casefold, punctuation to spaces.
- Arabic-script diacritics removed; Arabic yeh, kaf and heh folded to their Urdu forms.
- **No transliteration.** Urdu and English are compared only within the same script.
- A "core" name drops only `the`, `school`, `schools` and `sch`.
- Original spellings are kept untouched.

**Branch marks:**
- numbers (including Roman numerals after `phase`, `sector` and similar words);
- the words around `campus`, `branch`, `block`, `phase`, `sector`, `town`, `wing`.

Differing numbers, or disjoint branch words, give `conflicting_branch`.

**Rules, in order:**

| Order | Condition | Outcome (reason) |
|---|---|---|
| 1 | Same provider and key | `exact_reobservation` |
| 2 | Different city | `distinct` |
| 3 | Missing city | `insufficient_evidence` |
| 4 | Branch conflict | `distinct` |
| 5 | Different locality | `distinct` |
| 6 | Points more than 0.5 km apart, or more than 2 km when either is an area centre | `distinct` (`coordinate_conflict`) |
| 7 | No same-script name pair | `insufficient_evidence` |
| 8 | Different names | `distinct`, unless two precise points are ≤50 m apart: then `suggest_review` (`co_located_different_names`) |
| 9 | Similar names (exact, or `SequenceMatcher` ≥ 0.88 on the core) | Decided in the next table |

**When names are similar:**

| Condition | Outcome (reason) |
|---|---|
| Shared domain, no locality or coordinates | `distinct` (`chain_without_site_evidence`) |
| Same provider, different ids | `insufficient_evidence` (`same_provider_distinct_ids`): the provider itself keeps them apart |
| Same locality | `suggest_review` |
| Precise points ≤150 m apart | `suggest_review` |
| Area centre nearby | `insufficient_evidence` (`area_center_ambiguous`) |
| Otherwise | `insufficient_evidence` (`locality_unknown`) |

**Features** are labels and scores only; no upstream text is stored in them.

**Blocking:** pairs are proposed only when they share a city and a core token. Blocks of more than 60 members are skipped and counted (`skipped_common_blocks`); this is a documented recall limit.

### 4. Persistence (migration 0008)

**`identity_suggestions`**
- One row per canonical pair (`left < right`, or candidate→account) per algorithm version, enforced by unique partial indexes.
- Holds features, reason codes, evidence source ids, candidate revisions, status and version.
- **Stored outcomes:** only `suggest_review` and `insufficient_evidence`; `distinct` is counted in the run report.

**Re-running the resolver**
- **Open** suggestions (pending or deferred) are recomputed when their evidence changes, or `superseded` when they become distinct.
- **Reviewed** suggestions are never rewritten. They get `evidence_changed_at` instead.

**`identity_decisions`** is append-only (the P1.4 trigger). It records:
- the command id, action, prior and next status, expected version and reason;
- the payload digest, held fact ids and link;
- `reverses_decision_id` and the request id.

**`candidate_account_links`** records reviewed candidate→account associations.
- At most one active link per candidate.
- Undo **ends** a link (`unlinked_at`/`unlinked_by`); it never deletes it.

All foreign keys are composite and organization-scoped.

### 5. Review commands (`POST /api/v1/identity/suggestions/{id}/decisions`; owner or operator, CSRF)

The body is `{command_id, action, expected_version, reason}`.

**Command handling:**
- The same `command_id` with the same payload replays the prior result.
- A reused `command_id` with a different payload gives 409.
- A stale version gives 409. The version is checked under a row lock, and again by a compare-and-swap `UPDATE`.

**Transitions:**

| From | Allowed actions |
|---|---|
| pending, undone | confirm, mark_distinct, defer |
| deferred | confirm, mark_distinct, undo |
| confirmed, distinct, reallocation_review | undo |

**Undo of a confirmed candidate→account link:**
- **Held facts:** current facts on the account (those not superseded) that cite the candidate's source record **and** were recorded after linking.
- **If any are held:** the status becomes `reallocation_review`, the held fact ids are recorded, and the link stays. Nothing is moved or orphaned.
- **To finish the undo:** correct those facts through the P1.4 correction chain, then undo again.

### 6. Running the resolver

`POST /api/v1/identity/resolve` (owner or operator) runs synchronously over the organization's non-rejected candidates and non-excluded accounts. P2.4 may call it from the discovery-run job.

## Consequences

- **Recall is deliberately low.** Many real duplicates will stay `insufficient_evidence` until a human looks. Accuracy is measured only on the 26-case gold set (zero automatic merges of different identities); no general accuracy claim is made.
- **Algorithm changes need a new version.** Changing the rules requires a new `ALGORITHM_VERSION`; old suggestions remain with their version.

## Rollback

- **Stop generating suggestions:** stop calling the resolve endpoint.
- **Keep the history:** all decisions and links are retained.
- **Revert behaviour:** use application-level compensation, by undoing decisions; never delete in cascades.
- **Schema:** downgrade 0008 only on a disposable database (rehearsed by the migration suite).
