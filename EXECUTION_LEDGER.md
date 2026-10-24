# Execution Ledger

The authoritative record of subphase progress. Statuses: `not-started`, `in-progress`, `verified`, `blocked`, `not-run` (see AGENTS.md). Entries are append-only, and corrections are recorded as new notes.

## Subphase status

| ID | Title (blueprint §4) | Status |
|---|---|---|
| P0.1 | AGENTS.md, README, ADR-001, ledger, `.env.example`, secrets rules | verified (ADR-001 accepted 2026-10-23) |
| P0.2 | Compose (API, web, Postgres, Redis, worker), health/readiness | verified (ADR-009 accepted 2026-10-23) |
| P0.3 | CI lint/typecheck/test, migrations, fixtures, time control | partially verified: all local gates pass; remote CI run not observed (A2 NOT RUN) |
| P0.4 | Structured logging, typed errors, config validation, secret masking | verified |
| P1.1 | Auth, sessions, CSRF, operator-only access (Batch 02) | verified |
| P1.2 | Core account/source/fact schema, rights policy, migrations (Batch 02) | verified |
| P1.3 | Versioned offers and approved capability claims (Batch 02) | verified |
| P1.4 | Account management API/UI, evidence entry, corrections (Batch 03) | verified |
| P1.5 to P12.4 | See blueprint §4 and `docs/phases/` | not-started |

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

## Note 2026-10-23: spec files moved, ADRs accepted (owner decisions)

- **Spec location (corrects P0.1 conflict 1 and the P0.2 starting-state note).** At the owner's direction, the blueprint moved to `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`. The phase packages (Batch 01, Batch 02) and the `OPUS_P1.x_PROMPT.md` files moved to `docs/phases/`, which is where Batch 02 and its prompts expect them. File contents are unchanged. README, AGENTS.md, ADR-001 and `scripts/verify-setup.sh` now point to the new paths. Earlier ledger entries keep the paths that were true when they were written.
- **ADR-001 and ADR-009 accepted by the owner on 2026-10-23.**
- **P1.1 preflight (Batch 02) was run and blocked:** P1.1 requires P0.3 and P0.4 to be VERIFIED, and both were `not-started`. The owner chose to run P0.3 next.

## P0.3 — CI, deterministic tests and migration harness (2026-10-23)

**Scope:** Batch 01 §P0.3 (`docs/phases/HERMECIOUS_BATCH_01_P0.2-P0.4.md`). CI workflow, the canonical validation command, a disposable integration DB and Redis, a minimal Alembic harness, deterministic time, API/web/DB contract tests and a testing runbook. **Not touched:** P1 business tables, jobs/outbox, browser E2E, performance suites.

### Starting state

`8abd44c` on `main`, clean. The P0.2 stack, with no migrations, no CI, no lint/type config and no web tests. Untracked `HERMECIOUS_BATCH_03_P1.4-P2.1.md` and `OPUS_P1.4/P1.5/P2.1_PROMPT.md` appeared during this work. They were left untracked and unread.

### Decisions and deviations

1. **The integration stack reuses `compose.yaml`.** It does not define a second stack. A `test` profile adds an `api-test` service (Dockerfile `test` stage). `scripts/test-integration.sh` runs it in a throwaway project `hermecious-test-<time>-<pid>` with `--env-file /dev/null`, a random password and database `hermecious_test`, and runs `down -v` for that project only on exit.
2. **Alembic baseline `0001` is empty.** It anchors the chain without creating P1 tables. `env.py` uses only the validated `DATABASE_URL`, with no `sqlalchemy.url` fallback. Offline `--sql` mode is refused. `app/persistence/base.py` defines the single declarative `Base` with a constraint naming convention, which P1.1 must reuse.
3. **Time:** `app/core/clock.py` provides `Clock`, `SystemClock`, `FixedClock` and `BUSINESS_TZ = Asia/Karachi`. Ruff `DTZ` rules forbid naive datetimes in app code.
4. **ESLint 10.13.0, not 9.** ESLint 9.39.5 is marked "no longer supported" by npm. `eslint-config-next@16.4.3`'s nested `eslint-plugin-react`, `-jsx-a11y` and `-import` declare peers that stop at ESLint 9, so npm overrides them (`ERESOLVE overriding peer dependency` warnings). I verified empirically that rules from all five plugins fire under v10: `@next/next/no-img-element`, `no-html-link-for-pages`, `@typescript-eslint/no-explicit-any`, `jsx-a11y/alt-text`, `react-hooks/exhaustive-deps`, `react/jsx-key` and `import/no-anonymous-default-export`, with probe file exit 1. **Risk:** a plugin could break on a future rule or syntax. That would surface as a lint failure, so it fails closed. Revisit when the plugins declare v10 support.
5. **Vitest 5.0.5** is the web test framework (blueprint test stack). `npm run typecheck` uses `next typegen`, so types do not depend on a prior build.
6. **API tests are split** into `apps/api/tests/{unit,contracts,integration}` and stay inside the Python project. The repo-root `tests/` is left for cross-app E2E and evals. `tests/` is now a package, because mypy saw two `conftest` modules otherwise.
7. **The P0.2 tests were annotated** to pass `mypy --strict`, and two intentional ruff findings were suppressed inline with reasons: S104 (bind to all interfaces inside the container) and S108 (fixed `/tmp` path in a single-user container).
8. **CI actions are pinned to commit SHAs** (checkout v7.0.1 `3d3c42e5`, setup-uv v10.3.2 `07a047e6`, setup-node v7.1.0 `949feb24`), with input names verified against each `action.yml`. The workflow has `permissions: contents: read` and `persist-credentials: false`. It pins uv 0.7.9 and Node 22.23.4.

### Acceptance evidence

| ID | Test / command | Observed | Result |
|---|---|---|---|
| A1 | `bash scripts/check.sh` at the final tree (`8813e52`) | 15/15 steps PASS, exit 0, about 32s (per-step times in summary) | PASS |
| A2 | GitHub Actions run of `.github/workflows/ci.yml` | Workflow pushed (`8813e52`). The run cannot be observed: local `gh` is authenticated as `hassan-ali-coderzhunt`, which gets HTTP 404 on the private repo (`gh run list -R cognetheus/hermecious`) | **NOT RUN** |
| A3 | API `test_clock` and web `health-live` assertions deliberately broken, then `check.sh` | exit 1; summary `FAIL(1) api: unit + contract tests`, `FAIL(1) web: test`, all else PASS. After `git checkout`, exit 0 | PASS (local) |
| A4 | `tests/integration/test_migrations.py::test_upgrade_head_is_repeatable` (fresh scratch DB, upgrade twice) | `alembic_version = ["0001"]` after both runs | PASS |
| A4 | `test_downgrade_to_base_and_back` | head → base (no `alembic_version`) → head | PASS |
| A4 | Dev DB via the runtime image: `docker compose run --rm --no-deps api python -m alembic upgrade head` twice, then `current` | First run `-> 0001`, second a no-op, `0001 (head)` | PASS |
| A5 | `test_invalid_database_url_refuses_to_migrate` (empty, malformed, `mysql://` with a secret) | non-zero exit, `refusing to run: missing or invalid settings: DATABASE_URL`, secret not in output | PASS |
| A5 | `test_unreachable_database_fails_without_fallback` | non-zero exit, `OperationalError`; no other DB used | PASS |
| A5 | Integration suite with `DATABASE_URL=.../hermecious` (non-test name) | `integration tests refused: DATABASE_URL must name a database ending in _test`, exit 2, before any connection | PASS |
| A5 | Integration suite without `HERMECIOUS_ENV=test` | `integration tests require HERMECIOUS_ENV=test`, exit 2 | PASS |
| A6 | `pytest tests/unit/test_clock.py tests/unit/test_worker_health.py` under `TZ=UTC`, `America/Los_Angeles`, `Pacific/Kiritimati` and `Asia/Karachi` | `10 passed` in every run | PASS |
| A7 | `scripts/test-integration.sh` (fresh project and volume each run) | `8 passed`; afterwards only `hermecious_postgres-data` (dev) remains, no `hermecious-test-*` project or volume | PASS |
| A8 | FastAPI app created and served via TestClient against real deps in the test image (`test_ready_with_real_dependencies`); `npm run build` | ready 200 with real Postgres and Redis; Next build exit 0 | PASS |

