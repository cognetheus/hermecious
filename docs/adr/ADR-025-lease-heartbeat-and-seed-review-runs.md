# ADR-025: Job leases are renewed between steps; operator CSV imports are reviewed through seed review runs

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" on the open audit decisions; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-25
- **Source:** the 2026-10-25 audit of P2.2–P4.5; blueprint §4 P1.5, P2.2, P2.4; `HERMECIOUS_BATCH_04_P2.2-P2.4.md` ("SourceAdapter.search() (or validated seed import)"; "a local user-supplied seed file provides a usable alternative").

## 1. Lease heartbeat

### Problem

- **Short leases (P1.5).** A claimed job gets a 60-second lease, so a dead worker's job is rescued quickly.
- **No renewal.** Handlers could never renew it. A run that took longer, for example one slow Overpass call after earlier ones, could lose its lease mid-run, and a second worker would then run it concurrently.

### Decision

- **Renewal.** The runner gives each handler `JobContext.renew_lease`. It is a fenced heartbeat in its own short transaction: `UPDATE jobs SET lease_expires_at = now + 60 s WHERE id = … AND lease_token = … AND status = 'running'`.
- **Where it is called.** Handlers call `registry.keep_alive(ctx)` between steps:
  - discovery: before every adapter call;
  - research: before every source;
  - simulator: before every item.
- **Lease loss.** If the lease was already taken over, `keep_alive` raises `LeaseLostError` and the handler stops. Its completion would be refused by the fencing token anyway.
- **What stays the same:** the 60-second lease, dead-letter rules, backoff and attempt limits.
- **Remaining bound:** a single step must finish within 60 seconds (Overpass: 20 s server timeout, 25 s socket timeout).

## 2. Seed review runs

### Problem

- **Staging only.** P2.2's operator CSV import staged rows, but nothing let a reviewer admit them.
- **No other path in production.** Runs offered only the fixture and OSM, and OSM is off until the owner enables it. Production therefore had no reviewable source.

### Decision

- **The CSV is a run source.** Its key is `operator_seed_csv`.
- **Starting a run.** `POST /api/v1/discovery/runs` takes `budget.seed_import_id`. It is required for this source and refused for any other. An import of another organization is a 404.
- **Execution.** The run fetches and re-stages nothing. It lists up to 30 of that import's unreviewed rows in import order, then runs identity resolution.
- **Review.** Admission uses the same decisions, rights checks (the seed descriptor), same-campus rules and audit as any run.
- **Listing imports.** `GET /api/v1/discovery/seed-imports` lists imports for the picker in the new-run form.
- **Provenance.** Rows keep the operator's `source_reference` in their attribution. They are never presented as verified.

## Consequences

- **Long runs no longer race a second worker.** A crashed worker is still rescued after at most 60 seconds.
- **The CSV fallback is usable end to end,** including in production, without enabling a live source.

## Rollback

- **Heartbeat:** remove the `keep_alive` calls (no schema change).
- **Seed review runs:** drop the CSV option from `_options` (no schema change). Admitted accounts remain.
