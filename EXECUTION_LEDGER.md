# Execution Ledger

The authoritative record of subphase progress. Statuses: `not-started`, `in-progress`, `verified`, `blocked`, `not-run` (see AGENTS.md). Entries are append-only, and corrections are recorded as new notes.

## Subphase status

| ID | Title (blueprint §4) | Status |
|---|---|---|
| P0.1 | AGENTS.md, README, ADR-001, ledger, `.env.example`, secrets rules | verified (owner proceeded to P0.2; ADR-001 still Proposed) |
| P0.2 | Compose (API, web, Postgres, Redis, worker), health/readiness | verified; awaiting owner review |
| P0.3 | CI lint/typecheck/test, migrations, fixtures, time control | not-started |
| P0.4 | Structured logging, typed errors, config validation, secret masking | not-started |
| P1.1 to P12.4 | See blueprint §4 | not-started |

## P0.1 — Repository foundation (2026-10-23)

**Scope (blueprint §4 P0):** `AGENTS.md`, project README, ADR-001 (modular monolith and approved stack), task ledger, `.env.example`, secrets rules.
**Gate:** setup instructions reproduce on a clean machine.

### Starting state

The repository had no commits. Its only file was `HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, which was committed unchanged as the baseline (`0dce235`). There was no code, no dependencies, no tests and no ADRs.

### Conflicts and the safe defaults chosen

1. **Blueprint location.** The task prompt cited `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, but the file is at the repo root, and blueprint §8 refers to it by bare name. It stays at the root. Moving it is a one-line `git mv` if the owner prefers `docs/`.
2. **ADR-001 status is `Proposed`, not `Accepted`.** §8 forbids an agent from self-approving decisions. The owner accepts it at this review.
3. **Worker library (Dramatiq vs RQ)** is left open, because §1 requires a separate ADR for that choice. It must be decided before P0.2 builds the worker.
4. **`.env.example` content.** No code reads any variable yet. Listing future variables (DB, Redis, WhatsApp) would be speculative scaffolding, so the template declares only the two values the blueprint fixes: the environment name and the `Asia/Karachi` timezone. Later subphases add a variable when their code first reads it (secrets rule 5).
5. **`scripts/` is not in the suggested tree (§1).** It was added because both the gate and the secrets rules need an executable check. Without one, "reproduces on a clean machine" could not be verified.

### Acceptance cases and results

| # | Case | Result |
|---|---|---|
| AC1 | The README setup steps reproduce from a fresh public clone on a clean machine: macOS with empty HOME/env, and Debian 12 container as non-root | **pass** (both) |
| AC2 | All P0.1 documents are present, and every relative markdown link resolves | **pass** |
| AC3 | A secret value or a credentialed URL in `.env.example` is rejected, and the value is never echoed | **pass** |
| AC4 | `.env` and its variants are git-ignored, and a force-added `.env` is detected | **pass** |
| AC5 | A local `.env` readable by group or others is rejected | **pass** |
| AC6 | A private key or well-known token format in any tracked or addable file is detected (file name reported, not content) | **pass** |
| AC7 | Failure handling: a malformed or duplicate `.env.example` entry, a missing required document, or a non-git copy each fail with a specific message and exit code | **pass** |
| AC8 | The tests discriminate: sabotaging the permission check and the secret-value check makes the matching tests fail | **pass** (9/11 with the mutation, then restored) |

### Commands and observed outcomes