### Negative paths observed

| Case | Observed |
|---|---|
| Failing migration (`0001.upgrade` raises, temporarily) | Integration step `2 failed, 6 passed`, exit 1; restored → `8 passed` |
| **Secret in failure output (found and fixed)** | That broken-migration run first printed the scratch DB URL **with its disposable password** through pytest assertion rewriting. Tests now pass URLs as SQLAlchemy `URL` objects (masked repr). Rerun: 0 password-bearing URLs; output shows `postgresql://hermecious:***@postgres:5432/hermecious_scratch_<hex>_test` |
| Missing DB / unreachable DB | A5 rows above |
| Broken code (deliberately failing tests) | A3 |
| Parallel or duplicate test invocations | Two `test-integration.sh` runs at once: projects `...-5403` and `...-5404`, both `8 passed`, exit 0; both cleaned up |
| Flaky date tests | None possible by construction (`FixedClock`, no sleeps); A6 |
| GitHub permissions missing | A2: the observing account lacks repo access. The workflow itself requests only `contents: read` |
| Slow run | One full `check.sh` took over 10 minutes and passed (exit 0). The slow step was not identified; my process listing showed the delay came before `next build`, which suggests `npm ci` or the image rebuild, but that is unconfirmed. Timed reruns took about 32s, and per-step durations are now printed so a recurrence is diagnosable |

### Static checks (all inside `check.sh` unless noted)

ruff check and format (line length 120; rules E W F I B UP S SIM DTZ), `mypy --strict` (29 files), pytest 22 unit/contract plus 8 integration, ESLint `--max-warnings=0`, `next typegen && tsc --noEmit`, Vitest 2 tests, `next build`, shellcheck, `docker compose config`. Ad hoc: `actionlint .github/workflows/ci.yml` exit 0. actionlint is not in `check.sh` because CI runners do not ship it.

### P0.2 regression

`docker compose up --build -d` then `bash scripts/smoke-local.sh`: all smoke checks passed. `api-test` is not started by the default `up`.

### Changed files

`.github/workflows/ci.yml`; `scripts/{check,test-integration}.sh`; `compose.yaml` (`api-test` service); `apps/api/{Dockerfile,.dockerignore,pyproject.toml,uv.lock,alembic.ini}`; `apps/api/alembic/{env.py,script.py.mako,versions/0001_baseline.py}`; `apps/api/app/core/clock.py`; `apps/api/app/persistence/{__init__,base}.py`; `apps/api/app/__main__.py` and `app/workers/worker.py` (lint annotations only); `apps/api/tests/**` (restructured, new clock/schema/integration tests); `apps/web/{package.json,package-lock.json,eslint.config.mjs,vitest.config.ts}`; `apps/web/tests/health-live.test.ts`; `docs/runbooks/{testing,local-development}.md`; `README.md`; `AGENTS.md`. Commits: `2e5bdc7`, `8813e52`, plus this ledger commit.

### Rollback

`git revert` the P0.3 commits. The only migration is the empty baseline `0001`, so `alembic downgrade base` on a DB removes just `alembic_version`. The dev DB was migrated to `0001`. Disposable test projects are removed automatically. Never run `docker compose down -v` on the `hermecious` project.

### Blockers

- **A2 (remote CI) is NOT RUN.** To close it, either let me read Actions (log `gh` in as a user with access to `cognetheus/hermecious`), or open the repo's **Actions** tab and confirm that the `CI` run for `8813e52` is green. Ideally also push a deliberately failing commit on a branch and confirm it goes red.

### Next safe step

Close A2, then **P0.4** (structured logs, typed errors, validated config, redaction). P1.1's preflight requires P0.3 and P0.4 to be VERIFIED.

## P0.4 — Structured logs, typed errors, validated config and redaction (2026-10-23)

**Scope:** Batch 01 §P0.4. Executed at the owner's instruction to continue without pausing ("keep working don't pause"), while P0.3 A2 (remote CI observation) is still NOT RUN. **Not touched:** Sentry/OTel, alerts, analytics, message handling, web (Next.js) log format.

### Starting state

`1c025a5`, clean. Settings had only `DATABASE_URL`/`REDIS_URL`. Logging was the stdlib default with plain-text uvicorn and RQ output. There was no error envelope, so FastAPI defaults leaked validation inputs in 422 bodies. There were no request IDs.

### Decisions

1. **One settings component** (`app/core/settings.py`). `HERMECIOUS_ENV` is now **required** (`development|test|production`, no default, so there is no hidden fallback). Also `HERMECIOUS_LOG_LEVEL` (default INFO). Production rejects DEBUG. The `Settings` repr masks URLs. `SettingsError.names` carries setting names only.
2. **Stdlib logging with our own `JsonFormatter`**, no new dependency. **Allowlist** context keys (`SAFE_CONTEXT_KEYS`); everything else becomes `[REDACTED]`, recursively. **Scrubbing** applies to every string, including third-party messages and tracebacks.
3. **Uvicorn access logs are disabled** (they carry query strings). The middleware emits `http.request` with the path only.
4. **Pure ASGI `RequestContextMiddleware`**, rather than `BaseHTTPMiddleware`, so the contextvar is reliable. It is the outermost app middleware, catches unhandled exceptions before Starlette's `ServerErrorMiddleware`, and so attaches `X-Request-ID` and the envelope to 500s.
5. **4xx statuses outside the category list** (for example 405) keep their status and use `VALIDATION_ERROR`. **5xx** responses use `INTERNAL_ERROR`, except dependency outages, which use 503 `DEPENDENCY_UNAVAILABLE`.
6. **Worker tracing:** `TracingMixin.perform_job` binds the job's `trace_id` meta (validated) or a fresh `job_` ID for one job only. RQ runs with `log_job_description=False` because job arguments may hold personal data.
7. **Compose** passes `HERMECIOUS_ENV` (required) and `HERMECIOUS_LOG_LEVEL` to api and worker. `.env.example`, `test-integration.sh` and `check.sh` were updated.
8. **Bookkeeping:** commit `6830282` also picked up the owner's new `docs/phases/HERMECIOUS_BATCH_04_P2.2-P2.4.md` and `OPUS_P2.2–P2.4_PROMPT.md` files (unchanged), because they were present under `docs/` when it was staged.

### Acceptance evidence

| ID | Test / command | Observed | Result |
|---|---|---|---|
| A1 | Real container: `curl -H 'X-Request-ID: p04-evidence-0001' '/health/live?token=QUERY-SECRET&phone=03001234567'` | Response `x-request-id: p04-evidence-0001`. Log line `{"service":"api","event":"http.request","request_id":"p04-evidence-0001","context":{"method":"GET","path":"/health/live","status":200,...}}`, with no query string | PASS |
| A1 | `test_request_correlation.py::test_generated_id_matches_header_and_log`, `test_safe_client_id_is_propagated` | Generated `req_` ID equals the header and the log field | PASS |
| A2 | `test_error_envelope.py::test_validation_error_is_422_without_submitted_data`, `test_malformed_json_is_a_safe_validation_error` | 422 `VALIDATION_ERROR`, `retryable=false`, submitted values absent | PASS |
| A3 | `test_unhandled_error_is_500_without_traceback` | 500 `{"code":"INTERNAL_ERROR","message":"Internal error",...}`. No `Traceback`, class name, secret or path in the body. Log has `http.unhandled_exception` with the same `request_id` and a scrubbed traceback | PASS |
| A4 | `test_dependency_failure_is_retryable_503[postgres-down, redis-down]`, typed `DependencyUnavailable` | 503 `DEPENDENCY_UNAVAILABLE`, `retryable=true`, no hostnames or secrets | PASS |
| A5 | Real container: `docker compose run --rm --no-deps -e HERMECIOUS_ENV= -e DATABASE_URL='mysql://u:LEAK-P04@x/y' api` | exit 1; `{"level":"critical","event":"config.invalid","context":{"settings":["DATABASE_URL","HERMECIOUS_ENV"]}}`; `LEAK-P04` in logs: 0 | PASS |
| A5 | `test_entrypoints.py` (api and worker) and `test_settings.py` (unknown env, production+DEBUG, masked repr) | Names only; values never printed | PASS |
| A6 | `test_redaction.py` seeds a nested password, API key, cookie, DB URL, phone, message body, email and bearer token | None of the seeded values appear in output | PASS |
| A6 | Real logs of all services after the runs above | password 0, `QUERY-SECRET` 0, `03001234567` 0, `a@b.co` 0; non-JSON api/worker lines 0 | PASS |
| A7 | `test_concurrent_requests_never_share_context` (100 interleaved ASGI requests) | 100 distinct IDs; each handler saw its own ID before and after `await` | PASS |
| A7 | `tests/integration/test_trace_context.py` (real Redis, SimpleWorker): from-request, standalone and tampered-meta jobs, plus a failed job and its follow-up | The job inherits the request ID; standalone and tampered jobs get distinct `job_` IDs; no leakage after failure; context `None` afterwards | PASS |
| A8 | `test_request_context.py` (11 unsafe IDs) and `test_hostile_client_ids_are_replaced` (100 kB ID, JSON injection, newline, markup); real 300-character ID | All replaced with a 36-character `req_` ID; exactly one log line; hostile text absent | PASS |

