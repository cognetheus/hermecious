# ADR-015: Discovery runs are durable jobs over reviewed sources; accounts are created only by explicit reviewer admission

- **Status:** Proposed — implemented and verified, awaiting owner acceptance (an agent may not accept its own ADR; AGENTS.md)
- **Date:** 2026-10-24
- **Source:** Batch 04 §P2.4; `OPUS_P2.4_PROMPT.md`; ADR-011 (jobs), ADR-012/013 (sources), ADR-014 (identity)

## Decision

### 1. Run model (migration 0009)

**`discovery_runs`** stores one row per requested run:
- **Request and snapshots:** requester, provider, server-resolved city and area label, adapter version and rights policy version, attribution, and a budget snapshot.
- **Execution record:** status, counters (examined, staged, rejected by rules, displayed ≤30), `truncated`, `stop_reason`, `partial_reason`, `error_code`, `usage_json`, and the job id.
- **Idempotency:** `idempotency_key` plus a request digest; unique per organization.

**`discovery_run_candidates`** links runs to P2.2 candidates many-to-many.
- Review state is `pending`, `accepted`, `rejected` or `deferred`.
- Each row has its own version.

**`discovery_review_decisions`** is append-only, one row per reviewer command.

There is no copy of P2.2 candidates or P2.3 links: P2.3's `candidate_account_links` is reused for admissions.

### 2. Area

No P1.2 `areas` row exists for discovery, and the browser must never send geometry. The run's area is therefore the area **bound to the chosen provider on the server**:
- the synthetic fixture dataset; or
- the owner-configured, cited OSM box (ADR-013).

`area_id` from the batch's example DTO is replaced by this server-side binding.

### 3. Creating a run (`POST /api/v1/discovery/runs`; owner or operator, CSRF; 202)

**Body:** `{provider, budget, idempotency_key}`.

**Checks:**
- The provider must pass policy **now**; otherwise the request is refused with 400 before anything is written.
- The budget can only tighten the platform ceilings: 30 listings, 5 pages, 20 fetches and 45 seconds. 45 s is deliberately below the 60 s P1.5 lease.

**In one transaction**, the request commits:
- the run;
- a `discovery.run` v1 job, whose payload is `{run_id}` only;
- the P1.5 outbox event;
- a `discovery.run_requested` audit.

**Idempotency:** the same key with the same request replays (202, `replayed: true`). The same key with a different request gives 409.

### 4. Worker (`app/discovery/runs.py::handle_run_job`)

**At start:**
- A terminal run is never touched again.
- A run with a pending cancellation becomes `cancelled`.
- Otherwise the run becomes `running`, committed so the UI sees progress.

**Execution:**
- The worker re-resolves the provider with **current** settings. A stale or withdrawn policy gives `failed` with the reason code, before any request is made.
- It acts as the requesting user, after re-checking that the user is still active and allowed to make changes.
- It re-applies the budget snapshot, then runs the P2.1/P2.2 runner. The runner checks policy and cancellation before every adapter call.
- It links up to 30 staged candidates to the run, then runs the P2.3 resolver.

**Terminal states:** `completed` (the bounded run finished; never "exhaustive"), `partial` (with a safe reason), `cancelled` or `failed`.
- The terminal state is written in the final transaction, which P1.5 commits only with a fenced completion. A worker whose lease was lost cannot finalize, and a late duplicate delivery sees a terminal run and does nothing.
- Unexpected errors retry up to 3 attempts. The last attempt marks the run `failed` (`worker_error`) instead of leaving it running.

### 5. Cancellation (`POST /runs/{id}/cancel`)

Cancellation is idempotent and cooperative.
- **Pending run:** it becomes `cancelled` immediately, and its job becomes `cancelled`, so the job is never claimed.
- **Running run:** `requested_cancel_at` is set. The runner stops before its next adapter call, and the run ends `cancelled`.
- **Never touched:** reviews and accounts that already exist.

### 6. Reviewer admission (`POST /runs/{id}/candidates/{candidate_id}/decision`; owner or operator, CSRF)

**Body:** `{action, expected_version, idempotency_key, reason, existing_account_id?}`.

**Actions:**
- **`accept_new`**
  - **Refused when:** the candidate's evidence is still not permitted (candidate or source expired, provider rights, fixture or seed policy), or **any open `suggest_review` same-campus suggestion** exists, which must be decided in P2.3 first.
  - **Effect:** one P1.4 account, status `discovered` (research pending, never qualified), plus aliases (the Urdu name included) carrying the source record. It also creates a `candidate_account_links` row and an `account.created` audit with origin and provenance.
  - **Not recorded:** no facts, contacts or needs.
- **`attach_existing`** requires the active P2.3 reviewed link between this candidate and that account.
- **`reject`** is refused if the candidate is linked to an account.
- **`defer`**.

**Idempotency and concurrency:**
- Decisions are idempotent per key; the same key with a different payload gives 409.
- The candidate row is locked, so admissions of one candidate are serialized across runs and reviewers. A concurrent `accept_new` **converges** on the existing account (`converged: true`).
- A stale version gives 409, and a foreign account gives 404.

### 7. UI (Next.js, existing auth and style)

**Pages:**
- `/discovery`: the runs table with status, counts and the review tally.
- `/discovery/new`: only permitted sources are offered, with the rights, attribution and server area summary, and downward-only budget fields.
- `/discovery/runs/[id]`: polls durable state every 2 s while active, and offers a cancel control.

**Listing cards show:**
- provenance, observed and upstream times, rights, expiry and attribution;
- an explicit list of unknowns;
- possible same-campus matches, decided through the P2.3 API.

**Reviewer actions:** accept, attach (only when confirmed), reject and defer.

**Safety in the UI:**
- Observers see no controls.
- Text is rendered by React (escaped). Only `https:` provenance links are rendered, with `rel="noopener noreferrer nofollow"`.
- Urdu names are marked `lang="ur" dir="rtl"`.

## Consequences

- A run is always explicit about being bounded: `exhaustive: false`, plus copy in the UI.
- Live OSM runs are possible only after the owner's ADR-013 activation. Until then, only the synthetic fixture (development and test) is offered.

## Rollback

- **Stop new runs:** remove the provider from the permitted set (disable or unconfigure it); `POST /runs` then refuses before anything is written.
- **Pause execution:** stop the worker. Pending runs stay visible and can be cancelled.
- **Keep the history:** runs, decisions, links and accounts are retained.
- **Revert code:** revert the P2.4 commits.
- **Schema:** downgrade 0009 only on a disposable database.
