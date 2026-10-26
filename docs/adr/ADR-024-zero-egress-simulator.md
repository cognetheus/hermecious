# ADR-024: Dry runs are bounded, fresh-checked simulations with a fake transport and a database-enforced zero

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" after reviewing the audit; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-24
- **Source:** `OPUS_P4.5_PROMPT.md`; blueprint §4 P4.4–P4.5. Batch 07 is absent from the repository.

## Decision

### 1. Separate tables (migration 0018)

- **`simulation_runs`:**
  - one per request, with a scenario, a mode and a status;
  - `max_items` (1–30) and `considered`;
  - `real_messages_sent`, held at 0 by a check constraint;
  - a frozen `evaluated_at`, the policy and simulator versions, the report and its SHA-256 digest;
  - an idempotency key with a request digest;
  - a partial unique index: **one active (pending or running) run per campaign**.
- **`simulation_items`** are append-only and unique per (run, account) and (run, seq). Database checks:
  - lifecycle only for `accepted`;
  - a `sim-<24 hex>` receipt only for `sim_delivered`;
  - attempts between 0 and 3.
- **No real tables are touched:** no message, conversation, consent, draft or approval state is written.

### 2. Execution

- **`simulation.run` v1** is an allowlisted P1.5 job type: max 3 attempts, payload `{run_id}` only.
- **Candidates:** at most 30. Campaign members (approved or excluded) come first, then the other accounts the campaign preview considers.
- **Each item is evaluated afresh, in order:**
  1. a contact exists (else `invalid: no_contact`);
  2. membership is not excluded;
  3. the latest draft;
  4. **P4.4 status**, which must be `approved_content` (a stale, rejected, revoked or unreviewed approval denies, with reasons);
  5. **P4.3 `decide()`** for the approval's exact contact, template and campaign, with usage counts **from this run only**;
  6. then the transport.
- **Per-item commits.** Items commit one at a time, and a retried job skips accounts already recorded, so there is one logical result per account.
- **Cancellation** is checked before each item.
- **Readiness mode** (live campaigns, or production) never invokes the transport.

### 3. Transport

- **`FakeWhatsAppTransport`** is the only transport. It is deterministic: `sim-` + sha256(run:account:content digest)[:24]. A 429 on the first attempt or timeouts are fixture scenarios only.
- **`live_transport()`** always raises `LiveTransportForbidden`. No setting, including `HERMECIOUS_LIVE_OUTBOUND_ENABLED`, can change that before P5.
- **No network:** the simulator package imports no HTTP or socket library and no egress client.

### 4. Scenarios (fixture state only)

| Scenario | Effect |
|---|---|
| `all_allow` | No change |
| `opt_out_mid_run` | A simulated STOP from the 2nd recipient |
| `quiet_hours` | Evaluates at 19:00 Asia/Karachi on the request day |
| `quota` | Starts usage at cap − 1 |
| `stale_approval` | Checks approvals 7 days + 1 second later |
| `provider_429_mock` | A 429 on the first transport attempt |
| `transport_timeout_mock` | Every transport attempt times out |
| `worker_restart_mock` | The first attempt crashes after half the items |

Clients cannot inject consent, inbound times or template states.

### 5. Report

- **Decision buckets** (`accepted`, `denied`, `deferred`, `invalid`) with denominator = considered.
- **Simulated lifecycle** (`sim_accepted`, `sim_delivered`, `sim_failed`) with denominator = accepted. An opt-out is never a delivery.
- **`reconciled`**, **missing prerequisites** mapped from reasons, and **standing blockers**:
  - official template approval (P5);
  - the real P3.4 audit;
  - verified real opt-in.
- **Labels.** Every API response, page and CSV line 1 says **"SIMULATION ONLY — 0 real messages sent"**.
- **CSV export** is redacted (no numbers, bodies or contact ids) and guarded against formula injection.

## Consequences

- **Engineering:** the decision pipeline (P4.1 → P4.5) is exercised end to end without egress. P5.1 can implement a real adapter behind the same per-item checks.
- **Production outreach-readiness stays NO:** the P3.4 gate is closed, there is no real opt-in, and there are no provider templates.

## Rollback

- **Stop:** cancel runs, or stop the endpoints and job type.
- **Data:** runs and items are disposable simulation data.
- **Schema:** downgrade 0018 only on a disposable database.
