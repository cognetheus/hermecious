# Execution Ledger

The authoritative record of subphase progress. Statuses: `not-started`, `in-progress`, `verified`, `blocked`, `not-run` (see AGENTS.md). Entries are append-only, and corrections are recorded as new notes.

## Subphase status

| ID | Title (blueprint §4) | Status |
|---|---|---|
| P0.1 | AGENTS.md, README, ADR-001, ledger, `.env.example`, secrets rules | in-progress |
| P0.2 | Compose (API, web, Postgres, Redis, worker), health/readiness | not-started |
| P0.3 | CI lint/typecheck/test, migrations, fixtures, time control | not-started |
| P0.4 | Structured logging, typed errors, config validation, secret masking | not-started |
| P1.1 to P12.4 | See blueprint §4 | not-started |

## P0.1 — Repository foundation

_Evidence pending._