### Negative paths

| Case | Observed |
|---|---|
| Third-party noisy logs | uvicorn, RQ and Alembic all route through `JsonFormatter`; httpx/sqlalchemy pinned to WARNING |
| Malformed exception / hostile object | An object whose `__str__` and `__repr__` raise logs as its class name. A bad `%` format gives `log.format_error` with no crash |
| Sink errors | `logging.raiseExceptions = False`; documented limitation (dropped silently) |
| Worker failure before cleanup | A failed job still clears context (A7) |
| Validation exceptions | A2 |
| **Found and fixed:** `redis://:password@host` (empty username) was not scrubbed | Caught by `test_percent_args_are_scrubbed_after_formatting`. The pattern now allows an empty username |
| Cancellation | `CancelledError` is a `BaseException`, so it is not caught; the contextvar reset runs in `finally`. Not separately tested |

### Regression

`bash scripts/check.sh`: 15/15 PASS (API unit + contract 87 tests, integration 10). P0.2: `scripts/smoke-local.sh` and `scripts/recovery-local.sh` all PASS. Worker recovery after the Redis outage took 41s this run (RQ backoff, within the 150s bound).

### Changed files

`apps/api/app/core/{settings,logging,errors,request_context}.py`, `apps/api/app/api/{middleware,health}.py`, `apps/api/app/{main,__main__}.py`, `apps/api/app/workers/{tracing,worker}.py`, tests (`unit/test_{redaction,request_context,entrypoints,settings,worker_health}.py`, `contracts/test_{error_envelope,request_correlation,health_contract}.py`, `integration/test_trace_context.py`, `conftest.py`), `compose.yaml`, `.env.example`, `scripts/{check,test-integration}.sh`, `docs/runbooks/observability.md`, `README.md`. Commit `6830282`.

### Rollback

`git revert 6830282`. There is no schema change. Do not disable redaction as a fix. After a revert, `.env` still contains `HERMECIOUS_LOG_LEVEL`, which is harmless.

### Next

P1.1 (Batch 02). Its preflight needs P0.1–P0.4 VERIFIED; P0.3 is partial only because remote CI is unobserved. The owner directed continuous execution, so P1.1 proceeds and records this gap.

## P1.1 — Persistent authentication, sessions and authorization (2026-10-23)

**Scope:** `docs/phases/HERMECIOUS_BATCH_02_P1.1-P1.3.md` §P1.1 and `OPUS_P1.1_PROMPT.md`. **Base SHA:** `0cb583a`. **Head:** `01886f2`, plus this ledger commit.

### Preflight

| Prerequisite | Status |
|---|---|
| P0.1, P0.2, P0.4 | VERIFIED (ledger evidence above) |
| P0.3 | PARTIALLY VERIFIED: every local gate passes, and A2 (observing remote CI) is NOT RUN. P1.1 proceeded under the owner's explicit "keep working, don't pause" instruction, and this gap is carried forward |
| Existing conventions reused | Single `Settings`, single declarative `Base` and naming convention, Alembic chain (`0001` → new `0002`), P0.4 error envelope and `X-Request-ID`, JSON logging and redaction, `FixedClock`, `scripts/test-integration.sh`, Compose service names |

### Decisions

ADR-010 records the sequencing correction (P1.1 owns `organizations`/`users`/`auth_sessions`; P1.2 reuses them), the session scheme (`<uuid hex>.<256-bit verifier>`, sha256 at rest, `hmac.compare_digest`), the CSRF scheme (HMAC of the verifier plus exact `Origin`/`Referer`), the login limits (Redis, fail closed), and the role and capability model. Other notes:
- **Default-deny:** `assert_api_routes_protected(app)` runs in `create_app`. It enumerates routes with FastAPI's public `fastapi.routing.iter_route_contexts`, because **FastAPI 0.162 no longer flattens included routers into `app.routes`**. The first version of the guard silently checked nothing; the contract test caught it, and the fix fails closed for any route it cannot inspect.
- **Interactive docs and OpenAPI are disabled** (`/docs`, `/redoc`, `/openapi.json` return 404).
- **Proxy headers are not trusted** (`proxy_headers=False`); the client IP is the direct peer.
- **`/auth/session-status` was intentionally omitted** in favour of `/auth/me`.
- **Web:** Next rewrites `/api/v1/*` to `API_INTERNAL_URL` (baked at build time, default `http://api:8000`). `/` checks the session server-side and redirects to `/login`. The CSRF token is held in memory only.
- **Bookkeeping:** commit `01886f2` also added the owner's new `docs/phases/OPUS_P3.1–P3.3_PROMPT.md` files (unchanged), because they were present when `docs/` was staged.

### Acceptance evidence