| Command | Where | Outcome |
|---|---|---|
| `shellcheck scripts/verify-setup.sh scripts/verify-setup.test.sh` | macOS | exit 0, no findings |
| `bash -n` on both scripts | macOS (bash 3.2.57) | exit 0 |
| `bash scripts/verify-setup.sh` | working tree | 15 PASS, "All checks passed", exit 0 |
| `bash scripts/verify-setup.test.sh` | working tree | 11 passed, 0 failed, exit 0 |
| Mutation run: two checks disabled with `sed` in a scratch copy | scratch copy | 9 passed, 2 failed (expected), copy deleted |
| README steps under `env -i HOME=<empty> PATH=/usr/bin:/bin`, cloning `https://github.com/cognetheus/hermecious.git` at `7d4ad51` | macOS | verify exit 0 (16 PASS including .env perms); tests 11/0, exit 0 |
| The same README steps as user `dev` in `debian:bookworm-slim` (git 2.39.5, bash 5.2.15, GNU tar 1.34), clone at `7d4ad51` | Linux container | verify exit 0; tests 11/0, exit 0 |
| Relative link check over all tracked `*.md` | working tree | 15 links, 0 broken |

**Not run, and why:**
- `markdownlint` and `shfmt` are not installed locally. They will be added with CI in P0.3.
- `ruff`, `mypy`, `pytest`, `vitest` and Playwright do not apply, because there is no Python or TypeScript code yet.
- There are no contract or integration tests yet, because there are no integrations.

### Changed files

`.env.example`, `.gitignore`, `AGENTS.md`, `README.md`, `EXECUTION_LEDGER.md`, `docs/adr/ADR-001-modular-monolith-and-stack.md`, `docs/runbooks/secrets.md`, `scripts/verify-setup.sh`, `scripts/verify-setup.test.sh`. The blueprint is unchanged.

### Review notes

- **Security.** The checks never print secret values; this is tested. The scan is pattern-based and covers only the working tree. It is not a full secret scanner (no entropy analysis, no git-history scan). A dedicated scanner such as gitleaks is a candidate for P0.3 CI. No pre-commit hook was added, so enforcement relies on AGENTS.md and, later, CI.
- **Correctness and portability.** Verified on bash 3.2 with BSD tools and on bash 5.2 with GNU tools.
- **Idempotency.** `verify-setup.sh` is read-only. The test suite writes only to a `mktemp` directory that it removes on exit, and it never reads the developer's `.env`.
- **Architecture.** No application directories were created. ADR-001 records the approved stack and the exclusions.

### Blockers

None for P0.1. **Owner action:** accept or amend ADR-001, and confirm that the blueprint should stay at the repo root.

### Rollback

P0.1 is documentation and scripts only, with no data and no migrations. Run `git revert` on the P0.1 commits. `0dce235`, the blueprint baseline, remains.

### Next safe step

Owner review of P0.1, then the worker-library ADR (Dramatiq vs RQ), then **P0.2** (Compose, health and readiness probes). Do not start P0.2 until the owner approves it.

## P0.2 — Docker development stack and readiness (2026-10-23)

**Scope:** Batch 01 §P0.2 (`HERMECIOUS_BATCH_01_P0.2-P0.4.md`). Compose stack with API, web, Postgres, Redis and worker, plus live/ready probes, a meaningful worker health check, a named Postgres volume, a runbook, and smoke and recovery scripts. **Out of scope and not touched:** business tables, auth, CI, migrations, structured logging, messaging.

### Starting state

P0.1 was committed (`e180782`). There was no application code, no manifests and no lockfiles. The batch file was untracked and was committed as `60b36c0`. Batch 02 and the `OPUS_P1.x_PROMPT.md` files, plus a PDF, appeared in the repo root during this work. They were left untracked and unread.

### Decisions and deviations

