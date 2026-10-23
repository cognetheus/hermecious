# HERMECIOUS — Claude Opus 5.5 High — P2.2 Real, Rights-Aware Lahore Source

**Implement P2.2 ONLY. STOP after P2.2 is VERIFIED or truthfully BLOCKED.**

## Sources of truth

Read, in this order:
1. `AGENTS.md` / `CLAUDE.md` where present; accepted ADRs; `EXECUTION_LEDGER.md`.
2. `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` (P2 scope and source restrictions).
3. `docs/phases/HERMECIOUS_BATCH_03_P1.4-P2.1.md` (P2.1 source DTOs/rights/budgets plus P1.5 durable worker contract).
4. `docs/phases/HERMECIOUS_BATCH_04_P2.2-P2.4.md`: §§0, P2.2, 5.1, 5.3.
5. Actual repository models, migrations, API routing, source registry, tests and job code. **Do not infer existing implementation from planning files.**

## Preflight (must occur before code changes)

- Print branch, HEAD, `git status`, migration revision, runtime/dependencies and relevant test commands with observed baseline outcomes.
- Confirm executed ledger proof for P0.1–P2.1. Check `SOURCE-01…SOURCE-10` results and actual approved source-registry semantics. If needed prerequisites are absent, report exact blocker and STOP; do not fabricate them.
- Make file-level plan and 10 test cases `LIVE-01…LIVE-10` with fixture/non-network vs. live execution differentiated. Declare one endpoint/source terms and operator-reviewed licence/storage rules. **Do not equate this prompt with permission to make network requests.**

## Build this bounded vertical slice

1. Implement an explicit **disabled-by-default** `osm_overpass_schools` source descriptor reusing P2.1 interfaces, allowed fields and budget governance. Record ODbL attribution, rights policy/reviewer/version, current endpoint restrictions, operation rights, legal retention and field-level storage class. Unknown/expired policy = denied. Do not silently rely on assumed fixed Overpass quotas.
2. Resolve Lahore area via validated, already-authorized configured geometry (or explicit operator bbox validated server-side); **do not invent neighborhood bounds or call public Nominatim for systematic lookups**. Generate fixed Overpass QL for school POIs only, no user-supplied query. Use one narrow query; max 30 accepted candidates, bounded requests/pages/fetch/cost/time/response bytes, truthful partial/truncated flags.
3. Locked-down outbound client: HTTPS, exact host/path allowlist, redirects off/strictly validated, DNS/IP SSRF protection, timeout, bounded response bytes, conservative retry/429/503 handling and Retry-After. No arbitrary URL fetch, no credential leakage, no browser scraping. Network test stubs for all CI tests.
4. Parse real OSM `node/way/relation` features: validated element type/id as immutable source key; capture only licensable allowed metadata, upstream timestamp if available and capture timestamp; preserve source OSM ID URL, attribution, version/expiry, unknown status. A way `center` is approximate, not verified address. No inferred owner, ERP, phone, school independence or prospect quality.
5. Integrate with existing P1.2 `source_records`; stage source-backed candidates only in a minimal table if no equivalent exists. Atomic/org-scoped/idempotent ingest. **Never automatically create accounts, facts, contacts, permissions, campaigns or sends**. Existing fixture adapter remains intact.
6. Provide an **operator-supplied CSV seed** fallback with explicit source and permission declaration, file checksum, bounded rows, validated UTF-8/Urdu/BOM/header, formula-injection-safe display/export, no fetch. Distinguish user-seeded records from independently observed OSM data.
7. Perform **one limited real Lahore source canary only if endpoint access and current permissions are explicitly enabled and externally available**. If not, include the tested fallback, but record `LIVE-10 BLOCKED/NOT-RUN`; do not manufacture real provider evidence or mark P2.2 verified in full.
8. Write/update `docs/contracts/source-adapters.md` and a P2.2 source policy ADR; show migration/rollback and operators' activation procedure; update ledger.

## Required tests — do not change meanings

- `LIVE-01`: disabled/expired/unreviewed source fails before network.
- `LIVE-02`: node/way/relation mocked normalization with stable identifiers and attribution.
- `LIVE-03`: malformed key, spoof URL, malicious name, bogus locale and geometry fail safely.
- `LIVE-04`: bbox/response >limits, 31+ candidate cap and visible truncation.
- `LIVE-05`: 429/Retry-After/503/timeout with enforced budgets and truthful partial state.
- `LIVE-06`: field/retention/rights/attribution reflected in database and redacted logs.
- `LIVE-07`: identical/revised response and CSV checksum replay without duplicate logical rows.
- `LIVE-08`: CSV malformed header, wrong area, payload/formula/encoding issues fail safely.
- `LIVE-09`: org/RBAC/CSRF where applicable, SSRF/redirect/DNS egress and all old SOURCE gates.
- `LIVE-10`: permitted actual-source canary with observed endpoint/query counts, OR explicitly BLOCKED.

Run real applicable lint/typecheck, unit, contract, Postgres integration/migration checks, source-fixture regressions and network-denied security tests. Inspect persisted rows and logs. Missing external network ≠ passing live canary. Provide command, exit code, evidence and state *after* failure for each relevant gate.

## Non-negotiable exclusions

No arbitrary internet scraping, Google Maps/Places durable scraping, public Nominatim grid/systematic queries, invented coordinates, fuzzy dedup, UI run management (P2.4), school qualification (P3), models/LLMs, outreach, messaging or follow-ups. No mass import that disregards licence/terms.

## Mandatory completion format

Return (1) changed files, (2) decisions and source-rights evidence, (3) migration plan/result, (4) `LIVE-01…LIVE-10` table with **VERIFIED / FAILED / BLOCKED / NOT-RUN**, (5) actual commands/tests/negative outcomes, (6) safety inspection, (7) rollback, (8) exact remaining blockers, (9) readiness for P2.3. Update `EXECUTION_LEDGER.md`. **STOP. DO NOT START P2.3.**