| ID | Executed test / command | Result summary | Status |
|---|---|---|---|
| AUTH-01 | `test_bootstrap_creates_one_org_and_owner_and_refuses_a_second`, `test_concurrent_bootstraps_create_exactly_one_owner` (4 threads), `test_bootstrap_rejects_weak_passwords` (3), `test_bootstrap_cli_has_no_password_flag_and_needs_a_tty` | 1 org and 1 owner; second attempt refused; concurrent attempts gave `created, refused×3`; `--password` is an unrecognized argument; piped stdin refused (exit 2) | PASS |
| AUTH-01 | Real clean-room stack: `alembic upgrade head`, then the bootstrap CLI driven through a pty with `expect` | `bootstrap: organization and owner created`; second run `bootstrap: refused: already bootstrapped`; DB has 1 org, `owner \| $argon2id$v=19$m=65536,t=3,p=1$` | PASS |
| AUTH-02 | `test_bad_password_unknown_email_disabled_user_and_suspended_org_look_identical`, `test_email_lockout_after_five_failures_even_with_correct_password`, `test_ip_budget_limits_enumeration_across_emails` | Four identical 401 bodies, no cookie, no session rows, no email or password in logs. Sixth attempt 429 with `Retry-After` ≤ 900 even with the correct password; other accounts unaffected; window expiry restores login. 31st IP attempt 429 | PASS |
| AUTH-03 | `test_login_sets_hardened_opaque_cookie_and_me_is_safe`, `test_csrf_endpoint_requires_session_and_returns_bound_token`; real flow through the web origin | `HttpOnly; Path=/; SameSite=lax; Max-Age=86400`, no `Domain`. Body has a safe summary and the CSRF token. DB stores `sha256(verifier)` only. The verifier, cookie and password are absent from logs. No `localStorage` use anywhere in `apps/web` | PASS |
| AUTH-04 | `test_tampered_cookies_are_rejected_and_cleared` [verifier, unknown_id, malformed, empty], `test_idle_expiry_and_exact_edge`, `test_absolute_expiry_cannot_be_extended_by_activity`, `test_last_seen_is_written_at_most_every_five_minutes` | 401 with cookie cleared, and session rows unchanged (not revoked or prolonged). Idle expiry at exactly `idle_expires_at` → 401. Activity every 4h cannot pass 24h. `last_seen_at` written only after 5 min | PASS |
| AUTH-05 | `test_logout_revokes_immediately_and_replay_fails`, `test_disabling_the_user_revokes_live_sessions`, `test_suspending_the_organization_blocks_sessions`, `test_credential_change_invalidates_older_sessions`; real flow | Replaying the old cookie gives 401 on `/me` and logout. Disabled user and suspended org give 401 with the session revoked. Credential change rejects older sessions | PASS |
| AUTH-06 | `test_logout_without_valid_csrf_and_origin_is_403_and_changes_nothing` [missing-token, wrong-token, cross-origin, null-origin, no-origin, cross-referer, lookalike], `test_same_origin_referer_is_accepted_when_origin_is_stripped`, `test_csrf_token_from_a_rotated_session_is_rejected`, `test_login_csrf_defences` | 403 envelope; `revoked_at`, `last_seen_at` and `idle_expires_at` unchanged, and the session still works. Cross-site or origin-less login 403; form and text/plain login 400; no session rows | PASS |
| AUTH-07 | `test_role_matrix_denies_lower_roles_before_any_effect` (owner, operator, observer × read/mutate/draft/publish), `test_client_supplied_organization_is_ignored`, `test_anonymous_requests_never_reach_handlers`, `test_route_protection.py` (4 contract tests) | Owner: all 200. Operator: read and draft 200; mutate and publish 403. Observer: read only. Handler side effects are recorded only for allowed calls. `?organization_id=<other>` is ignored. Every private route 401s anonymously. An unprotected route fails startup | PASS |
| AUTH-08 | `test_sessions_survive_an_api_restart`, `test_redis_outage_fails_login_closed_but_keeps_sessions`, `test_database_outage_is_a_safe_503`. Real stack: `docker compose restart api`, then `docker compose stop redis` | `/me` 200 after an API restart. Login 503 `DEPENDENCY_UNAVAILABLE` while Redis is down, while the existing session still gets 200; login 200 after Redis returns. DB down gives 503 with no secret. Idle/absolute limits as in AUTH-04 | PASS |
| AUTH-09 | `test_auth_units.py`: `test_unsafe_production_configurations_are_rejected` [insecure-cookie, http-origin, mixed-origins, debug-logging], `test_origins_must_be_exact_in_every_environment` (10 cases including `*`), `test_idle_cannot_exceed_absolute` | Each is rejected with the offending setting's name only | PASS |
| AUTH-10 | `bash scripts/check.sh` | 15/15 PASS (API unit + contract 122 tests; integration 55; web lint/typecheck/test/build). `scripts/smoke-local.sh` PASS on the rebuilt dev stack, and the dev DB migrated `0001 -> 0002` | PASS |

### Real end-to-end flow (throwaway stack `hermecious-p11e2e`, web origin `http://localhost:13001`; removed afterwards with `down -v`)

1. Anonymous `/` → 307 to `/login`.
2. Wrong password → 401. Cross-site login → 403.
3. Login through the web proxy → 200, with `set-cookie: hermecious_dev_session=<id>.<verifier>; HttpOnly; Max-Age=86400; Path=/; SameSite=lax`.
4. `/` renders "Signed in as E2E Owner".
5. Logout without CSRF → 403.
6. `docker compose restart api`, then `/me` → 200.
7. Redis stopped: login → 503 and `/me` → 200. Redis back: login → 200.
8. Logout with CSRF → 204, then replay `/me` → 401 and `/` → 307.
9. Log scan: password 0, verifier 0, email 0, CSRF token 0.

Auth events seen: `csrf_rejected`×2, `login_denied`, `login_succeeded`×2, `logout`, `session_rejected`×2, `session_revoked`.

**Argon2id benchmark:** verify median 107 ms on the host and 108 ms in the container (t=3, m=64 MiB, p=1).

### Negative tests and failure-state observations

- **Parallel logins:** 5 threads → 5 distinct sessions.
- **Logout racing a request:** the request gets 200 or 401, and afterwards the session is unusable.
- **Session fixation:** the presented session is revoked and the old cookie gives 401.
- **Clock-edge expiry:** see AUTH-04.
- **Log injection in the email field:** no forged `auth.login_succeeded` event.
- **Malformed cookie:** see AUTH-04.
- **Transient DB or Redis outages:** see AUTH-08.
- **Mutation check:** making the CSRF check always pass and `verifier_matches` always return True made 4 integration tests fail (tampered-verifier, missing-token, wrong-token, rotated-token). **Process note:** the restore with `git checkout` failed because the files were not yet tracked, so I reverted by hand, confirmed no `MUTATION` markers remained, and reran the suite (55 passed) before committing. Lesson: commit before mutating.
- **Intermittent failure found and fixed:** pytest's unraisable-exception hook failed one `check.sh` run because of an unclosed Redis socket. Causes: unclosed test Redis clients, and the app never closing its Redis or engine. Fixed with `close_app()`, a lifespan hook and closing every test connection. **Three consecutive integration runs:** 55 passed each, 0 unraisable.
- **pty bootstrap automation:** a first attempt that piped input into `script` hung, because the input arrived before `getpass` read it, and it echoed a throwaway test password into the transcript. Nothing was created with that password, it was rotated, and the clean room was destroyed. Final automation used `expect`, which waits for each prompt.

### Migration and data safety

`0002` creates three tables: FKs, `users(organization_id, email_canonical)` unique, CHECKs (status, role, lowercase email, verifier hash format, idle ≤ absolute, absolute > issued), and indexes on `auth_sessions(user_id)` and `(absolute_expires_at)`.
- Upgrade/downgrade: `test_downgrade_to_base_and_back` (head → base → head) passes on a scratch DB.
- Model/schema drift: `test_models_match_migrations` reports `compare_metadata` diff `[]`.
- The dev DB is migrated to `0002`. No owner was created there: the owner runs the bootstrap themselves (runbook).

### Security and privacy review

- **Identity source:** organization and role come only from the DB row.
- **No CORS, no JWT, no `localStorage`.**
- **Cookie:** `HttpOnly` + `SameSite=Lax`; production forces `__Host-` + `Secure` + HTTPS origins.
- **CSRF:** verified before any write.
- **Enumeration:** uniform 401 bodies, and a dummy-hash verification for unknown users.
- **Rate limiting:** limits fail closed.
- **Logs:** no email, password, cookie, verifier or CSRF token (asserted).
- **Bootstrap:** never prints personal data.
- **Residual risks:**
  - A Redis restart resets the rate-limit counters.
  - A wrong-verifier probe does not revoke the session, by design (DoS avoidance), so brute force relies on the 256-bit verifier.
  - The login form is not covered by browser E2E (P7.5).

### Changed files (with reasons)

| File | Reason |
|---|---|
| `apps/api/alembic/versions/0002_identity.py` | Identity tables |
| `apps/api/app/auth/{models,passwords,tokens,rate_limit,service,dependencies,routes,bootstrap}.py` | Auth implementation |
| `apps/api/app/persistence/{db,registry}.py` | Session factory and `DbSession` dependency; model registration for Alembic |
| `apps/api/app/core/settings.py` | Origins, cookie and session lifetime settings with production rules |
| `apps/api/app/main.py`, `__main__.py` | Wiring, route guard, lifespan cleanup, `proxy_headers=False` |
| `apps/api/app/workers/worker.py` | Health check closes its Redis connection |
| `apps/api/alembic/env.py` | Registers models |
| `apps/api/pyproject.toml`, `uv.lock` | argon2-cffi 25.1.0; tests may hold fixed passwords (S105/S106) |
| `apps/api/tests/**` | `factories.py`; unit `test_auth_units.py`; contract `test_route_protection.py`; integration `conftest.py`, `db.py`, `auth_helpers.py`, `test_auth.py` (52 tests), drift test; updates for the new settings |
| `apps/web/{next.config.ts,lib/api.ts,app/page.tsx,app/login/page.tsx,app/logout-button.tsx}` | Login UI and protected shell |
| `compose.yaml`, `.env.example`, `scripts/{check,test-integration}.sh` | New settings and `API_INTERNAL_URL` |
| `docs/adr/ADR-010-identity-and-server-sessions.md`, `docs/runbooks/auth.md`, `README.md`, `docs/runbooks/local-development.md` | Documentation |