1. **One subphase only.** The batch says "exactly one subphase per run", so P0.3 and P0.4 were not started even though the request said "implement" the batch.
2. **Worker: RQ** ([ADR-009](docs/adr/ADR-009-worker-mechanism-rq.md), status Proposed). Dramatiq was not installed. The behaviour the ADR relies on was confirmed in the rq 2.12.0 source (heartbeat on every dequeue loop, `ConnectionError` retry with backoff capped at 60s) and then observed in A4.
3. **Toolchain:** uv (`uv.lock`) for Python 3.13 and npm (`package-lock.json`) for Node 22. Image base tags are pinned to exact patch versions: python 3.13.17, node 22.23.4, postgres 18.6, redis 8.10.2, uv 0.7.9.
4. **TypeScript 5.9.3, not 7.0.2.** TS 7 is the native-compiler rewrite, and the Next 16 build-time type check relies on the TS 5 JS API.
5. **`httpx2` instead of `httpx` for tests.** Starlette 1.9 deprecates `httpx` in `TestClient` and names `httpx2`, which is published by the pydantic org.
6. **API tests live in `apps/api/tests/`, not the blueprint's root `tests/`.** They colocate with the Python project. P0.3 owns the final test layout.
7. **Redis has no password and no persistence.** It is reachable only on the internal Compose network, and it is a broker only (ADR-009). Production hardening is P11.
8. **The repository became private during this work,** so anonymous HTTPS clone now returns 404. README now clones over SSH (`837060e`). The P0.1 evidence of an anonymous clone describes the state at that time.
9. **Postgres 18 images mount the volume at `/var/lib/postgresql`** (PGDATA `/var/lib/postgresql/18/docker`), not at `/var/lib/postgresql/data`.

### Acceptance evidence (final code at `837060e`, plus this ledger commit)

| ID | Test / command | Observed | Result |
|---|---|---|---|
| A1 | `docker compose up --build -d` (dev); clean room: fresh SSH clone, README steps, `docker compose build --no-cache`, `up -d` | 5 services `running/healthy` in both | PASS |
| A2 | `bash scripts/smoke-local.sh` | live `200 {"status":"alive"}`; ready `200 {"status":"ready","checks":{"postgres":"ok","redis":"ok"}}`; web `200 {"status":"alive"}`; exact-body match | PASS |
| A3 | `scripts/recovery-local.sh` §A3 | Postgres stopped: ready `503 {"status":"not_ready","checks":{"postgres":"unavailable","redis":"ok"}}`, live 200; restarted: ready 200 | PASS |
| A4 | `scripts/recovery-local.sh` §A4 | Redis stopped: ready 503 (`redis: unavailable`); the worker health check exits 1; container `unhealthy` after 26–30s; Redis restarted: ready 200, worker `healthy` 11s later with **0 container restarts** (RQ reconnect) | PASS |
| A5 | `scripts/recovery-local.sh` §A5 | Row in throwaway DB `hermecious_p02_smoke`, then `docker compose down` (no `-v`) and `up -d`; the row read back with a matching token; DB dropped | PASS |
| A6 | `POSTGRES_PASSWORD= docker compose config` | exit 1: `required variable POSTGRES_PASSWORD is missing a value` | PASS |
| A6 | `docker compose run --rm --no-deps -e DATABASE_URL= api` | exit 1: `refusing to start: missing or invalid settings: DATABASE_URL` | PASS |
| A6 | Same, with `DATABASE_URL=mysql://u:LEAKME-123@db/x` | exit 1; `LEAKME` occurrences in output: 0 | PASS |
| A6 | `docker compose run --rm --no-deps -e REDIS_URL= worker` | exit 1: `... missing or invalid settings: REDIS_URL` | PASS |
| A7 | `docker compose ps`, `docker compose port` | Postgres and Redis publish nothing; api `127.0.0.1:8000`, web `127.0.0.1:3000` only | PASS |
| A7 | Image audit (api, worker, web) | `.env*` files in image: 0; Postgres password in image FS, `docker history` and image config: 0; build context contains only `app/` plus manifests | PASS |
| A7 | `docker compose logs`, all services | Password occurrences: 0; `postgresql://` occurrences: 0 | PASS |
| A7 | `id -u` in containers | api/worker 10001, web 1000 (non-root); app containers use `cap_drop: ALL` and `no-new-privileges` | PASS |

### Negative paths observed

