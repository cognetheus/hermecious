# OPUS 5.5 HIGH — HERMECIOUS P4.5: Zero-Egress Sending Simulator and Campaign Report

**ASSIGNMENT:** Implement **P4.5 only**. Build dry-run evidence of the sending decision engine; **never send a real message**. Stop after verification. Do not start P5.

## Repo inspection and prerequisite gate

Read `CLAUDE.md`, `AGENTS.md`, accepted ADRs, `EXECUTION_LEDGER.md`, the master blueprint, prior Batch 06 plan and **Batch 07 plan sections 0, P4.5, 4, 5**. Inspect and baseline actual P1.5 durable job registry, P3.4 quality gate, P4.1 campaign membership, P4.2 draft revisions, P4.3 policy evaluator and P4.4 immutable approvals. Confirm P4.3 and P4.4 are VERIFIED **for engineering** (not necessarily real outreach), or report blockers.

Capture SHA, branch/dirty worktree, migration version, existing worker and provider adapter references, baseline tests. Never erase/migrate down a real DB or reset uncommitted changes. Add only scoped, additive files/tables required for P4.5.

## The operator's functional journey

Open a synthetic/test campaign → click `Dry Run` → bounded simulate eligible/denied/deferred decisions for up to 30 candidates → inspect **exact** per-account policy/approval blocking reasons → see report with true denominators and independently labelled simulated lifecycle statuses → cancel/restart safely. Display `SIMULATION ONLY — 0 real messages sent` in every relevant UI and export.

Production candidate runs may report readiness gaps based on real stored policies, but **must not simulate** real contact delivery events or mutate real conversation/message state. Preserve P3.4 live 30-school evidence gate. Fixture data never means real permission.

## Architecture (specific limits)

1. Create `SimulationRun` and `SimulationItem` in a separated `simulations` DB namespace/tables. Reuse org scoping, action audits and P0.4 error pattern. No writes to real `messages` delivery statuses. Store simulated receipt IDs prefixed `sim-`; no provider IDs from API.
2. Implement a strict `FakeWhatsAppTransport` with no real network client/token/provider configuration. Any attempted live transport instantiation from simulator raises a typed `LiveTransportForbidden`. Under test, intercept socket/HTTP calls and assert *no outbound network invocation*; also assert no active `send_message` job/outbox event added.
3. For every item, bind exact current campaign, contact, draft version/digest, approval receipt and P4.3 **fresh policy check**, with suppressions/kill switch evaluated immediately before fake result. Do not rely on stale approval snapshots. A state change mid-run stops or denies remaining items. Contact with no verified consent stays denied.
4. Define deterministic scenarios with frozen aware UTC clock and stable fixture RNG if fake delivery variance is needed: `all_allow`, `opt_out_mid_run`, `quiet_hours`, `quota`, `stale_approval`, `provider_429_mock`, `transport_timeout_mock`, `worker_restart_mock`. Scenario override is only for **test-only fixture state**; a client cannot claim verified consent or falsify inbound timestamps for production records.
5. Bounded max 30 accounts/run; one active run/campaign; max attempts/runtime/concurrency. Same idempotency key+same canonical input→same stored run; different payload→409. Optional P1.5 job type `simulation.run.v1` with allowlisted handler **only**; never a generic message/sending job. After worker crash/restart items converge to one logical recorded result.
6. Report independent **decision bucket counts** (accepted/denied/deferred/invalid), **lifecycle counters** (sim-accepted/sim-delivered/sim-failed) and named missing prerequisites; reconciled denominator equals considered records. Percentage fields must include denominators and differentiate simulated vs live. Opt-out counts cannot be double-counted as deliveries.
7. APIs (adapt to routes): `POST /api/v1/campaigns/{id}/simulations` (owner/operator+CSRF and request bounded), `GET /.../simulations`, `GET /.../simulations/{run_id}`, `POST /.../{run_id}:cancel`, optional redacted export. Observer read-only; cross-org hidden; CSV formula injection escaped; no raw phone numbers or message body in report.
8. UI `Dry Run` dashboard with per-account reason drilldown, current plan/offer/evidence/permission state, sim status, run time, code/policy revisions, report digest and actionable prerequisite to P5 (`real opt-in`, `official template approval`, `fresh evidence`, `draft review`). No `Send Now`, no real provider config controls.
9. Add negative tests: suppress during run, replay, worker kill, 429/timeouts fixture only, real SDK accidentally imported, `HERMECIOUS_LIVE_OUTBOUND_ENABLED=true` from env **still cannot enable sending in Batch 07**, unauthorized actor, stale source/offers, UTC/Asia-Karachi and service-window edge cases.
10. Run static/unit/contract/integration/E2E/security/regression checks; code search job registry/outbox and network spies verify **zero real sends**. Put actual commands/statuses in `EXECUTION_LEDGER.md`; STOP.

## Acceptance checklist — all ten stable IDs

| Gate | Mandatory observed result |
|---|---|
| `SIM-01` | Deterministic synthetic eligible run, fake accepted/delivered only, no actual delivery |
| `SIM-02` | No consent/false proof/revocation all denied |
| `SIM-03` | Opt-out mid-run blocks across campaigns and remaining recipients |
| `SIM-04` | Unapproved/stale content, bad template, paused campaign, changed offer block |
| `SIM-05` | Quiet hours/UTC/local midnight/service-window purpose boundaries correct |
| `SIM-06` | Mock 429/timeout/restart retries bounded, no double logical effects/provider IDs |
| `SIM-07` | Concurrent runs + idempotency reuse and 409 conflicting payload |
| `SIM-08` | 30-item mixed report reconciles exactly; redacted export and simulation labels |
| `SIM-09` | Network spy/socket denial/worker registry/DB checks prove **zero real sends** |
| `SIM-10` | UI E2E dry run/cancel/restart + auth/CSRF/cross-org negative tests |

## Absolutely forbidden

- Sending a real message, **including test numbers**, or using Meta/WABA sandbox credentials; those come in P5.
- A real provider adapter/client fallback anywhere under `P4.5`.
- A `send_message`, `outbound.dispatch` or similarly capable background handler/outbox event.
- Treating `simulated_delivered` as WhatsApp-delivered, or publishing real delivery metrics from simulated data.
- Backfilling actual consent from public directories or accepting test fixtures as human permission.
- Building P5.1 adapter, P5.2 webhook or future phases.

## Completion report and stopping point

Return baseline+SHA, changed files/migrations, exact routes/types and data isolation, full `SIM-01..10` matrix with executed commands/exit statuses, network interception evidence, outbox/job registry proof, a sample **synthetic clearly labelled** report and denominator reconciliation, rollback/kill-switch plan, honest real P3.4/opt-in/template blockers, and ledger update. End with `P5.1 implementation-readiness` (technical only) vs `production outreach-readiness = NO`.

**STOP AFTER P4.5. DO NOT START P5 WITHOUT A NEW PROMPT.**