### Rollback

- **Disposable DB:** `alembic downgrade 0001`.
- **Data-bearing DB:** back up, review users and live sessions, prefer a forward fix, and never re-open private routes anonymously.
- **Code:** `git revert 01886f2 5fecce7`.
- **Never** `docker compose down -v`.

### VERDICT: VERIFIED

The P0.3 remote-CI observation gap is carried forward. P1.2 is next (owner-directed continuous execution).

## P1.2 — Core account, source, provenance and facts database (2026-10-23)

**Scope:** Batch 02 §P1.2 and `OPUS_P1.2_PROMPT.md`. **Base:** `2eaa12d` (`df5e77d` added prompts only). **Head:** `519607b` (code), plus the docs and ledger commit.

### Preflight

P1.1 is VERIFIED. P0.3's remote-CI gap is carried forward. The existing pieces reused are `organizations` (no re-creation), `Actor`, `ROLE_CAPABILITIES`, the single `Base` and naming convention, Alembic (`0002` → `0003`), the P0.4 typed errors, the integration fixtures and `FixedClock`.

### Decisions

- **Feature package `app/accounts/`** (models, policy, claims, service), consistent with `app/auth/`.
- **Composite FKs have explicit short names.** Convention-generated names exceeded Postgres's 63-character limit and were silently truncated with a hash, which would make hand-written migrations drift.
- **`areas` uniqueness** uses an expression index over `(org, lower(city), coalesce(lower(district), ''))`. The batch warned about nullable semantics: a plain unique constraint would treat NULL districts as distinct.
- **Duplicate `(org, provider, external_key)` gives `Conflict` (409)** rather than silently returning the existing row. P2 ingestion decides on idempotent reuse explicitly.
- **Provider allowlist** (`manual_entry`, `owner_seed_list`, `first_party_website`, `google_places` metadata-only with place ID, `fixture`). Unknown providers are refused.
- **The claim registry has no "absent" values**, and unknown values can only be hypotheses. New facts must be `source_supported` or `hypothesis`.
- **No routes were added** (accounts API and UI are P1.4). The default-deny route contract still passes.
- **Test infrastructure fix:** `clean_state` no longer truncates migration-seeded reference tables (`verticals`). The first run failed with `NotFound` for every account test because of that.
- **Mapping fix:** SQLAlchemy needs `version_id_col` as a column object, not a string; corrected before the first green run.

### Acceptance evidence

| ID | Executed test / command | Result summary | Status |
|---|---|---|---|
| DATA-01 | `test_core_domain_objects_exist_and_reupgrade_is_a_noop`, `test_upgrade_head_is_repeatable` (HEAD `0003`), `test_models_match_migrations` | 6 tables, the composite FKs, CHECKs, partial and expression unique indexes and the seeded `schools` vertical are present. The second upgrade prints no `Running upgrade`, and the catalog is identical. ORM/schema drift `[]` | PASS |
| DATA-02 | `test_downgrade_of_populated_core_domain_preserves_identity`, `test_downgrade_to_base_and_back` | Populated with an org, user, session and account, then `downgrade 0002`: P1.2 tables are gone and the user and session rows remain. Re-upgrade gives empty accounts with 1 user kept | PASS |
| DATA-03 | `test_lahore_school_with_source_supported_fact` | Synthetic Lahore account; fact joined to its source with provider, `full_allowed`, rights version, `observed_at`; `is_stale=False` | PASS |
| DATA-04 | `test_source_supported_without_source_is_rejected_by_service_and_database` | Service: `InvalidRequest("...requires a source record")`. Raw SQL: `CheckViolation ck_account_facts_supported_requires_source`. 0 facts | PASS |
| DATA-05 | `test_cross_org_links_fail_in_the_database` (3 raw inserts), `test_cross_org_service_access_looks_like_not_found` (5 paths) | `ForeignKeyViolation` on `fk_account_facts_org_account`, `fk_account_facts_org_source` and `fk_account_aliases_org_account`. Service reads and writes across orgs give `NotFound`, as do unknown ids. 0 rows | PASS |
| DATA-06 | `test_duplicate_external_key_and_alias_are_safe_conflicts`, `test_concurrent_duplicate_sources_store_exactly_one` (6 threads) | Second identical key gives `Conflict` (409, safe message), while the same key in another org is allowed. Punctuation/case variant alias gives `Conflict`. Concurrent: `created` ×1, `conflict` ×5, 1 row | PASS |
| DATA-07 | `test_same_normalized_name_in_two_localities_stays_two_accounts` | Same normalized name in Johar Town and DHA Phase 5: 2 accounts, never merged | PASS |
| DATA-08 | `test_forbidden_sources_are_rejected_and_nothing_persists` (18 cases), `test_payload_requires_full_rights_in_the_database`, `test_expired_source_cannot_support_new_facts`, `test_excerpt_rights_and_bounds` (4) | Rejected: unlisted provider, forbidden class, Places content, Places without key, metadata IP, private IP, `[::1]`, localhost, single-label host, metadata host, userinfo, `?token=`, fragment, ftp, `javascript:`, http for an https-only provider, bidi override, >2048 characters. The payload CHECK fires at DB level. Expired source refused for new facts. Excerpts refused on metadata/derived-only sources, >1000 characters or NUL. 0 rows each time | PASS |
| DATA-09 | `test_hypothesis_is_distinct_and_unknown_stays_unknown`, `test_invalid_or_overclaiming_facts_are_rejected` (12), `test_offset_timestamps_are_normalized_to_utc`, `test_fact_becomes_stale_when_its_source_expires` | Hypotheses are stored without a source and shown separately. Rejected: count 0, string count, extra field, software "none", website "absent", likelihood-to-buy, personal phone claim, unknown as a supported finding, strong hypothesis, disputed-on-create, naive timestamp, future timestamp. `+05:00` stored as UTC. Facts on an expired source show `is_stale=True` | PASS |
| DATA-10 | `bash scripts/check.sh` | 15/15 PASS (integration 112 tests; unit + contract 122). The route-protection contract shows no new or anonymous routes. Dev DB migrated `0002 -> 0003`; smoke PASS | PASS |

### Failure paths

- **Malicious Unicode:** blank, RLO override and NUL names are rejected; Urdu names are NFKC-normalized and kept.
- **Unknown or inactive vertical:** `NotFound`.
- **Nested transaction rollback:** a failed flush inside a savepoint leaves no partial row and the session stays usable.
- **Concurrent inserts:** see DATA-06.
- **Optimistic concurrency:** a stale writer gets `StaleDataError`, and the first write is kept at version 2.
- **Incorrect timestamp offset:** see DATA-09.
- **Source expiring after a fact was created:** see DATA-09 staleness.
- **Interrupted migration and transient DB loss:** not separately simulated in P1.2. Migrations run one transaction per revision (`transaction_per_migration=True`), and DB loss maps to 503 (P0.4/P1.1 tests).

### Mutation checks (committed first, then restored with `git checkout`; tree verified clean)

| Mutation | Caught by |
|---|---|
| `_is_internal_host` never blocks IP literals | 3 failures: metadata-ip, private-ip, loopback-v6 |
| `_account` lookup drops `organization_id` scoping | 1 failure: `test_cross_org_service_access_looks_like_not_found` |

The first attempt at the second mutation was invalid (a comment swallowed a parenthesis, so the module failed to compile). It was redone with a compiling mutant before recording.

### Dependency audit

No dependency or lockfile changes in P1.2 (`git diff 01886f2 HEAD` on the lockfiles is empty).
- `pip-audit` over the 125 locked Python requirements: **No known vulnerabilities found**.
- `npm audit` (web, all deps): **0 vulnerabilities**.

