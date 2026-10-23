# Hermecious

Hermecious is a self-hosted, agent-assisted sales operations product. It discovers legitimate local businesses, researches their observable needs from permitted sources, matches them to verified offers, and runs consented, policy-gated WhatsApp outreach through to a human handoff. The first market is Lahore, Pakistan, and the first vertical is independent schools.

It is **not** a bulk-message bot, a scraper of prohibited sources, or a generic CRM.

## Status

Only subphase **P0.1** (repository foundation: documents, ADR-001 and secrets rules) has been worked on. The repository contains **no application code yet**: there is no API, web UI, database or worker. Those arrive in P0.2 and later, as tracked in [`EXECUTION_LEDGER.md`](EXECUTION_LEDGER.md).

## Repository layout

| Path | Purpose |
|---|---|
| [`HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`](HERMECIOUS_EXECUTION_BLUEPRINT_v1.md) | Master technical specification (source of truth) |
| [`AGENTS.md`](AGENTS.md) | Operating contract for coding agents and contributors |
| [`EXECUTION_LEDGER.md`](EXECUTION_LEDGER.md) | Subphase status, evidence, blockers and rollback notes |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`docs/runbooks/secrets.md`](docs/runbooks/secrets.md) | Secrets rules and leak response |
| [`.env.example`](.env.example) | Environment variable template (names only for secrets) |
| [`scripts/verify-setup.sh`](scripts/verify-setup.sh) | Baseline check: required documents and secrets rules |

## Setup on a clean machine

Prerequisites at this stage: `git` and `bash`. Both are preinstalled on macOS, and Linux distributions provide them as standard packages. Docker, Python and Node become prerequisites only in P0.2, and this section will be updated then.

```sh
git clone https://github.com/cognetheus/hermecious.git
cd hermecious
cp .env.example .env
chmod 600 .env
bash scripts/verify-setup.sh
```

The last command must end with `All checks passed` and exit with status `0`. A `FAIL` line names the rule that was broken. The rules are explained in [`docs/runbooks/secrets.md`](docs/runbooks/secrets.md).

To run the check's own tests:

```sh
bash scripts/verify-setup.test.sh
```

## Architecture

See [ADR-001](docs/adr/ADR-001-modular-monolith-and-stack.md). Hermecious is a modular monolith (FastAPI with a separate worker, PostgreSQL as the system of record, Redis as the queue and a Next.js operator UI) deployed with Docker Compose on one VPS.

## Contributing

Read [`AGENTS.md`](AGENTS.md) first. Work proceeds one blueprint subphase at a time, and each subphase records its evidence in the ledger.
