# Hermecious — Opus 5.5 High — P1.3 (Offer & Capability Catalog)

**MANDATORY INPUTS:** Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_02_P1.1-P1.3.md`, accepted ADRs, `AGENTS.md`/`CLAUDE.md`, `EXECUTION_LEDGER.md` and current P1.1/P1.2 API/DB/UI implementations.

**EXECUTE EXACTLY P1.3. STOP when P1.3 is verified or blocked.**

### Preflight gate

1. Inspect `git status`, actual migrations, organization scoping, current authorization/CSRF and approved offer-related decisions.
2. Verify P0.1–P0.4, P1.1, P1.2 are `VERIFIED` in ledger with evidence; if not, **STOP** and report exact blockers.
3. Describe implementation files, schema migration plan, publishing state machine, checks `OFFER-01`–`OFFER-10`, race cases and rollback.

### Implement only the P1.3 specification

- Add `offers` and immutable/versioned `offer_revisions` (or lean documented equivalent). Concurrency control, organization-scoped FKs, indices and stable content digest.
- Typed capability matrix with `available`, `limited`, `planned`, `unverified`, `not_supported`; only reviewed/evidenced `available` and constrained `limited` may appear in approved sellable claim snapshot.
- Owner-only publishing/archiving; operator draft creation; read-only observer; backend enforcement + session CSRF. No mutation of published revision.
- Authenticated offer routes and compact admin UI as described. `sales-ready` service MUST only expose active published claims, explicit limitations, approved prices if any; absence of approval means `pricing_unavailable`, never invented numbers.
- Seed a school-administration **DRAFT** with unknown/unverified modules, no false evidence, promises or prices.
- Test unpublished/default offers, forbidden publish attempts, invalid planned/unverified claim publishing, immutable history, two-writer version conflicts, archive withdrawal, cross-organization read/write, CSRF and invalid claim payloads.
- Document contract for later P4/P6 consumers but DO NOT build message generation, campaigns or AI now.

### Non-negotiable prohibitions

No real offer claim or price without owner evidence, no auto-publishing, no sales prompt that queries draft claim matrix as product truth, no offers leaked across orgs, no rewriting P0/P1 foundation or auth for convenience, no WhatsApp, discovery or agent integrations. Never report an unrun check as pass.

### Verification and close-out

Execute `OFFER-01`–`OFFER-10`, including negative paths and concurrent publish/archival, migration rehearsal on disposable DB, API+UI auth/CSRF and P0–P1.2 regression suite. Record command/status/evidence in `EXECUTION_LEDGER.md`, update `docs/contracts/offer-catalog.md`. Return **Section 5 close-out table** from Batch 02. **STOP. Do not implement P1.4.**