### Security, privacy and data rights

- No real school, person, phone or address data. Fixtures are fictional and use `.example` domains.
- No contacts or contact values are stored as facts.
- No negative-absence claims.
- Provider rights are enforced before storage, and Google Places content storage is excluded.
- Cross-org isolation is enforced by both DB composite FKs and service scoping.
- No raw payloads are logged; services do not log row contents.
- **Residual risks:**
  - URL screening is ingestion-only; there is no DNS resolution, so a public hostname resolving to a private IP is caught only at fetch time (P2.1/P11.1).
  - The provider allowlist lives in code; changing it needs a reviewed change.

### Changed files

| File | Reason |
|---|---|
| `apps/api/alembic/versions/0003_core_domain.py` | P1.2 schema and the `schools` seed |
| `apps/api/app/accounts/{models,policy,claims,service}.py` | Domain |
| `apps/api/app/persistence/registry.py` | Register models |
| `apps/api/tests/integration/{lahore_fixtures,test_accounts}.py` | Synthetic fixtures and DATA tests |
| `apps/api/tests/integration/{test_migrations,conftest}.py` | DATA-01/02 and the reference-table-safe cleanup |
| `docs/contracts/core-domain.md`, `README.md` | Documentation |

### Rollback

- **Disposable DB:** `alembic downgrade 0002` (tested; P1.1 data preserved).
- **Data-bearing DB:** back up and prefer a reviewed forward repair. Never drop fact or source tables to restore code, and never `down -v`.
- **Code:** `git revert 519607b`.

### VERDICT: VERIFIED

P1.3 is next.

## P1.3 — Versioned offers and approved capability claims (2026-10-24)

**Scope:** Batch 02 §P1.3 and `OPUS_P1.3_PROMPT.md`. **Base:** `f505396`. **Head:** `a07435c` (code), plus the docs and ledger commit.

### Preflight

P1.2 is VERIFIED; the P0.3 remote-CI gap is carried forward. The existing pieces reused are `verticals` (`schools`), `users`/`organizations`, `authorize_request` (CSRF, default owner-only mutations), `allow_roles`, `require_capability(PUBLISH)`, the P0.4 errors, Alembic (`0003` → `0004`) and the integration harness. No pre-existing offer schema existed.

### Decisions

1. **The offer ↔ revision cycle** is handled by creating the offer → revision composite FKs after both tables (`use_alter`).
2. **The database guarantees immutability:** a PL/pgSQL trigger blocks content changes, deletes and illegal state transitions. Application rules alone could be bypassed by an ORM or SQL write.
3. **`users` gains `UNIQUE(organization_id, id)`.** This is additive and needed so `created_by`/`approved_by` are organization-scoped FKs. It is the only change to a P1.1 table and does not alter behaviour.
4. **`approved_claims_json`** stores the author's *proposed* approvals. Publication re-validates every one, and the sales-ready projection serves only published revisions, so a draft cannot sell.
5. **Commitment guard:** approved claims and price text may not contain delivery timing, SLA or uptime, guarantees, or "integrates with". Free-text promises are refused outright, because there is no structured, evidenced way to represent them yet.
6. **Sales-ready on a non-sellable offer returns 409** `Offer has no published, sellable revision`, the documented domain denial. A foreign or unknown offer returns 404.
7. **Observers see only published revisions**, never drafts.
8. **New `AppClock` dependency** (`app/api/dependencies.py`): routes use the app's injected clock, so `FixedClock` applies in tests.
9. **UI:** `/offers` and `/offers/[id]`, rendered server-side. Readiness labels read Available, Limited, Planned, Unverified or Not supported. The owner gets publish and archive buttons; owners and operators get a JSON textarea that creates a new draft revision. Text is rendered escaped.
10. **Seed:** `python -m app.offers.seed`, idempotent. It requires exactly one active owner and never publishes.

### Acceptance evidence

| ID | Executed test / command | Result summary | Status |
|---|---|---|---|
| OFFER-01 | `test_seeded_school_draft_is_unpublished_with_no_claims_or_prices`, `test_seed_cli_needs_exactly_one_owner_and_never_publishes`; real stack: seed CLI twice | Listed as `school_admin_starter`, draft, draft revision 1. All 4 modules unverified; no approved claims, prices or evidence. Sales-ready 409; publishing the seed gives 400. CLI refuses without an owner; with an owner it is idempotent (1 offer, all drafts). Real run printed `seed: offer school_admin_starter is draft (version 2); nothing was published` both times | PASS |
| OFFER-02 | `test_operator_drafts_but_cannot_publish`, `test_observer_is_read_only_and_never_sees_drafts` | Operator creates the offer and revision (201); publish 403; DB still draft. Observer cannot create (403), sees `[]` revisions for a draft, and publish gives 403 | PASS |
| OFFER-03 | `test_unsellable_readiness_in_approved_claims_blocks_publication` [planned, unverified, not_supported], `test_unsubstantiated_claims_block_publication` [no evidence, no approval note, limited without limitations] | 400 with a precise message. Offer status, version and `published_revision_id` unchanged; revision still draft with no approver | PASS |
| OFFER-04 | `test_valid_revision_publishes_one_atomic_snapshot` | 200. `approved_by` is the owner, `approved_at == published_at`, `content_sha256` equals the draft digest and an independently recomputed digest. Sales-ready lists only `fee_tracking` and `admissions_intake` (limited, with limitations); `parent_portal` (planned) is absent; `pricing_unavailable` | PASS |
| OFFER-05 | `test_published_snapshot_is_immutable_and_new_drafts_do_not_replace_it` | A new draft does not change sales-ready (still revision 1, same digest). Raw SQL changing claims, digest, state or approval time, and `DELETE`, all raise `CheckViolation` from the trigger. An ORM edit of `price_rules_json` fails ("immutable"). Digest unchanged afterwards | PASS |
| OFFER-06 | `test_concurrent_publishers_with_the_same_version_one_wins`, `test_stale_writers_get_409`, `test_publish_racing_archive_leaves_a_consistent_state` | Concurrent publishes give `[200, 409]`, with exactly one published revision matching `published_revision_id`. A stale revision create or publish gives 409 with no row. Publish vs archive race gives `[200, 409]`, and the final state is consistent either way | PASS |
| OFFER-07 | `test_archive_withdraws_selling_but_keeps_history` | Archive 200, then sales-ready 409. History still shows revision 1 `retired` with `published_at` kept. New revision and publish give 409 | PASS |
| OFFER-08 | `test_other_organizations_cannot_see_or_touch_offers` | The intruder's list is empty; detail and sales-ready give 404 without the code in the body; archive gives 404. A raw cross-org revision insert raises `ForeignKeyViolation fk_offer_revisions_org_offer` | PASS |
| OFFER-09 | `test_pricing_must_be_approved_with_evidence`, `test_invalid_price_rules_are_rejected_at_draft_time` [negative, zero, 3 decimals, USD, unit], `test_invented_commitments_cannot_be_published` [go-live, delivered in, 99.9% uptime SLA, integrates with] | An unapproved price blocks publication (400). An approved price with evidence publishes, and sales-ready shows exactly the approved rule. Invalid prices give 422 at draft time with no row. Commitment text gives 400 "…commitment". No prices gives `pricing_unavailable` | PASS |
| OFFER-10 | `test_csrf_anonymous_and_malformed_requests_are_denied_without_effect`, `test_markup_and_control_characters_are_rejected_in_claims` [html, bidi, markup-injection], `test_malformed_capability_content_is_rejected` (6), `test_duplicate_offer_code_is_a_conflict`, `bash scripts/check.sh` | Missing or forged CSRF gives 403; anonymous 401; malformed JSON and unknown fields 422; offer unchanged. Markup and bidi text gives 422 without echoing `<script>`. Empty, duplicate, ambiguous-name, unknown-readiness, unlisted-evidence and URL-as-evidence content gives 422. Duplicate code 409. `check.sh` 15/15 PASS (integration 151, unit + contract 122). Dev DB migrated `0003 -> 0004`; smoke PASS | PASS |

