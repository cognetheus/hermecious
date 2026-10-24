# Hermecious

Hermecious is a self-hosted, agent-assisted sales operations product. It discovers legitimate local businesses, researches their observable needs from permitted sources, matches them to verified offers, and runs consented, policy-gated WhatsApp outreach through to a human handoff. The first market is Lahore, Pakistan, and the first vertical is independent schools.

It is **not** a bulk-message bot, a scraper of prohibited sources, or a generic CRM.

## Status

Foundation work is in progress; [`EXECUTION_LEDGER.md`](EXECUTION_LEDGER.md) tracks each subphase. P0.1 provided the documents, ADR-001 and the secrets rules. P0.2 added a local Docker Compose stack: a FastAPI API, an RQ worker, a Next.js web app, Postgres and Redis, each with health probes. P0.3 added CI, the Alembic migration harness and deterministic tests (`bash scripts/check.sh`). P0.4 added structured logs and the error envelope; P1.1 added operator authentication (create the first owner with [`docs/runbooks/auth.md`](docs/runbooks/auth.md)). P1.2 added the rights-aware account, source and fact data model (no UI yet). P1.3 added the versioned offer catalog (`/offers`). There is no discovery or messaging yet.

## Repository layout

| Path | Purpose |
|---|---|
| [`docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`](docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md) | Master technical specification (source of truth) |
| [`docs/phases/`](docs/phases/) | Phase implementation packages and per-subphase prompts |
| [`AGENTS.md`](AGENTS.md) | Operating contract for coding agents and contributors |
| [`EXECUTION_LEDGER.md`](EXECUTION_LEDGER.md) | Subphase status, evidence, blockers and rollback notes |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`docs/runbooks/secrets.md`](docs/runbooks/secrets.md) | Secrets rules and leak response |
| [`.env.example`](.env.example) | Environment variable template (names only for secrets) |
| [`scripts/verify-setup.sh`](scripts/verify-setup.sh) | Baseline check: required documents and secrets rules |
| [`compose.yaml`](compose.yaml) | The local development stack |
| [`apps/api/`](apps/api/) | FastAPI app and RQ worker (Python 3.13, uv) |
| [`apps/web/`](apps/web/) | Next.js operator UI (Node 22, npm) |
| [`docs/runbooks/local-development.md`](docs/runbooks/local-development.md) | Stack commands, health contracts, recovery and troubleshooting |
| [`docs/runbooks/testing.md`](docs/runbooks/testing.md) | `scripts/check.sh`, test layout, integration stack, migrations, time control |
| [`docs/runbooks/observability.md`](docs/runbooks/observability.md) | JSON logs, redaction, request IDs, error envelope |
| [`docs/runbooks/auth.md`](docs/runbooks/auth.md) | Owner bootstrap, sessions, CSRF, roles, login limits |
| [`docs/contracts/core-domain.md`](docs/contracts/core-domain.md) | Accounts, sources, facts: schema, rights policy, fact rules |
| [`docs/contracts/offer-catalog.md`](docs/contracts/offer-catalog.md) | Offers: revisions, publication rules, sales-ready projection |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI: runs `scripts/check.sh` |

## Setup on a clean machine

Prerequisites: `git`, `bash`, `curl`, `openssl` and Docker with the Compose v2 plugin. Python and Node are only needed to work on the code outside containers.

```sh
# Private repository: needs a GitHub account with access (SSH shown).
git clone git@github.com:cognetheus/hermecious.git
cd hermecious
cp .env.example .env
chmod 600 .env
sed -i.bak "s/^POSTGRES_PASSWORD=$/POSTGRES_PASSWORD=$(openssl rand -hex 32)/" .env && rm .env.bak
bash scripts/verify-setup.sh
docker compose up --build -d
bash scripts/smoke-local.sh
```

`verify-setup.sh` must end with `All checks passed` and `smoke-local.sh` with `All smoke checks passed`. A `FAIL` line names what was broken. The secrets rules are explained in [`docs/runbooks/secrets.md`](docs/runbooks/secrets.md). The stack commands (logs, restart, stop, recovery checks) are in [`docs/runbooks/local-development.md`](docs/runbooks/local-development.md).

To run the check's own tests:

```sh
bash scripts/verify-setup.test.sh
```

## Architecture

See [ADR-001](docs/adr/ADR-001-modular-monolith-and-stack.md). Hermecious is a modular monolith (FastAPI with a separate worker, PostgreSQL as the system of record, Redis as the queue and a Next.js operator UI) deployed with Docker Compose on one VPS. The worker uses RQ ([ADR-009](docs/adr/ADR-009-worker-mechanism-rq.md)).

## Contributing

Read [`AGENTS.md`](AGENTS.md) first. Work proceeds one blueprint subphase at a time, and each subphase records its evidence in the ledger.
