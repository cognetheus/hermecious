# ADR-016: Research reads only associated, rights-checked sources by key; deterministic rules propose claims; reviewers create facts

- **Status:** Proposed — implemented and verified, awaiting owner acceptance (an agent may not accept its own ADR; AGENTS.md)
- **Date:** 2026-10-24
- **Source:** `OPUS_P3.1_PROMPT.md`; blueprint §4 P3.1. The prompt's `docs/phases/HERMECIOUS_BATCH_05_P3.1-P3.3.md` was **not present** in the repository, so the prompt and blueprint are the specification; see the ledger.

## Decision

### 1. Inputs

A run names 1–5 `source_records` already **associated** with the account:
- through an admitted listing (P2.4 `candidate_account_links`);
- through alias provenance; or
- through an existing fact's source.

There are no URLs, hostnames or queries; the server rejects unknown fields. The account must exist in the caller's organization and not be archived.

### 2. Rights

`ineligibility()` is checked at scheduling, at worker execution (per source), at review and at rendering. It rejects:
- expired provenance;
- unknown or forbidden provider rights, or a URL that fails the P1.2 screen;
- `metadata_only` sources (`metadata_only_no_content`);
- providers without a reviewed, fetch-licensed descriptor (`live_fetch_not_authorized`), such as first-party websites;
- a descriptor that is disabled or wrong for the environment;
- a rights-version mismatch.

### 3. Fetch

Documents come from a `DocumentFetcher` keyed by `(provider, external_key)`. Only `FixtureDocumentFetcher` exists: synthetic pages for the fixture provider, with no network. **Live website research is not implemented and fails closed** until a source is rights-reviewed under a future ADR. P2.2's pinned egress client would be the only allowed transport.

### 4. Documents

**Refused:**
- compressed bodies (never decompressed, so no compression bombs);
- non-`text/html`/`text/plain` media (PDF, images, SVG);
- bodies over 2 MiB;
- invalid UTF-8;
- bodies with no visible text.

**Normalization:** HTML is reduced to visible text. Scripts, styles, templates, iframes and comments are dropped; control and bidi characters are removed; NFKC is applied.

**Budgets:** 60 000 normalized characters per run, 30 s per source and 60 s per run. Text exists only in memory; observations keep a SHA-256 hash and counts.

### 5. Extraction (`rules-1.0`; `rules-1.1` after the 2026-10-25 audit: "online admission form" only when "online" qualifies the admission)

- **Rules:** sentence-level English and Urdu rules over P1.2 claim types only:
  - admissions process;
  - fee voucher or bank challan process;
  - explicit campus count;
  - public contact *channel* (never the address or number);
  - parent or student portal mentioned;
  - results online.
- **Locators:** each claim has an exact `[start, end)` locator into the normalized text, plus the span's SHA-256.
- **Verification:** an independent verifier re-derives the claim from the span alone.
- **Abstention:** negated statements and instruction-like text are skipped and counted. The rules never assert software, ownership, decision authority or need, and absence produces nothing.
- **Limits:** at most 25 claims per run.
- **No model:** no ModelGateway is configured, so there is no model path.
- **Not covered:** affiliation and expansion have no P1.2 claim type, so they are not extracted.

### 6. Excerpts

Excerpt text is stored only for `full_allowed` sources (enforced by a database check), with emails and long numbers masked. `derived_only` sources keep the locator and hash only.

### 7. Review

Accept or reject, with a reason, `expected_version` and an idempotency key.
- **Accept** re-checks rights and creates one P1.4 `source_supported` fact with the reviewer's confidence, the source, and the excerpt if stored. If an identical current fact from the same source exists, the claim links to it instead.
- **Concurrency:** racing reviews give one success and one 409.

### 8. Durability

`research.run` v1 job and outbox, committed with the run.
- **Per-source effects** are idempotent: one observation per `(run, source)`, and claims unique on `(observation, type, span)`.
- **The terminal state** is written under the fenced job completion.
- **Cancellation** is cooperative and checked before each source.
- **Failure handling:** errors retry up to 3 attempts, after which the run is `failed`.

## Consequences

- **Real research is BLOCKED** until a website source is reviewed. Fixture runs prove the pipeline only, not that live sites are accessible.
- **Recall is low by design;** unknowns stay unknown.

## Rollback

- **Stop:** stop scheduling runs, or remove the fetcher.
- **Keep:** runs, claims and facts are retained. Facts are corrected through the P1.4 chain.
- **Schema:** downgrade 0010 only on a disposable database.