### Failure simulations

- **Database failure mid-publish:** `test_database_failure_mid_publish_rolls_back` injects `OperationalError` after the version bump. Result: 503 `DEPENDENCY_UNAVAILABLE`, and the offer stays draft with the same version and no partial publish.
- **Workflow after archive:** see OFFER-07.
- **Malformed matrix and ambiguous names:** see OFFER-10.
- **Race between publish and archive:** see OFFER-06.
- **Prompt or markup injection in a summary:** rejected at input. Rendering is escaped by React, and sales-ready carries only structured approved fields.

### Real end-to-end flow (throwaway stack `hermecious-p13e2e`, web origin `http://localhost:13002`; removed with `down -v`)

1. Migrations `→0004`. Bootstrap through `expect` gives `organization and owner created`. Seed twice: draft both times, nothing published.
2. Login through the web proxy: 200.
3. `/offers` HTML lists `school_admin_starter` as draft. `/offers/{id}` shows 4 "Unverified" labels, "pricing unavailable" and "no published, sellable revision".
4. Publishing the seeded draft through the proxy gives **400** "a revision needs at least one claim approved for sales" (identical when sent directly to the API).
5. New revision through the proxy: 201 (`revision 2`). Publish: 200 `published`.
6. Sales-ready: revision 2, claims `['fee_tracking']` (the unverified admissions claim stays hidden), `pricing_unavailable`. The page shows "yes, revision".
7. CSRF-less archive: 403. Archive with CSRF: 200 `archived`. Sales-ready then gives 409.
8. Log scan: password 0, CSRF token 0. Events: `offer.publication_refused` ×2, `offer.revision_created`, `offer.published`, `offer.archived`.

**Process note:** my first flow script built JSON inside nested `$(…)` quoting, which sent malformed bodies (422) and duplicated output lines. A focused reproduction showed the API and proxy behave correctly, and the flow was rerun with file-based bodies (results above).

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| Readiness gate removed from `assert_publishable` | 3 failures: `…blocks_publication[planned/unverified/not_supported]` |
| `expected_version` comparison removed | `test_stale_writers_get_409`. The concurrent-publisher test still passed: the row lock plus the "only the current draft can be published" check also stop the second publisher, which is defence in depth |

### Security, privacy and claims review

- No offer can sell without an owner publishing evidence-backed claims, and the draft matrix is never exposed through sales-ready.
- Prices are never invented: absence gives `pricing_unavailable`.
- Revisions are immutable at the database level.
- Organization isolation is enforced by composite FKs and service scoping (404).
- Publish and archive are owner-only with CSRF.
- Logs contain only event names.
- **Residual risks:**
  - The commitment guard is pattern-based. Novel phrasings could slip through, so owner review at publish time remains the control.
  - The JSON textarea UI is minimal (no field-level editor).
  - No browser E2E (P7.5).

### Changed files

| File | Reason |
|---|---|
| `apps/api/alembic/versions/0004_offers.py` | Tables, cyclic FKs, immutability trigger, additive `users` constraint |
| `apps/api/app/offers/{models,schemas,service,routes,seed}.py` | Catalog domain, API and seed |
| `apps/api/app/api/dependencies.py` | `AppClock` |
| `apps/api/app/auth/models.py` | `UNIQUE(organization_id, id)` on `users` |
| `apps/api/app/main.py`, `app/persistence/registry.py` | Wiring |
| `apps/api/tests/integration/test_offers.py` (39 tests), `test_migrations.py` (HEAD `0004`) | Tests |
| `apps/web/{lib/api.ts,lib/mutate.ts,lib/offers.ts,app/page.tsx,app/offers/page.tsx,app/offers/[id]/page.tsx,app/offers/[id]/offer-actions.tsx}` | Offers UI |
| `docs/contracts/offer-catalog.md`, `README.md`, `docs/runbooks/local-development.md` | Documentation |

### Rollback

- **Disposable DB:** `alembic downgrade 0003` (exercised by `test_downgrade_to_base_and_back`).
- **Data-bearing DB:** back up and prefer a forward repair. Never erase approved revisions.
- **Code:** `git revert a07435c`.

### VERDICT: VERIFIED

Batch 02 is complete. P1.4 is next (Batch 03).

## P1.4 — Account management API and evidence-first admin UI (2026-10-24)

**Scope:** Batch 03 §P1.4 and `OPUS_P1.4_PROMPT.md`. **Base:** `c44df58`. **Head:** `af22b2c` (UI and e2e), plus the race test, docs and ledger commit.

### Preflight

| Prerequisite | Status |
|---|---|
| P0.1, P0.2, P0.4, P1.1, P1.2, P1.3 | VERIFIED (ledger evidence above) |
| P0.3 | Partial: the remote-CI gap is carried forward under the owner's continuous-execution instruction |

Reused: the P1.2 `accounts`, `source_records` and `account_facts` models and services (rights, claims, URL screening), `authorize_request`/`allow_roles`, `AppClock`, the P1.3 UI conventions and `lib/mutate.ts`.

### Conflicts and decisions

1. **Error field name.** Batch 03 §0.3 names the error field `trace_id`; the accepted P0.4 envelope uses `request_id`. Kept `request_id`, because Batch 02 says the actual P0.4 contract wins.
2. **Source-rights refusals are now 403**, as the Batch 03 table specifies; P1.2 returned 400. A new `policy.RightsViolation` covers provider allowlist, storage class, payload, required key and excerpt rights. Malformed or unsafe URLs, expired sources and claim values stay 400; malformed bodies 422. The P1.2 tests were updated to expect `Forbidden` for rights cases.
3. **One migration, `0005`, was genuinely needed for corrections:**
   - `account_facts` gains `supersedes_fact_id` (an organization-scoped self-FK), `correction_reason` (3–1000 characters, required exactly when superseding), `recorded_by` (a scoped user FK) and `UNIQUE(organization_id, id)`.
   - The partial unique index `uq_account_facts_org_supersedes` allows one successor per fact.
   - Facts and the new `action_audits` table are append-only (trigger).
   - Keyset index `(org, updated_at, id)` and a `text_pattern_ops` name-prefix index.
4. **Corrections are pure append.** The prior fact is never modified; "superseded" is derived from the successor link, and the projection exposes `is_current`.
5. **Service composition:** P1.2 services gained `commit=False` (flush only), so the new source, the fact and the audit row commit as one transaction.
6. **City is restricted to Lahore** (the first market) via a `Literal`; widening it is a deliberate change. Archiving uses the existing `excluded` status and is owner-only (`ADMINISTER`). P1.4 has no un-archive.
7. **Cursor:** base64url `{updated_at, id, filter digest}`, where the digest covers the organization and filters. It is validated but **unsigned**, which is documented as safe because the query is always organization-scoped and the token only encodes a position.
8. **UI:** `/accounts`, `/accounts/new` (server-guarded) and `/accounts/[id]`, with forms built from labelled native controls, live status regions and minimal global CSS for wrapping. Playwright e2e was added now (desktop and mobile Chromium) because the batch asks for UI evidence. `scripts/test-e2e.sh` runs it on a disposable full stack and is part of `check.sh`; CI installs Chromium's system dependencies.

### Acceptance evidence

