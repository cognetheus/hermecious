# ADR-019: Evidence quality is measured on frozen, human-adjudicated samples; the enrollment gate is fail-closed

- **Status:** Accepted
- **Date:** 2026-10-24
- **Source:** `OPUS_P3.4_PROMPT.md`; blueprint §4 P3.4. **Batch 06 (`HERMECIOUS_BATCH_06_P3.4-P4.2.md`) is absent from the repository.**

## Decision

### 1. Definition: displayed factual claim

Everything the product currently shows **as fact** for an account:
- every current `source_supported` fact (the account's Evidence section);
- every P3.2 brief statement whose state is `observed` or `conflicting`;
- every P3.3 assessment dimension shown as `strong` or `moderate` (its reason asserts evidence).

Hypotheses, unknowns and discovery questions are labelled unverified on screen and are not claims. A hypothesis cannot carry an assertion into the Evidence section, because only `source_supported` facts appear there.

### 2. Sample

| Step | Rule |
|---|---|
| Eligible accounts | Non-archived Lahore school accounts |
| Order | `sha256(seed:account_id)` ascending |
| Size | The first 30 distinct accounts (campus key: normalized name and locality) |
| Provenance | `real` (only non-fixture sources); `synthetic` (fixture provider or a "(Synthetic)" name); or `unsourced` (excluded) |
| Corpus status | `SYNTHETIC_CORPUS` if any synthetic account is included (allowed outside production only); `INSUFFICIENT_CORPUS` if fewer than 30 real; otherwise `OK` |

The run stores the seed, the method, the account ids, the excluded accounts with reasons, and a fingerprint over the frozen items and their rights versions.

### 3. Items

Items are rights-safe summaries: claim type and value, or the statement, plus citations (https URL, provider, storage class, rights version, expiry). **No excerpts.**

### 4. Verdicts

- **Allowed verdicts:** `supported`, `unsupported`, `contradicted`, `stale` or `unverifiable`.
- **Who:** owners and operators only, with CSRF and a version check.
- **History:** append-only revisions with reviewer id and reason.
- **When `supported` is refused (409):** if the cited evidence is not currently usable (expired, metadata-only, superseded) or is contradicted.

### 5. Metric

**supported / all items.** Supported items whose evidence lapsed before finalization do not count.

`decide_result` returns:

| Result | When |
|---|---|
| `BLOCKED` | Corpus status is not `OK` |
| `FAILED` | 0/0 |
| `FAILED` | Below 90% (integer arithmetic) |
| `FAILED` | Any failed item still displayed as fact |
| `PASSED` | Otherwise |

Finalization is refused while items are unreviewed (the state reads `INCOMPLETE`). A replay returns the finalized run.

### 6. Remediation

- **Facts:** a failed fact is withdrawn through the **P1.4 correction chain**, demoted to hypothesis with unknown confidence. The reason cites the evaluation, and an append-only link records which correction it was. The resulting P3.2 and P3.3 digest changes flag reassessment.
- **Derived statements:** they follow once the brief and assessment are regenerated.
- **Post-remediation run:** a `post_remediation` run reuses the baseline's accounts. The baseline's verdicts and result are never rewritten.

### 7. Gate

`GET /api/v1/evidence-evals/gate` reports `enrollment_allowed: true` only when the latest finalized run is `PASSED` with corpus `OK`. Otherwise it reports `CLOSED` with the reason. P4.1 must consult it.

## Consequences

The production quality claim requires a real 30-account audit by a person (EVAL-07). Fixture and mechanism tests never satisfy it.

## Rollback

- **Stop:** stop creating evaluations. The gate stays closed (fail-closed).
- **Keep:** runs, verdicts and remediation links are retained.
- **Schema:** downgrade 0013 only on a disposable database.