| Case | Observed |
|---|---|
| Port collision (host 18000 held, `HERMECIOUS_API_PORT=18000 docker compose up -d api`) | exit 1, `bind: address already in use`; restored with default port and smoke passed |
| Port collision, unintended: during a clean-room rerun I forgot to export the alternate ports | Clean-room api/web failed to bind ports 8000/3000 held by the dev stack; recovery script `FAIL stack did not become ready`, exit 1. Harness error; rerun with ports exported passed |
| Container crash (SIGKILL of the worker's main process from the VM via privileged `--pid=host`) | RestartCount 0→1, new registration name, `healthy` again |
| Dependency delayed or down at runtime | A3/A4: readiness reports it and recovers without restarts |
| Docker daemon unreachable (`DOCKER_HOST=unix:///nonexistent.sock`) | smoke: `ERROR Docker daemon is not reachable`, exit 2 |
| Missing runtime (`docker`/`curl` absent) | Scripts exit 2 with a named error (code path is present; not executed) |
| Volume permissions | Only Postgres mounts a volume, and its image entrypoint owns `PGDATA`. App containers mount no volumes. No issue observed |

### Static checks and unit tests

| Command | Outcome |
|---|---|
| `uv run pytest -q` (apps/api) | 13 passed (health contract and sanitization, settings fail-closed and no-echo, worker heartbeat freshness, unregistered or unreachable-broker worker unhealthy) |
| `uvx ruff@0.15.0 check` / `format --check` (line length 120, ad hoc, no committed config) | pass / pass after formatting `worker.py` |
| `uv run --with mypy mypy --strict app` (ad hoc) | no issues in 11 files |
| `npx tsc --noEmit` and `next build` (apps/web) | exit 0; `/health/live` is dynamic (`ƒ`) |
| `shellcheck scripts/*.sh` | exit 0 (three SC2015 findings fixed) |
| `bash scripts/verify-setup.sh` and `scripts/verify-setup.test.sh` (P0.1 regression) | all pass; 11 passed, 0 failed |

**Not run:** CI (P0.3), the web test framework (P0.3), and committed lint/type configuration (P0.3).

### Security and privacy review

- Readiness responses and logs carry only dependency name, status and exception class. Settings errors carry only setting names, and `from None` drops the pydantic text that contains input values.
- `.env` is never in a build context, because both contexts are `apps/*` with allowlist-style `.dockerignore` files. Compose passes containers only `DATABASE_URL` and `REDIS_URL`, not the whole `.env`.
- **Known gaps for P0.4:** `Settings` URL objects would print the password if logged (nothing logs them today), and uvicorn access logs include query strings.

### Changed files

`compose.yaml`, `.env.example`, `README.md`, `docs/adr/ADR-009-worker-mechanism-rq.md`, `docs/runbooks/local-development.md`, `scripts/smoke-local.sh`, `scripts/recovery-local.sh`, `apps/api/{Dockerfile,.dockerignore,.gitignore,pyproject.toml,uv.lock}`, `apps/api/app/{__init__,__main__,main}.py`, `apps/api/app/api/{__init__,health}.py`, `apps/api/app/core/{__init__,settings}.py`, `apps/api/app/workers/{__init__,__main__,healthcheck,worker}.py`, `apps/api/tests/test_{health,settings,worker_health}.py`, `apps/web/{Dockerfile,.dockerignore,.gitignore,package.json,package-lock.json,next.config.ts,tsconfig.json}`, `apps/web/app/{layout,page}.tsx`, `apps/web/app/health/live/route.ts`. Commits: `60b36c0`, `9369a6b`, `484f46d`, `0793500`, `837060e`, plus this ledger commit.

### Rollback

1. `docker compose down` (no `-v`; the `hermecious_postgres-data` volume is kept).
2. `git revert` the P0.2 commits listed above.

No migrations or business data exist. Never use `docker compose down -v` as a rollback step.

### Blockers

None. **Owner actions:** accept or amend ADR-001 and ADR-009.

### Next safe step

Owner review of P0.2, then **P0.3** (CI, deterministic tests, migration harness). P0.3 must reuse this Compose stack and toolchain rather than define a second one. Do not start P0.3 until the owner approves it.
