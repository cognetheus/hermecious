# HERMECIOUS — Claude Opus 5.5 High — P3.3 Explainable Four-Axis Qualification

**ASSIGNMENT: Implement P3.3 ONLY. STOP after independently verifying P3.3 or truthfully reporting a blocker.**

## Read and verify

Read `CLAUDE.md`/`AGENTS.md`, accepted ADRs, actual `EXECUTION_LEDGER.md`, `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, `docs/phases/HERMECIOUS_BATCH_05_P3.1-P3.3.md` §§0, P3.3, 4; inspect the tested P3.1 source-supported claims, P3.2 six-signal snapshots, P1.3 *published approved* offer/capability revisions, P1.4 account status and current auth/UI conventions. Never assume filenames or that implementation exists because a prompt was drafted.

**Prerequisite:** P3.2 `SCHOOL-01..10` verified in executed tests/ledger; P1.3 published-offer constraints demonstrable. If absent, report blocked, do not paper over by stubbing entire earlier phase.

## Objective / exact boundary

Compute a transparent, independently evidenced assessment with four separate **ordinal** dimensions: `customer_fit`, `need_evidence`, `accessibility`, `delivery_fit`, each `{strong,moderate,weak,unknown}`; deterministic recommendation `{contact_now, investigate, nurture, exclude}` and an auditable human override. **Contact_now is research prioritization, NOT marketing permission or automatic messaging.** No conversion probability, no fake “92% ready to buy.”

## Implementation sequence

1. **Inventory/contract/tests first:** report branch/SHA, existing schema, current rubric and approved offers, run baseline checks. Create `QUALIFY-01..10` executable test map and a pure-function rule table before modifying APIs. Ensure offer capability versions can be checked for publication and allowed claims; do not introduce new offers or claim features your app lacks.
2. **Versioned four dimensions:** implement pure deterministic `school_qualification_v1`, each dimension with reason, source fact IDs, signal snapshot ID and unknown questions. `unknown` is distinct from `weak`; public generic directory phone isn't decision-maker access, and no published offer cannot yield strong delivery fit. An observed admissions instruction is not automatically confirmed painful process. Never compute a percentage/weighted composite.
3. **Decision precedence:** (a) `exclude` only when a current supported **hard** disqualifier exists; (b) `nurture` only when a documented deferred-review reason/event exists; (c) `contact_now` only with fit+need ≥moderate, business-route access ≥moderate from suitable evidence, delivery strong with *currently published* offer, no material conflicts/staleness and no hard blocker; (d) otherwise `investigate`. This is not a send gate. Expose `channel_eligibility=not_evaluated` as presentation only; DO NOT implement P4 channel policy.
4. **Persistence and invalidation:** reuse existing `assessments` if created by P1.2; otherwise minimal org-scoped `assessments` schema with ordered source signal digest, rubric version, P1.3 offer_id+approved capability version, exact four dimensions, decision, reason, unresolved questions, created_at, revision, supersession history. Unique logical generation for unchanged inputs and guarded concurrent writes. Correction/revoked source/school identity change/unpublished or changed offer => visible `needs_reassessment` / stale, new computation may supersede; history retained.
5. **Reviewer override:** owner/operator authenticated CSRF-protected decision override with `expected_revision`, mandatory nonempty reason, optional org-scoped evidence IDs, typed changed fields, full before/after audit and non-destructive superseding version. Reject stale revisions, unauthorized role, cross-org, arbitrary statuses and overrides that violate hard exclusions or fake consent. Preserve ability to challenge rubric judgment without losing machine explanation.
6. **API/UI:** implement or adapt `POST /api/v1/accounts/{id}/assess`, GET latest/history, POST `/accounts/{id}/assessments/{assessment_id}/override`. Account detail gets Qualification panel: four evidence/unknown cards, reviewed current published offer, decision and why, staleness, outstanding questions and read-only audit timeline; editable review for authorized operator only. Explicit UI text for `contact_now`: **“Research priority: contact candidate — channel eligibility not checked.”** No one-click send or enroll CTA. Sanitize HTML/URLs and long Urdu content.
7. **Test all negative and E2E paths:** missing site/OSM-only; conflicting notices; verified central mandate; undocumented defer guess; cancelled/revoked offer; stale source; concurrent overrides and job replay; CSRF/org/observer denials; malicious model prose; history/restart. `QUALIFY-01..10` must each assert actual DB state, not only HTTP codes. Run P3.1/P3.2 and P0–P2 regressions relevant to affected modules. Assert no `campaign_accounts`, `outreach_plans`, `contact_permissions`, messages or task schedules created by P3.3.
8. **Self-review and ledger:** inspect every condition that reaches `contact_now` for false claims; fail-safe if a source expires between read and commit; attach actual commands/exit codes and screenshots if UI E2E, docs/contracts, rubric change log, migration/rollback. If unavailable runtime or live source, truthfully mark BLOCKED/NOT-RUN.

## Ten required gates

- **QUALIFY-01** exactly four documented ordinal dimensions with source IDs/rubric/offer version.
- **QUALIFY-02** directory-only/no website -> unknown/investigate, no guessed need/budget/ERP.
- **QUALIFY-03** supported fit+need, meaningful administrative route and matching published offer -> contact_now research priority, not permission; no sends.
- **QUALIFY-04** verified hard disqualifier vs weak/unknown -> exclude only on supported hard blocker.
- **QUALIFY-05** proven defer vs guessed future interest -> nurture vs investigate; no reminder action.
- **QUALIFY-06** missing/unpublished/incompatible offer -> delivery cannot be strong; no invented capabilities.
- **QUALIFY-07** source/offer/signal change invalidates prior recommendation and preserves history.
- **QUALIFY-08** reviewer override reason/version/race yields safe immutable audit and conflict.
- **QUALIFY-09** CSRF/observer/cross-org/injection/security negative paths.
- **QUALIFY-10** E2E account → facts → school brief → assessment → reviewed override + restart; previous suites and zero messaging.

## Explicit exclusions and final report

Do not implement P3.4's real 30-account quality evaluation, P4 draft campaigns, contacts, consent evaluation, WhatsApp, sales conversations, production outreach, AI orchestration frameworks or a generic CRM. Do not claim business-need accuracy from synthetic test fixtures: production evidence quality is an **unmeasured hypothesis** until P3.4.

Final output: actual modified paths and schema, `QUALIFY-01..10` evidence table with commands/status, exact rule/override behavior, earlier suite outcomes, source-rights and offer-version controls, audit, rollback and `P3.4 UNBLOCKED / BLOCKED`. Update ledger. **STOP AFTER P3.3.**