| ID | Executed test / command | Result summary | Status |
|---|---|---|---|
| ACCOUNT-01 | API `test_operator_creates_account_and_list_and_detail_agree`, `test_two_schools_with_the_same_name_stay_separate`. E2E `ACCOUNT-01` (desktop) | 201 with UUID, `ETag "1"`, Lahore, discovered. List and detail agree; audit `account.created` by the operator. Same-name schools are 2 accounts. UI: created, reloaded, found via search | PASS |
| ACCOUNT-02 | API `test_source_supported_fact_with_new_source_persists_after_restart` (second app instance). E2E `ACCOUNT-02` and `@after-restart` (`docker compose restart api web`) | Fact and source are created atomically. The detail shows provider, URL, `full_allowed`, rights version, observed time, not stale, `recorded_by`. The UI card shows "Source-supported", the URL, rights, "(Asia/Karachi)" and the excerpt. Still present after the API and web restart | PASS |
| ACCOUNT-03 | API `test_unknown_erp_is_a_visible_hypothesis_not_absence`. E2E `ACCOUNT-03` | Stored as hypothesis/unknown with no source; `{"status":"none"}` and "supported absence" are refused (400). The UI shows it under "Hypotheses and unknowns (not verified)" with "No source"; no "no software" text exists anywhere | PASS |
| ACCOUNT-04 | API `test_correction_keeps_history_links_successor_and_is_unambiguous`, `test_correction_requires_reason_and_same_claim_type`. E2E `ACCOUNT-04` | The prior fact keeps `{"count":2}` with `superseded_by` set; the successor `{"count":3}` has `supersedes`, the reason and the recorder; exactly one current campus count. Raw SQL UPDATE or DELETE on the fact and an UPDATE on the audit fail ("append-only"). Audit: created, fact_added, fact_corrected. No reason, a short reason or a different claim type give 422. The UI history shows "Superseded: campus_count: count: 2" and one current fact | PASS |
| ACCOUNT-05 | `test_concurrent_patches_one_winner_and_stale_patch_preserves_state` (owner vs operator threads), `test_double_correction_has_exactly_one_successor`, `test_if_match_header_is_an_alternative_to_expected_version`, **`test_cas_rejects_a_write_that_lands_between_read_and_update`** (a deterministic race injected between the service read and the UPDATE) | Concurrent writes give `[200, 409]` with the winner's name, version 2 and one `account.updated`. A stale PATCH gives 409 with state intact. Double correction gives `[201, 409]` with one successor and one current fact. If-Match works, and a body/header disagreement gives 400. The injected race gives 409, keeping the racer's name and leaving our locality unapplied | PASS |
| ACCOUNT-06 | `test_role_matrix_and_csrf_with_no_persisted_writes`. E2E `ACCOUNT-06` | Observer create, patch, fact and archive all give 403; operator archive 403; a fact without CSRF 403; anonymous read and write 401. Counts stay (1, 0, 0). Owner archive gives 200 `excluded`, and a re-archive 409. UI: the observer has no buttons or forms, and `/accounts/new` redirects to `/accounts` | PASS |
| ACCOUNT-07 | `test_cross_org_accounts_facts_and_sources_are_invisible` | The intruder's list shows only its own account. GET, PATCH, add-fact, a correction of my fact via their account, using my `source_id`, and archive all return **404** without leaking the name. My account stays version 1, with 0 facts in their organization. The DB composite FKs are covered by P1.2 tests | PASS |
| ACCOUNT-08 | `test_invalid_listing_parameters_are_typed_errors` (8 cases), `test_bad_transitions_and_forbidden_or_stale_sources_write_nothing`, `test_failed_inline_source_rolls_back_with_the_fact`, `test_cursor_from_another_organization_is_rejected`, `test_keyset_pagination_is_complete_stable_and_filter_bound` | Typed `VALIDATION_ERROR` with `request_id` matching the header (422 or 400). discovered→shortlisted and PATCH to excluded give 422. Places full-content gives **403**; a metadata-IP URL 400; an expired source 400 "expired". Afterwards status and version are unchanged, the fact shows stale and counts are unchanged. A failed inline source rolls back the fact too, leaving only `account.created` audited. 7 accounts in 3 pages, complete and ordered; a changed filter or a foreign-organization cursor gives 400 | PASS |
| ACCOUNT-09 | API `test_markup_long_and_unicode_names_are_bounded_and_returned_as_data`. E2E `ACCOUNT-09` markup on **desktop and mobile (Pixel 7)**; E2E keyboard-only create | The API returns markup as JSON data; 251 characters gives 422; RLO gives 400; an Urdu name is kept; a 1001-character excerpt gives 422. In the browser, `<img onerror>` and `<script>` names render as text: `window.__pwned` undefined, 0 `img` in main, 0 dialogs, no horizontal overflow on mobile. Tab and Enter create an account | PASS |
| ACCOUNT-10 | API `test_everything_survives_a_restart` (new app instance). E2E `@after-restart` after `docker compose restart api web`. Dev stack: `alembic upgrade head` (`0004 -> 0005`) then smoke. `bash scripts/check.sh` | Status, version, two facts with one current and 4 audits persist. The UI after the real container restart shows the correction and hypothesis. **check.sh 16/16 PASS**: unit + contract 122; integration 171 (P1.1–P1.3 suites included); web Vitest 2; e2e 9 passed plus 1 after restart | PASS |

### Negative paths

- **Postgres loss mid-request:** `test_database_outage_is_a_safe_503` gives 503 without the secret.
- **Duplicate names across localities:** see ACCOUNT-01.
- **Changing filters while paginating:** gives 400.
- **SSRF-shaped source URLs:** refused, and nothing is ever fetched.
- **Expired facts:** shown as stale.
- **Archiving with active materialized data:** there is none yet.
- **UI cache showing a stale version:** a PATCH with the old version gives 409, and the UI shows the error message.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| `list_accounts` drops `organization_id` scoping | `test_cross_org_accounts_facts_and_sources_are_invisible` |
| `_cas_update` drops `version = expected` | **Initially not caught.** The service's pre-read version check masked it, and the HTTP concurrency test did not interleave inside the read→update window. Added `test_cas_rejects_a_write_that_lands_between_read_and_update`, which passes on the real code and **fails on the mutant** |

### Process notes

- The first e2e run failed on a test-locator ambiguity: "Evidence excerpt (needs full storage rights)" contains "Storage rights". Fixed with exact label matching.
- The second e2e run reloaded before the correction POST finished; the spec now awaits the 201.
- An integration test advanced the fixed clock beyond the 24h session lifetime, giving a correct 401; it now uses a 2h source TTL and a 3h advance.
- The first version of the CAS race test re-raced on the 404/409 disambiguation read; it now races once.

### Security, privacy and data rights

- Every query is organization-scoped from the session; cross-organization access looks like 404.
- CSRF and roles apply on all writes, and observers are read-only.
- Rights refusals return 403, and sources are registered as provenance only (no fetch).
- History is append-only (DB triggers) with audited actor, time and reason.
- Logs carry event names and IDs only.
- Synthetic `.example` data only; e2e users are created by the bootstrap function with a random per-run password.
- **Residual risks:**
  - The cursor is unsigned (documented as safe).
  - Name search is prefix-only, by design.
  - The UI fact value is entered as JSON text, an operator tool that is not polished.

### Changed files

| File | Reason |
|---|---|
| `apps/api/alembic/versions/0005_account_management.py` | Corrections, audits, indexes, append-only triggers |
| `apps/api/app/accounts/{models,policy,service,management,routes}.py` | Domain, service and API |
| `apps/api/app/core/{errors,logging}.py` | `Unprocessable` (422); `account_id`/`fact_id` log keys |
| `apps/api/app/main.py` | Router |
| `apps/api/tests/integration/{test_account_management,test_accounts,test_migrations}.py` | Tests (20 new API tests; rights expectations; HEAD `0005`) |
| `apps/web/{app/accounts/**,lib/accounts.ts,lib/mutate.ts,app/page.tsx,app/layout.tsx,app/globals.css}` | UI |
| `apps/web/{playwright.config.ts,e2e/*,package.json,package-lock.json,.gitignore}` | E2E (`@playwright/test` 1.64.1) |
| `scripts/{test-e2e.sh,check.sh}`, `.github/workflows/ci.yml` | E2E harness; CI Chromium dependencies |
| `docs/contracts/account-management.md`, `README.md`, `docs/runbooks/testing.md` | Documentation |

### Rollback

- **Disposable DB:** `alembic downgrade 0004` (covered by the migration down/up tests).
- **Data-bearing DB:** back up and prefer a forward repair. Corrections and audits are history.
- **Code:** revert `2478996` and `af22b2c`, plus the follow-up commit. Reverting must not drop history.
- **Never** `down -v`.

### VERDICT: VERIFIED

P1.5 is next.
