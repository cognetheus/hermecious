# Hermecious — Opus 5.5 High — P2.1 Discovery SourceAdapter Framework (Offline Fixture)

**Run ONE subphase only: P2.1. STOP after verified or blocked.**

## Required reading

Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` (P2.1, shared contracts and Section 4.2), accepted ADRs, `AGENTS.md`/`CLAUDE.md`, `EXECUTION_LEDGER.md` and actual P1.2 source/fact rights policy, P1.4 account management and P1.5 job contracts. Inspect real API/persistence and fixtures before proposing files; do not invent path names.

## Preflight — hard stop if missing

1. Inspect `git status`, base SHA, migration head, source-rights schema, provider config, worker registry, source URLs validators and current test harness.
2. Verify executed ledger proof for **P0.1–P0.4 and P1.1–P1.5**. If ANY prerequisite is not VERIFIED, **STOP** with exact missing evidence and no speculative backfill.
3. Show small file-level design, DTOs/versioning, policy registry, budgets, pagination rules, storage rights, test fixtures and gate mapping **SOURCE-01…SOURCE-10**.

## Implement ONLY the P2.1 offline adapter slice

- Define typed SourceAdapter interface: `search(query, limit, cursor)` returns validated page/candidates; `fetch(source_key)` returns validated SourceObservation. If existing architecture insists on fetch(URL), restrict to registered provider hosts and no arbitrary external URLs; ADR rationale required.
- Define SourceDescriptor with terms/review reference, enabled flag, operation rights, retention/TTL, storage class, quota/limits and allowed-host policy. **Fail closed on unknown/unreviewed real provider.** Do not confuse public contact existence with messaging permission.
- Register ONE synthetic `fixture_lahore_schools` adapter and versioned 6–10-school fictional dataset. No network egress, no real person/phone, no real provider integration.
- Bounded discovery runner: max 30 candidates, 5 search pages, 20 fetches and 60-second default cap (make ceilings configurable only downward without policy); cap query keywords and page sizes; reject malformed/oversized/duplicated/cyclic responses, handle retries within budget, stop deterministically with truthful partial report.
- Integrate only **rights-allowed** synthetic provenance into P1.2 source_records. Do not persist restricted raw content, fabricate facts, infer owner/ERP/consent or automatically create/merge accounts. Treat fixture prompt injection as plain untrusted text.
- Reuse P1.5 registered safe worker job only if needed, with versioned typed payload and idempotency, dev/test only. Otherwise implement an internal test/dev CLI runner. No public unbounded discovery-run endpoint/UI.
- Output safe `DiscoveryFixtureReport` with run correlation ID, adapter/policy version, budget counters, accepted/rejected counts and reason codes. Never claim synthetic candidates are real Lahore businesses.
- Document `docs/contracts/source-adapters.md`, expected P2.2 provider extension, fixture license metadata, tests and ledger evidence.

## Do NOT build

Real directory/API adapter, SearXNG search, real website crawling, Google Maps scraping, production HTTP fetcher, generic SSRF-capable fetch URL tool, lead dedup, school scoring, campaign/contacts, outreach, messaging, AI agents or P2.2 work. Do not disable source rights checks for tests; configure explicit synthetic fixture policy.

## Verification and STOP

Execute **SOURCE-01…SOURCE-10**, including: policy missing/disabled, field/payload validation, storage class/TTL, repeated cursor and keys, 429/timeouts within budget, malicious text, unsafe URL no egress, cross-org provenance isolation, replay, DB+log inspection and prior P0–P1.5 regressions. Assert no real HTTP requests, no account/contact creation, no leaked restricted content, no prompt-injection authority and truthful partial-run counters. Run lint/types/tests and DB checks. Report exact commands, exit/status, and observed state; mark absent checks NOT-RUN.

Return **Section 4.2 close-out report** with all 10 SOURCE gates, migration impact, constraints for P2.2 and verdict. **STOP. DO NOT START P2.2.**
