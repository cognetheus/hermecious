# ADR-031: Deterministic `intent.v1` observations for human review, rules only

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-11-02
- **Source:** `docs/phases/OPUS_P6.1_PROMPT.md`, blueprint §4 P6.1 ("deterministic fixture evaluation"). The cited Batch 09 document is not in the repository.

## Context

The repository has no model gateway: drafts and research extraction are explicitly model-free. P5.5 is NO_GO, so P6.1 runs offline only and drives no automation. P5.2 keeps inbound text only when ADR-029 sealing is configured.

## Decision

1. **Contract `intent.v1`** (`app/intent/schema.py`). It is validated on the server before storage:
   - exactly ten primary intents, eight safety flags, ten read-only recommended actions;
   - the action must equal the fixed mapping for the primary label;
   - an opt-out must carry `explicit_opt_out`;
   - every evidence span must quote the message exactly;
   - extra fields (a probability, a score, an invented action) are rejected;
   - `model_version` and `prompt_version` are `null`, because no model is used.
2. **Classifier `intent-rules-1.0`** (`app/intent/classifier.py`). It is pure and deterministic:
   - **Folding:** text is folded for matching (NFKC, Cyrillic and Greek look-alikes, Arabic-to-Urdu letter forms, invisible and bidi controls removed). An index map anchors evidence to the original text.
   - **Patterns:** high-precision patterns cover English, Roman Urdu and Urdu script.
   - **Negation and quotation:** quoted, reported or negated stop words never count as an opt-out.
   - **Primary label:** chosen by a fixed precedence; safety flags are never dropped.
   - **Injection:** text addressed to the system is flagged, and its demo or contact requests are ignored.
   - **Default:** `ambiguous`.
   - **Unavailable content:** media, expired, not retained or unreadable content is `ambiguous`, with a `content_<state>` reason.
3. **Where it runs.**
   - Classification happens inside the P5.2 processor's transaction, in a **savepoint**. A classifier fault never loses the signed message.
   - The `intent.classify` job (owner-triggered backfill) classifies messages that lack an observation for the current version.
   - Only `provider_inbound_messages` (signed) are classified. Never P5.3/P5.5 outbound, P4.5 simulations, unmapped events or other organizations.
4. **Storage** (migration 0025, append-only):
   - **`intent_observations`:** unique per (organization, message, classifier version, source revision). Retries add nothing; a new version appends.
   - **`intent_reviews`:** the operator's confirmation or correction, audited and kept apart. It changes no observation, classifier, policy, consent or suppression, and is not used for training.
5. **Authority.** The classifier never suppresses or grants. The deterministic P5.2 STOP path and P4.3 remain the only suppression authority. An `explicit_opt_out` observation only asks a person to review (`request_opt_out_review`).
6. **UI.** The inbox timeline shows, for each inbound message:
   - label, secondary labels, flags, confidence, language;
   - the quoted evidence and the suggested next step, marked "nothing happens automatically";
   - the classifier version and "rules only, no model";
   - a review form.

   There is no sales score and no send control.

## Evaluation and quality gate

| Set | Provenance | Use | Result |
|---|---|---|---|
| `gold_v1` (121; EN 43, RU 37, UR 31, mixed 8, unknown 2) | written by the same agent that wrote the rules | behavioural regression; split by paraphrase cluster | held-out macro-F1 1.0. **Not a generalization measure** |
| `blind_v1` (72) | an independent agent that saw only the guidelines | measured once: macro-F1 **0.691**, 11 safety-flag misses, 0 false opt-outs; then used for rule development | consumed |
| `blind_v2` (80) | a second independent agent, guidelines only | **the held-out measurement**: macro-F1 **0.736**, accuracy 0.725, safety recall **13/19**, 0 false opt-outs | **BLOCKED_QUALITY** |

The targets (held-out macro-F1 ≥ 0.85 and 100% recall on clear opt-outs and human requests) are **not met** on independent data.

- None of the fixtures is human-reviewed, so INTENT-07's "human-reviewed gold" is not satisfied.
- **Promotion is blocked:** the feature stays a manual-review aid with no automation. Two orthographic safety fixes (`krna`, "call kar lena" / "کال کر لیں") were made after the `blind_v2` measurement and are not validated by it.
- **Next step:** a human annotator reviews the fixtures (`docs/intent/annotation-guidelines.md`), and a fresh blind set, ideally real de-identified replies, is measured.

## Consequences

- **Rollback:** observations are append-only and derived; to roll back, drop migration 0025 or stop showing them.
- **No PII leaves the server.** There is no remote model, and messages with possible sensitive data are flagged for redacted review.
- **Future models:** a semantic adapter (P6.2+) may append observations under a new classifier version, inside the same schema and allowlist, and only through a real gateway.
