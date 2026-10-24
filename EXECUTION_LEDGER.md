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
| P1.5 | Durable Postgres jobs, transactional outbox, fenced runner (Batch 03) | verified |
| P2.1 | Offline rights-aware SourceAdapter framework + synthetic fixture (Batch 03) | verified |
| P2.2 to P12.4 | See blueprint §4 and `docs/phases/` | not-started |

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

## P1.5 — Durable jobs, transactional outbox and safe worker execution (2026-10-24)

**Scope:** Batch 03 §P1.5 and `OPUS_P1.5_PROMPT.md`. **Base:** `bcb4639`. **Head:** `dd614b7` (core), `d2d0bf4` (fixes and docs), plus this ledger commit.

### Preflight

P0.1, P0.2, P0.4 and P1.1–P1.4 are VERIFIED; the P0.3 remote-CI gap is carried forward. Before this subphase: an RQ worker (ADR-009) with Redis as the queue, but **no RQ job had ever been enqueued**; Alembic head `0005`; the P1.4 `action_audits` table; P0.4 logs and correlation.

### Design decisions (ADR-011)

1. **PostgreSQL is the only queue authority.** RQ needs Redis as queue truth, so, as the batch instructs, the worker process now runs a small bounded Postgres runner. RQ stays installed but dormant (no second queue). Redis carries only wake-up notifications from the outbox publisher. ADR-009's runtime role is marked superseded.
2. **Migration `0006`:**
   - `jobs`: idempotency key per (org, type, key), canonical payload digest, attempts ≤ `max_attempts` (1–10), DB-clock lease plus **fencing token**, sanitized `last_error_class`, CHECKs for lease and finish invariants, and a partial claimable index.
   - `outbox_events`: `dispatched_at` + `dispatch_sink` mean *notification delivered*; lease and backoff columns.
   - `account_audit_snapshots`: the DB-only effect, with `UNIQUE(org, job_id)`.
3. **Transaction boundary.** `enqueue_job` and `record_outbox_event` never commit; the producer (`request_account_snapshot`, HTTP `POST /accounts/{id}/snapshots` with `Idempotency-Key`) commits the domain audit, the job and the event together.
4. **Execution.** The handler effect and the fenced completion are one transaction. Stale owners match 0 rows and roll back. Errors use an explicit taxonomy, with capped jittered exponential backoff. Expired leases are reclaimed, or dead-lettered once their attempts are exhausted.
5. **Health.** Worker health is now runner heartbeat + Postgres reachable, independent of Redis. Before migrations the runner waits without heartbeating (unhealthy, no crash loop).
6. **Registry:** `diagnostic.noop` (dev/test) and `account.audit_snapshot`. Payloads are Pydantic, ≤ 16 KiB, with no credential fields and nothing the log scrubber would redact.
7. **Honest limit:** execution is at-least-once, and exactly-once holds only for **local DB effects**. **No external side-effect handlers exist; nothing claims exactly-once messaging.**

### Acceptance evidence

| ID | Executed test / command | Persisted outcome observed | Status |
|---|---|---|---|
| JOB-01 | `test_domain_change_job_and_outbox_commit_together` | Audit `account.snapshot_requested`, job `pending` and outbox `job.enqueued` committed; same organization; `jobs.correlation_id` = audit `request_id` = bound request ID; event keyed by job ID; not dispatched | PASS |
| JOB-02 | `test_exception_before_commit_leaves_no_job_event_or_audit` | After the injected exception: 0 jobs, 0 events, no snapshot audit | PASS |
| JOB-03 | `test_committed_job_without_notification_is_found_by_polling`; **real containers**: `docker compose stop worker`, producer commits and exits (no notify), `start worker` | Test: succeeded, 1 attempt, 1 snapshot; second `run_once` gives `[]`; event dispatched to `none`. Real: `pending` while the worker was down, then `succeeded` after restart, snapshots 1, attempts 1 | PASS |
| JOB-04 | `test_redis_down_does_not_strand_work_and_notification_retries_later`; **real containers**: `docker compose stop redis` with the worker running | Test: the job succeeded while the event stayed undispatched (`sink_unavailable`); with Redis back it was dispatched (`redis`), the wake list holds the event UUID only, and there was no re-run. Real: the job succeeded with 1 snapshot, the **worker stayed healthy** for 25s+ of outage, the event was undispatched during the outage and dispatched `redis` after Redis returned, and the job was untouched | PASS |
| JOB-05 | `test_racing_workers_claim_each_job_exactly_once` (3 workers × 10 jobs) | Each job claimed once (attempts 1), 10 snapshots, outcome IDs equal the enqueued IDs | PASS |
| JOB-06 | `test_idempotent_enqueue_and_payload_mismatch`, `test_concurrent_identical_enqueues_create_one_job` (4 threads), `test_http_idempotency_key_contract` | An exact replay gives the same receipt (`created=False`) and one snapshot-requested audit. A different account with the same key gives 409; v2 is "not registered". Concurrency gives 1 job and 1 event. HTTP: 202, 202 with the same `job_id`; clash 409; missing or bad key 422; the job view has no payload | PASS |
| JOB-07 | `test_crash_inside_the_effect_transaction_leaves_no_effect_and_reclaim_succeeds`, `test_committed_effect_without_ack_is_not_duplicated_and_stale_owner_is_fenced`, `test_expired_lease_on_last_attempt_goes_dead_not_silently_lost`; **real**: SIGKILL of the worker process | (a) An uncommitted effect leaves 0 snapshots; the lease is held until expiry; the rescuer succeeds with attempts 2 and 1 snapshot. (b) A committed effect without ack: the new owner succeeds and the stale `complete_job` raises `LeaseLost`, the stale `fail_job` returns `None`, and the final status and digest are the winner's, with **1 snapshot** (absorbed by the unique key). (c) Exhausted attempts give `dead`/`lease_expired`. Real: RestartCount 0→1 and the queued job succeeded | PASS |
| JOB-08 | `test_transient_failures_back_off_then_succeed`, `test_permanent_failure_is_dead_immediately`, `test_retries_are_bounded_and_errors_are_sanitized`, `test_notification_backoff_grows_per_failed_delivery` | Delays within ±20% of 2s then 4s; no claim before due; succeeded on attempt 3. Permanent gives dead after 1 attempt (`bad_input`), never retried. An unknown error with a secret message gives retry_wait ×2 then `dead`/`retries_exhausted`; logs contain neither `job-secret-value` nor `hunter2`. Notification backoff 2/4/8/16s (±20%) | PASS |
| JOB-09 | `test_racing_publishers_deliver_each_event_once` (2 publishers × 8 events), `test_failed_notification_is_retried_after_backoff_never_lost`, `test_publisher_crash_after_claim_is_recovered_after_lease_timeout` | Each event notified exactly once and all dispatched, **while jobs are still `pending`** (notify ≠ process). A failure is retried after backoff, not before; attempts 2. A crashed publisher's lease blocks others until it expires, then the event is delivered once | PASS |
| JOB-10 | `test_malicious_or_unsupported_payloads_fail_closed` (11 cases), `test_cross_org_enqueue_read_and_injected_job_fail_closed`, `test_ops_diagnostics_are_owner_only_scoped_and_payload_free`; **`bash scripts/check.sh`** | Refused: shell name, function path, unknown version, 20 kB payload, `password=`, phone, email, `token` key, extra field, noop in production, bad UUID; 0 jobs and 0 events each time. A cross-org enqueue gives 404; a cross-org job read gives 404; an injected job pointing at another org's account goes dead (`account_not_found`) with no foreign snapshot. Ops view: operator 403; owner sees counts and dead classes, no payloads or account IDs. **check.sh 16/16 PASS**: integration 204 tests (P1.1–P1.4 suites included), unit + contract 122, web 2, e2e 9 + 1 after restart | PASS |

### Fault injection on real containers (throwaway project `hermecious-p15`, removed with `down -v`)

Results are under JOB-03, JOB-04 and JOB-07 above. Totals: 3 jobs succeeded, 3 snapshots, **0 duplicate snapshots**. Worker logs: 4 `jobs.metrics` lines and 3 `job.succeeded`, with 0 occurrences of the account ID (no payloads).

### Defects found and fixed during verification

1. **Outbox notification retried every ~2s during a Redis outage** (10 attempts in 25s), because the backoff always used attempt 1. It now grows per failed delivery. Regression test added.
2. **The worker crash-looped before migrations**, from an unhandled `ProgrammingError`. It now waits without heartbeating (unhealthy). Tested against a real unmigrated scratch DB. The e2e harness and README now migrate before the worker starts. **The README clean room was re-verified** at `d2d0bf4`: fresh SSH clone, README steps, 6 migrations, smoke all PASS.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| `complete_job` ignores the fencing token | `test_committed_effect_without_ack_is_not_duplicated_and_stale_owner_is_fenced` |
| Claim without `SKIP LOCKED` | `test_racing_workers_claim_each_job_exactly_once` |

### P0.2 regression with changed semantics

`scripts/recovery-local.sh` was updated per ADR-011:
- **Postgres outage:** the worker reported unhealthy after 28s and was healthy again after the restart.
- **Redis outage:** the worker **stayed healthy** for 40s+ with 0 restarts.
- **A5 persistence:** PASS.

`smoke-local.sh` PASS. Dev DB migrated `0005 -> 0006`.

### Security and privacy

- Typed allowlist only, with no dynamic code paths.
- Payload size, credential and contact checks.
- Errors are stored as classes only; logs are scrubbed.
- Organization-scoped receipts; owner-only diagnostics with no payloads.
- **No external sends, fetches or agent orchestration.**
- Redis receives event UUIDs only.

### Changed files

| File | Reason |
|---|---|
| `apps/api/alembic/versions/0006_jobs_outbox.py` | Tables, constraints, indexes |
| `apps/api/app/jobs/{models,registry,service,runner,routes}.py` | Jobs and outbox |
| `apps/api/app/accounts/{models,snapshots,routes}.py` | Snapshot effect, producer, endpoint |
| `apps/api/app/workers/worker.py` | The runner replaces the RQ loop; new health check |
| `apps/api/app/core/{settings,logging}.py` | `HERMECIOUS_JOB_NOTIFY`; metric log keys |
| `apps/api/app/main.py`, `app/persistence/registry.py` | Wiring |
| `apps/api/tests/integration/test_jobs.py` (31 tests), `test_dependencies.py`, `test_migrations.py`; `tests/unit/test_worker_health.py`, `test_entrypoints.py` | Tests |
| `compose.yaml`, `.env.example` | The worker depends on Postgres, not Redis; notify setting |
| `scripts/{recovery-local,test-e2e}.sh` | New health semantics; migrate before the worker |
| `docs/adr/ADR-011-postgres-jobs-and-outbox.md`, `ADR-009` (superseded note), `docs/contracts/job-outbox.md`, `docs/runbooks/{jobs,local-development}.md`, `README.md` | Documentation |

### Rollback

- **Code:** revert the worker image. Rows stay, and unknown types or versions fail closed (dead `invalid_payload`), so nothing runs with the wrong schema.
- **Disposable DB:** `alembic downgrade 0005` (migration tests).
- **Data-bearing DB:** drain or export pending and dead jobs first. Never delete pending work, and never `down -v`.

### VERDICT: VERIFIED

P2.1 is next.

## P2.1 — Rights-aware discovery SourceAdapter framework, offline fixture (2026-10-24)

**Scope:** Batch 03 §P2.1 and `OPUS_P2.1_PROMPT.md`. **Base:** `a4bc47e`. **Head:** `7238eff` (code), plus the docs and ledger commit. **No migration** (head stays `0006`).

### Preflight

P0.1, P0.2, P0.4 and P1.1–P1.5 are VERIFIED; the P0.3 remote-CI gap is carried forward.

Reused:
- The P1.2 rights policy: `PROVIDERS`, `screen_url` and `add_source_record(commit=False)`.
- The P1.4 `_audit`, now with a target type parameter.
- The integration harness.

There was no existing discovery code.

### Design decisions

1. **`fetch(source_key)`, never `fetch(url)`** (ADR-012). Adapters are synchronous, return raw mappings, and the framework validates every record individually.
2. **Fail-closed descriptor registry.** Exactly one provider, `fixture_lahore_schools`, is enabled, in development and test only. Non-fixture kinds are refused (`live_sources_not_enabled`), and so are missing terms, rights or review, credentials, unlicensed operations and unsupported queries, all **before** the adapter is invoked.
3. **Downward-only budgets** (30, 5, 20, 60s, cost 50, 2 retries); exceeding a ceiling raises `ValueError`. Retries consume budget.
4. **Rights-filtered retention:**
   - metadata only: identity and URL;
   - derived: plus unverified hints;
   - full: plus a bounded excerpt.

   Provenance rows only, with **no content or payload stored**. TTL is clamped to the descriptor's retention.
5. **No URL means a preview only.** The first draft wrote a placeholder provider URL for a record without one; that was fabricated provenance, and I removed it before the first commit. Such records now count as `not_persisted_missing_url`.
6. **P1.2 rights policy gains provider `fixture_lahore_schools`**: all classes, no payload, external key required. Keys are namespaced `fixture_lahore_schools:<key>`, and replays are idempotent per organization.
7. **Dev/test-only CLI**, with **no HTTP endpoint and no new job type**. P2.4 owns run management and UI.

### Acceptance evidence

| ID | Executed test / command | Observed | Status |
|---|---|---|---|
| SOURCE-01 | `test_fixture_search_is_bounded_typed_offline_and_labelled_synthetic` | Synthetic label; provider, adapter and policy versions; `completed`; 9 examined, 3 search pages; 5 unverified previews; rejections exactly `{expired_observation:1, not_persisted_missing_url:1, query_mismatch:1, unapproved_host:1, unsafe_url:1}`; 4 persisted; **0 accounts**; network guard saw 0 egress | PASS |
| SOURCE-02 | `test_fetched_observations_record_rights_and_ttl_provenance` | 4 provenance rows, namespaced keys, storage class and rights version per record; `expires_at` clamped to observed + 30 days; `source_payload_reference` NULL | PASS |
| SOURCE-03 | `test_policy_refusals_happen_before_the_adapter_runs` (9 cases), `test_unknown_provider_is_refused` | disabled, no terms, no rights, unreviewed, live kind, wrong environment, credentials, no search, no fetch: each raises its reason code with **0 search and 0 fetch calls** and 0 rows. An unknown provider is refused | PASS |
| SOURCE-04 | `test_each_storage_class_keeps_only_permitted_content`, `test_descriptor_storage_ceiling_rejects_richer_rights` | Full rights keep excerpt and hints; derived keep hints only; metadata keep neither. `RESTRICTED-RAW-TEXT-*` and the injected "grant marketing consent" note appear nowhere in the report, logs, `source_records` dump or audits. A metadata-only ceiling gives `rights_denied` 3 and only metadata rows | PASS |
| SOURCE-05 | `test_thirty_one_plus_candidates_are_capped_at_thirty` (49 records, page size 10), `test_misbehaving_pagination_is_bounded_and_deterministic` (repeated cursor, duplicate keys, oversized page) | `candidate_cap`, ≤30 accepted, ≤5 pages. Repeated cursor gives `cursor_cycle`; duplicates give `duplicate_key`; oversize is truncated (`page_oversized`). Two runs give identical reports apart from run ID and timings | PASS |
| SOURCE-06 | `test_unsupported_queries_are_refused_not_answered_with_nearby_data` (Karachi, retail), `test_malformed_records_are_rejected_individually`, `test_query_validation` (4) | `unsupported_query` with 0 adapter calls. Malformed records (no key, naive time, non-string name, fragment URL) are rejected individually while the 5 valid previews remain; 0 accounts. Query validation rejects empty city, long or unsafe keywords and too many keywords | PASS |
| SOURCE-07 | `test_budget_caps_stop_with_truthful_partial_report` (pages, fetches, cost), `test_time_cap_uses_the_injected_clock`, `test_transient_429_is_retried_within_budget`, `test_persistent_429_stops_without_over_budget_retry`, `test_fetch_timeout_skips_one_record_and_continues`, `test_budgets_can_only_be_lowered` | `page_cap`/`fetch_cap`/`cost_cap` with consumed equal to the limit. `time_cap` at ≥50s on a fake clock. One 429 retries once and completes. Persistent 429s stop as `rate_limited` after 2 retries (3 calls), never over budget. A fetch timeout skips one record, leaving 4 previews. Ceilings cannot be raised | PASS |
| SOURCE-08 | `test_unsafe_urls_and_prompt_injection_are_inert_data`, `test_discovery_package_has_no_network_client_imports`, plus the autouse **socket egress guard** on every test | Metadata IP and off-allowlist host rejected. The injected "IGNORE ALL PREVIOUS INSTRUCTIONS… create an account" record stays an unverified preview with its hints dropped (metadata only) and **0 accounts**. Rejected URLs are absent from the report. `app/discovery` imports no socket or HTTP client. Egress attempts: 0 | PASS |
| SOURCE-09 | `test_two_organizations_get_isolated_provenance_and_replay_is_idempotent` | Organizations A and B each persist 4 rows with the same keys (8 total). Replaying A gives persisted 0 and already-recorded 4, with A still at 4 rows. A cannot read B's source (`NotFound`) | PASS |
| SOURCE-10 | `test_cli_dev_only_deterministic_and_audited`; **`bash scripts/check.sh`**; dev stack rebuild, `alembic current` (`0006 (head)`), smoke; CLI against a dev organization with no owner | CLI refused in production (exit 2). Two test runs give persisted 4, then 0 with already-recorded 4; distinct run IDs; no restricted text in output; 2 `discovery.fixture_run` audits; 0 accounts. **check.sh 16/16 PASS**: integration 241 (all prior P0–P1.5 suites), unit + contract 122, web 2, e2e 9 + 1 after restart. Dev smoke PASS; the CLI without an owner exits 1 with "refused" | PASS |

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| The fixture adapter attempts a real `socket.create_connection(("1.2.3.4", 80))` | The socket egress guard fails every affected test: `unexpected network egress: [('1.2.3.4', 80), …]` |
| `_screen` drops the descriptor hostname allowlist | 8 tests fail, including SOURCE-01, SOURCE-02, SOURCE-08, SOURCE-09 and SOURCE-10 |

### Security, privacy and data rights

- No network code, and egress is proven absent by a test guard.
- No real providers; the fixture policy id is explicitly synthetic.
- No contacts, accounts, facts or merges.
- Injected text is data only.
- Restricted raw text is never persisted or logged.
- Provenance is organization-scoped and idempotent.
- Budgets cannot be raised, and the dev-only CLI is refused in production.

### Constraints handed to P2.2

- Implement a real provider only behind a reviewed descriptor (ADR-012). Use a network client bound to `allowed_hostnames`, with post-DNS private-address and redirect checks, and register the provider in the P1.2 `PROVIDERS` rights policy.
- Never Google Maps scraping, and never `fetch(url)`.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/discovery/{contracts,registry,fixture,runner,cli}.py`, `fixtures/lahore_schools_v1.json` | Framework, fixture and runner |
| `apps/api/app/accounts/{policy,management}.py` | Fixture provider rights entry; audit `target_type` parameter |
| `apps/api/tests/integration/test_discovery.py` (37 tests) | SOURCE-01 to SOURCE-10 |
| `docs/adr/ADR-012-source-adapter-fetch-by-key.md`, `docs/contracts/source-adapters.md`, `README.md` | Documentation |

### Rollback

Disable the fixture with `enabled=False` in its descriptor (fail closed), or revert `7238eff`. There is no schema change. Provenance rows already stored are kept; they are synthetic, organization-scoped and labelled by provider.

### VERDICT: VERIFIED

Batch 03 is complete. P2.2 is next (Batch 04).

## P2.2 — First real, rights-aware Lahore school discovery input (2026-10-24)

**Scope:** Batch 04 §P2.2 and `OPUS_P2.2_PROMPT.md`. **Base:** `5d8480f`. **Head:** `18834d9` (code), plus the docs and ledger commit. **Migration:** `0007_discovery_staging` (`source_imports`, `discovery_candidates`); the dev database is upgraded to `0007 (head)`.

### Preflight

- **Prerequisites:** P2.1 is VERIFIED (SOURCE-01…10), and P0/P1 ledger proof exists. The P0.3 remote-CI observation gap is carried forward.
- **Baseline at `5d8480f`:** check.sh 16/16 PASS, with 241 integration tests and 122 unit + contract tests.
- **Reused:**
  - P2.1 DTOs, descriptor registry, runner and budgets (extended backward-compatibly, ADR-013 §5);
  - P1.2 `PROVIDERS`, `screen_url`, `clean_text` and `add_source_record`;
  - P1.4 `_audit`.
- **No equivalent staging table existed**, so `discovery_candidates` was added as Batch 04 specifies.
- **This prompt was not treated as permission to make network requests.**

### Design decisions (ADR-013)

1. **`osm_overpass_schools`** (`api`, `osm-odbl-2026-10`, metadata only, 30-day TTL, quota 3, ≤30 results).
   - **Off by default.** It is enabled only when the owner sets the enabled flag, reviewer, timezone-aware review time, bounding box (≤0.6° per side, Pakistan sanity envelope) and box citation.
   - **Validation:** settings validation names any incomplete activation; a review older than 365 days gives `rights_review_expired`.
   - **Endpoint:** from a code allowlist only.
2. **One fixed Overpass QL template** with validated numbers. It requests 31 to detect truncation, and never sweeps a grid or uses a cursor.
   - **Elements:** node/way/relation with a positive integer id; key `{type}/{id}`; the provenance URL is built from the key.
   - **Tags kept:** `name`, `name:ur`, `addr:suburb` only.
   - **Location:** `center` is labelled `area_center`. Elements outside the box or without geometry are rejected.
   - **Never synthesized:** a missing name. **Never kept:** contributor metadata.
   - **`fetch`:** served from the same search capture, with no second request.
3. **`PinnedHttpsClient`** is the only network module.
   - Exact host and path; HTTPS on 443; every DNS answer must be global; the TCP connection is pinned to the vetted IP, with TLS SNI verification.
   - No redirects, proxies, cookies or credentials; 25 s timeout; 1 MB cap.
   - 429/503 become typed transients; Retry-After is accepted only as numeric seconds ≤300.
4. **Runner:**
   - policy is re-checked before every adapter call (`policy_revoked`);
   - waits are `max(Retry-After, 5 s × 2^n)` and must fit the time budget;
   - new stops: `response_too_large`, `upstream_error`, `unavailable`;
   - new report fields: `truncated`, `partial`, `completeness_note`, attribution and staged counts;
   - refusals leave a `discovery.source_denied` log line and a `discovery.run_refused` audit;
   - names are screened for control and bidi characters (`unsafe_text`).
5. **Staging:** idempotent on `(org, provider, external_key)`.
   - An identical replay is a no-op.
   - A change bumps `revision` and writes a `discovery.candidate_revised` audit with both digests.
   - Concurrency is handled with `ON CONFLICT` and a row lock.
   - **No accounts, facts or contacts are created.**
6. **CSV fallback `operator_seed_csv`** (owner only, CSRF): see ADR-013 §7 for the full rules.
   - **Required inputs:** a source label and a permission declaration.
   - **File:** UTF-8 with an optional BOM; ≤256 KB; ≤500 rows; strict header; Lahore only.
   - **Row rejections:** formula-like or control-character cells. Rejected rows are reported by number only.
   - **Idempotency:** on the checksum.
   - **No network use:** nothing is fetched.
7. **Read API** `GET /api/v1/discovery/candidates` (bounded, keyset). Every item says `unverified` and carries origin, attribution, TTL and `expired`. **There is no endpoint that starts a live run.**

### Acceptance evidence

All of LIVE-01…09 are hermetic: Overpass is replaced by a stub, Postgres is real, and every discovery test runs under a socket egress guard that saw 0 attempts.

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| LIVE-01 | `test_live_01_unpermitted_source_is_denied_before_any_request` (8 cases: disabled, unreviewed ×2, review incomplete, expired, wrong environment, fetch not licensed, website kind), `test_live_01_review_expiry_follows_the_clock`, unit `test_osm_is_disabled_by_default…`, `test_enabling_osm_requires_every_reviewed_activation_setting` (6), `test_fully_reviewed_activation_enables_the_descriptor`; dev CLI | Each case raises its reason code with **0 requests** and 0 `source_records`/`discovery_candidates`, plus one `discovery.run_refused` audit `{provider, reason}` and one `discovery.source_denied` log line. Incomplete settings name the variable without echoing values. Dev CLI: without `--confirm-live` it exits 2; unreviewed, it exits 1 with `provider_disabled` | VERIFIED |
| LIVE-02 | `test_live_02_node_way_relation_become_stable_attributed_candidates` | One request carrying exactly the fixed query (`out center 31`). Keys `node/1001`, `way/2002`, `relation/3003`; precision `point`/`area_center`; provenance URLs `https://www.openstreetmap.org/{type}/{id}`. `name:ur` and `addr:suburb` kept; upstream timestamp parsed; ODbL attribution on the report. 3 staged rows, `unreviewed`, revision 1, linked to `source_records`. 0 accounts and 0 facts. 0 remote fetches | VERIFIED |
| LIVE-03 | `test_live_03_malformed_hostile_and_out_of_area_elements_fail_safely` (14 hostile elements), `test_live_03_malformed_payloads_stop_without_persisting` (4 bodies), unit `test_provenance_urls_come_only_from_validated_element_keys` (6), `test_bbox_must_be_explicit_finite_small_and_plausible` (9) | Rejections exactly `{invalid_record:4, missing_key:8, unsafe_text:1}`: bidi, no name, negative/zero/string/bool id, `area` type, Karachi point, no geometry, text latitude, non-dict tags, 300-character name, non-object. The `<script>`/"create an account" name stays inert text, with no locality guessed and 0 accounts. The `website` metadata URL appears nowhere in the DB. Non-JSON, `[]`, wrong shape and invalid UTF-8 stop as `upstream_error` with 0 rows | VERIFIED |
| LIVE-04 | `test_live_04_thirty_one_plus_results_are_capped_at_thirty_and_marked_truncated` (45 elements), `test_live_04_oversized_response_and_runtime_ceiling`, `test_live_04_descriptor_ceiling_limits_requests`, unit `test_query_is_a_fixed_template…`, oversized-body unit test | 45 elements: 30 accepted, `truncated: true`, `candidate_cap`, `partial: false`, 1 request, and the "never an exhaustive list" note. Too-large response: `response_too_large`, partial, 0 rows. 61 s request: `time_cap`, partial, `time_budget_exhausted: 3`, 0 rows. Quota 1: `provider_quota` after 1 request. Limits outside 1–31 refused. A huge box is refused at settings and at `parse_bbox` | VERIFIED |
| LIVE-05 | `test_live_05_retry_after_is_honoured_within_the_budget`, `…backoff_without_retry_after_and_retries_stop_at_budget`, `…retry_after_beyond_the_time_budget_stops_instead_of_waiting`, `…timeout_then_permanent_error`, `…disabling_the_provider_mid_run_halts_storage`, unit `test_rate_limits_become_typed_transients…` (6), `test_timeouts_are_transient` | 429 with Retry-After 7: slept [7.0], 2 requests, completed. 503 ×3: slept [5, 10], 3 requests, `unavailable`, partial, 0 rows. Retry-After 300: no sleep, 1 request, `rate_limited` with `retry_wait_exceeds_time_budget`. A timeout then 400: `upstream_error`, no further retry. Disabled during the request: `policy_revoked`, `{policy_provider_disabled:1, policy_revoked:3}`, 0 rows, and the audit records the stop. An HTTP-date, negative or >300 Retry-After is ignored | VERIFIED |
| LIVE-06 | `test_live_06_only_licensed_fields_persist_with_attribution_and_visible_ttl` | `source_records`: `metadata_only`, `osm-odbl-2026-10`, no payload, URL from the key, expiry = observed + 30 days. A text dump of `source_records`, `discovery_candidates`, `source_imports`, `action_audits` and the report contains none of the injected phone, email, operator or contributor strings. JSON logs contain none of them, nor school names. The API returns `unverified`, `map_listing`, ODbL attribution, `expires_at` and `expired: false` (true after 31 days), with no phone, email, website or operator keys; `no-store` | VERIFIED |
| LIVE-07 | `test_live_07_identical_replay_is_a_no_op_and_changes_are_audited_revisions`, `test_live_07_csv_checksum_replay_creates_nothing_new`, `test_live_07_concurrent_identical_imports_record_once` (2 threads) | OSM replay with a new upstream base: staged unchanged 3, persisted 0, already 3, 3 rows, 0 revision audits. A renamed node gives revision 2 and exactly one `discovery.candidate_revised` audit; still 3 rows. The same CSV twice gives `replayed`, the same import id, 1 import, 2 candidates and 1 audit. Concurrent identical imports: one not replayed and one replayed, with 1 import row | VERIFIED |
| LIVE-08 | `test_live_08_whole_file_rejections_persist_nothing` (6: bad header, extra phone column, 501 rows, >256 KB, NUL, unterminated quote), `test_live_08_non_utf8_and_missing_declaration_are_refused`, `test_live_08_bad_rows_are_rejected_individually_without_echoing_content` | Whole-file problems give 400 `VALIDATION_ERROR` with 0 imports and 0 candidates. Latin-1 is refused, and so is a short declaration. In an 11-row file only `good-1` is staged; reasons are exactly `{duplicate_row:1, formula_like:4, invalid_external_key:1, invalid_text:2, wrong_area:1, wrong_column_count:1}`, rows reported as numbers 2–11. `HYPERLINK`, `evil.example`, `calc`, `@SUM` and the Karachi row are absent from DB, audits and response. BOM and Urdu rows are accepted, with `lahore` normalized to `Lahore` | VERIFIED |
| LIVE-09 | `test_live_09_seed_import_api_is_owner_only_csrf_protected_and_org_scoped`, `…candidate_list_is_bounded_paginated_and_validated`, `…cross_org_replay_stays_isolated`, `…operators_cannot_seed_and_observers_cannot_run`; unit SSRF suite (8 targets, 10 DNS answer sets, 4 redirects, DNS failure, proxy env); `test_discovery_package_has_no_network_client_imports`; **the full P2.1 SOURCE suite unchanged (37 tests)** | Responses: unauthenticated 401; operator 403; no CSRF 403; spoofed `organization_id` or `source_url` field 422; created 201; replay 200; bad header 400. Org B sees 0 of org A's candidates. Pagination 30 + 5 with `limit` 51 → 422 and a bad cursor → 400. Two orgs keep 3 + 3 rows. Service-level operator seed gives `Forbidden`. Egress client: off-allowlist host, path, scheme, port, userinfo, query, fragment or IP gives `target_not_allowed` with 0 connects; loopback, metadata, RFC1918, ULA, CGNAT, `0.0.0.0`, IPv4-mapped loopback or a mixed public+private answer gives `non_public_address` with 0 connects; 3xx gives `redirect_refused`; `HTTPS_PROXY` is ignored (connected to the vetted IP). Network modules in `app/`: only `app/egress/https_client.py`; egress importers in `app/discovery`: only `cli.py` and `osm.py`. SOURCE-01…10 still pass | VERIFIED |
| LIVE-10 | — | **Not run.** It needs the owner's explicit opt-in (rights review recorded in `HERMECIOUS_OSM_*`, a cited box) and outbound access to `overpass-api.de`. **No live request has been made from this repository, and no real-provider evidence exists.** The Overpass QL is checked only against the documented template | **BLOCKED** (owner opt-in) |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `18834d9` | 0 | 16/16 PASS. Integration **277** passed (241 prior + 36 LIVE); unit + contract **179** (122 + 57); web 2; e2e 9 + 1 after restart |
| `./scripts/test-integration.sh tests/integration/test_discovery.py tests/integration/test_discovery_live.py tests/unit` | 0 | 216 passed |
| `./scripts/test-integration.sh … test_migrations.py` (includes upgrade/downgrade and model-drift checks with 0007) | 0 | passed |
| Dev: `docker compose run --rm --no-deps api python -m alembic upgrade head`, then `alembic current` | 0 | `0006 -> 0007`, then `0007 (head)` |
| `bash scripts/smoke-local.sh` after the rebuild | 0 | All smoke checks passed |

### Defects found and fixed during verification

- **`Result.tuples()` deprecation:** it raised under warnings-as-errors in the candidate list; replaced with row unpacking.
- **Two test expectations were wrong, not the code:**
  - The error code is upper-case `VALIDATION_ERROR`.
  - A 31-day clock jump correctly expires the session, so the test now re-logs in.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| `_is_public` always true | 10 unit failures (DNS answer suite) |
| No policy re-check before `fetch` | 1 (`…disabling_the_provider_mid_run…`) |
| Staging ignores the digest (every replay counts as a revision) | 1 (LIVE-07 replay) |
| Formula-prefix check removed | 1 (LIVE-08 bad rows) |
| Bounding-box containment check removed | 1 (LIVE-03) |
| Retry wait skipped | 2 (LIVE-05) |
| Redirect refusal removed | 4 (redirect cases) |
| CSV checksum `ON CONFLICT` removed | 3 (replay, concurrency and API replay) |

### Security, privacy and data rights

- **Egress:** one network client, allowlisted and pinned, with no redirects or proxies, plus bounded time and bytes. Nothing in discovery or the API takes a URL to fetch, and no operator or model can supply one.
- **Data minimisation:**
  - OSM: identity tags only; no contributor, contact, website or operator data.
  - CSV: no contact columns accepted; formula cells refused; rejected content never echoed.
  - Logs carry counts and reason codes only.
- **Rights:**
  - Metadata only with a 30-day TTL. ODbL attribution travels on every candidate and report.
  - The CSV carries the operator's declaration and checksum.
  - **ODbL share-alike must be re-assessed before any external export.**
- **Organization scope:** organization-scoped keys, FKs and queries; `organization_id` from clients is rejected.
- **What staging does not do:** no accounts, facts, contacts, jobs or sends.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/egress/{__init__,https_client}.py` | Pinned HTTPS client |
| `apps/api/app/discovery/{area,osm,staging,seed_import,models,routes}.py` | Bounding box and endpoint allowlist; OSM adapter; staging; CSV import; models; API |
| `apps/api/app/discovery/{contracts,registry,runner,cli}.py` | Backward-compatible extensions; review expiry; runner P2.2 rules; live CLI |
| `apps/api/app/core/settings.py`, `app/api/dependencies.py`, `app/main.py`, `app/accounts/policy.py`, `app/persistence/registry.py` | Activation settings; settings dependency; router; OSM rights entry; model registry |
| `apps/api/alembic/versions/0007_discovery_staging.py`, `tests/integration/test_migrations.py` | Schema; HEAD now 0007 |
| `apps/api/tests/integration/test_discovery_live.py` (36), `tests/unit/test_egress.py` (57), `tests/integration/test_discovery.py` | LIVE-01…09; static egress test tightened |
| `docs/adr/ADR-013-…`, `docs/contracts/source-adapters.md`, `docs/runbooks/discovery-sources.md`, `.env.example`, `README.md` | Decision, contract, activation procedure, documentation |

### Rollback

- **Stop OSM:** stop passing `HERMECIOUS_OSM_*`; runs fail closed before any request, and a run in flight stops at its next policy check.
- **Disable CSV:** set `enabled=False` in `seed_import.DESCRIPTOR`.
- **Revert code:** revert `18834d9` and the docs commit.
- **Data:** keep `source_records` and `discovery_candidates` rows (organization-scoped, attributed), and repair the schema forward. Downgrade 0007 only on a disposable database (tested by the migration suite).

### VERDICT: IMPLEMENTATION COMPLETE, LIVE INTEGRATION UNVERIFIED (LIVE-01…09 VERIFIED; LIVE-10 BLOCKED)

P2.2 is **not** marked VERIFIED, as Batch 04 requires when the canary cannot run.

**Owner action:** to verify LIVE-10, follow `docs/runbooks/discovery-sources.md` for one bounded run and record the observed endpoint, query bounds, request count, counts and attribution here.

**Effect on P2.3:** Batch 04 allows P2.3 on a "source-compatible imported fixture gate". The staged candidates from the CSV and fixture sources satisfy it, so P2.3 proceeds on that basis.

## P2.3 — Conservative, inspectable, reversible school identity resolution (2026-10-24)

**Scope:** Batch 04 §P2.3 and `OPUS_P2.3_PROMPT.md`. **Base:** `97c2585`. **Head:** `0c9bf27` (code), plus the docs and ledger commit. **Migration:** `0008_identity_resolution` (`identity_suggestions`, `candidate_account_links`, `identity_decisions`).

### Prerequisite: changed, explicitly

P2.2 is **not VERIFIED**: LIVE-10 is BLOCKED on the owner's live opt-in. The P2.3 prompt allows starting only with "a formally accepted, explicit source-compatible fixture-only exception documented as a changed prerequisite", and Batch 04 §0 lists the P2.3 prerequisite as "P2.2 VERIFIED **or source-compatible imported fixture gate**".

**The exception applied here:**
- P2.3 runs on the P2.2 staging contract (`discovery_candidates`), exercised by hermetic OSM-shaped stubs and operator CSV imports, which LIVE-01…09 verified.
- **No live result is claimed**, and nothing here depends on real Overpass data.
- **The owner should ratify this exception.** If it is rejected, P2.3 remains implemented but its gate reverts to "waiting on LIVE-10".

### Preflight

- **Baseline at `97c2585`:** check.sh 16/16 PASS (277 integration, 179 unit + contract).
- **Existing identity data:**
  - P1.2 `accounts.normalized_name` and `account_aliases`;
  - the P1.4 append-only facts with the correction chain;
  - P1.4 optimistic versions;
  - P2.2 `discovery_candidates` with `revision`.
- **No equivalent suggestion, decision or link tables existed**, so three minimal tables were added.

### Decision policy (ADR-014)

1. **Identity is a physical campus, not a brand.** The only automatic outcome is the exact `(org, provider, key)` re-observation, handled by P2.2 staging.
2. **Matcher `campus-match-1.0`:** pure, deterministic and symmetric; no network or model calls. Features are labels and scores, with `buying_authority` always unknown.
3. **Disqualifiers come before similarity:**
   - city, then branch (numbers and words), then locality, then coordinate conflict (0.5 km between points, 2 km when either is an area centre).
   - Names are compared within the same script only.
   - A chain domain without site evidence gives `distinct`.
   - Same provider with different ids gives `insufficient_evidence`.
4. **Only `suggest_review` and `insufficient_evidence` are stored.** A re-run recomputes open suggestions and never rewrites reviewed ones; it flags them with `evidence_changed_at`.
5. **Decisions:**
   - `command_id` makes them idempotent; a different payload gives 409.
   - A stale version gives 409; it is checked under a row lock and again by a compare-and-swap `UPDATE`.
   - An append-only log records `reverses_decision_id`.
6. **Undo of a candidate→account link:** a fact on the account that cites the candidate's source and was recorded after linking puts the suggestion into `reallocation_review`, and the link is kept. The undo completes only after those facts are corrected through the P1.4 chain. **Links are ended, never deleted.**
7. **Staging revision audits** now also store the previous permitted listing values: the IDENTITY-01 history.

### Gold fixtures (`tests/fixtures/identity_gold_v1.json`, `campus-identity-gold-v1`)

- **Coverage:** 26 labelled pairs, plus the upstream key-rejection case (batch fixture 18), plus duplicated candidates under concurrency (IDENTITY-09 integration).
- **Expected outcomes:** exact 3, suggest 6, distinct 11, insufficient 6.
- **Observed:** every case matches its exact resolution **and** its exact ordered reason codes. **Automatic merges of different source identities: 0.** Results are deterministic and symmetric for all 26.
- **Scope of the claim:** this measures only the fixtures; no general accuracy is claimed.

### Acceptance evidence

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| IDENTITY-01 | `test_identity_01_reingest_same_key_keeps_one_identity_with_history`, `test_identity_01_reviewed_decisions_survive_later_source_revisions`, gold 01–03 | Re-staging `node/501` with a new name updates the same row (revision 2); the `discovery.candidate_revised` audit holds the previous `display_name`; still 1 source record. The re-run recomputes the open suggestion (version 2, revisions [1, 2]), created 0. After a confirm, an upstream rename gives `evidence_changed_on_reviewed` 1: the status stays `confirmed` at version 2, `evidence_changed_at` is set, and there is still 1 decision | VERIFIED |
| IDENTITY-02 | `test_identity_02_cross_source_near_names_become_review_suggestions_only`, gold 04/05/14/15/21/26 | Pending `suggest_review` with `[name_near, same_locality]`, algorithm version, evidence source id and `buying_authority: unknown`. 2 candidates kept; 0 accounts and 0 links | VERIFIED |
| IDENTITY-03 | `test_identity_03_04_cities_campuses_and_chains_stay_distinct`, gold 06–09/19/25 | Lahore vs Gujranwala, Gulberg vs Johar Town campus, DHA Phase 5 vs 6, numbered schools and 1.2 km points are all distinct; 0 suggestions stored; 0 accounts | VERIFIED |
| IDENTITY-04 | Same test, gold 07/10/11/27, `features.buying_authority` assertions | Same brand and domain: distinct with `shared_domain_weak` / `chain_without_site_evidence`. Every suggestion and API item says `buying_authority: unknown` | VERIFIED |
| IDENTITY-05 | `test_identity_05_unknowns_stay_unknown_and_originals_are_kept`, gold 12/13/16/17/20 | Urdu spelling variants without a locality, and an exact name with a missing locality, both give `insufficient_evidence`. Urdu-only vs English-only gives `no_comparable_name_script`. The original Urdu `display_name` and `name_local` are unchanged | VERIFIED |
| IDENTITY-06 | `test_identity_06_confirm_via_api_is_audited_idempotent_and_keeps_provenance` | An operator confirms via the API (CSRF): `confirmed`, version 2. An identical replay returns `replayed: true` with the same `decision_id`: 1 decision, 1 link, 1 `identity.decision` audit. The link joins the candidate to the account (active). Source records and candidates are unchanged; history is exposed | VERIFIED |
| IDENTITY-07 | `test_identity_07_stale_reused_and_racing_commands_conflict`, `test_identity_07_undo_holds_facts_recorded_after_linking` | A reused command with a different payload, a stale version and an invalid transition each give `Conflict`. Two racing undos at the same version: one result and one `Conflict`, with 3 decisions total. Undo with a later fact citing the candidate's source: `reallocation_review`, `held_fact_ids = [that fact]`, link still active. A second undo gives `Conflict`. After the P1.4 correction, undo gives `undone`; the link is ended (not deleted) with `unlinked_by`; `reverses_decision_id` points to the confirm. All 3 facts are retained; a direct `UPDATE identity_decisions` fails with "append-only". Re-confirm creates a second link (history kept) | VERIFIED |
| IDENTITY-08 | `test_identity_08_cross_org_observer_and_csrf_are_denied` | An org B resolve considers 0 pairs (no cross-org pairing). Service responses: org B deciding on org A's suggestion gives `NotFound`; an observer gives `Forbidden`. A cross-org link insert gives `IntegrityError` (composite FK). HTTP: unauthenticated 401; observer decision or resolve 403; org B GET or POST 404 with an empty list; owner without CSRF 403; spoofed `organization_id` 422. The suggestion stays pending at version 1 with 0 decisions | VERIFIED |
| IDENTITY-09 | 26 gold cases plus scorecard, determinism, feature-text and upstream-key tests (`tests/unit/test_identity_matcher.py`, 58 tests); `test_identity_09_malicious_and_long_names_are_inert_and_concurrent_runs_do_not_duplicate` | Gold: all pass, 0 automatic merges. An instruction-like name with `DROP TABLE` is distinct. A long name is truncated before comparison. URL-like and invalid keys are rejected by `SourceKey` (tightened: `//` is impossible). Three concurrent resolver runs: exactly 1 suggestion, 0 errors, no text in features | VERIFIED |
| IDENTITY-10 | `test_identity_10_restart_and_rerun_keep_decisions_and_create_no_duplicates`; migration suite (upgrade/downgrade, model drift at 0008); full SOURCE + LIVE suites | After a decision, the app instance is closed and recreated; two re-runs give created 0, 0, unchanged 1; the same suggestion id is still `distinct` v2 with 1 decision. Migrations pass. SOURCE-01…10 (37) and LIVE-01…09 (36) still pass | VERIFIED |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `a2c4680` | 0 | 16/16 PASS. Integration **287**; unit + contract **237** (+58); web 2; e2e 9 + 1 |
| `./scripts/test-integration.sh tests/integration/test_identity.py` ×3 | 0 | 10 passed each time; 11 after `0c9bf27` |
| `./scripts/test-integration.sh … test_identity.py test_discovery.py test_discovery_live.py` | 0 | 83 passed |

### Defects found and fixed during verification

**Code**
- A URL-shaped key (`https://…`) passed the P2.2-widened `SourceKey`. The pattern now allows single `/` separators only.
- `No.` was taken as a branch word. Number words are now excluded.

**Tests whose expectations or setup were wrong** (no gold labels changed)
- The scorecard tally was miscounted (it now reads 6 suggest and 6 insufficient).
- The alef-hamza folding expectation was wrong; the matcher deliberately does not fold it.
- The canonical pair order depends on UUIDs. The test asserted a side, and now asserts the revisions instead.
- On a fixed clock, two decisions in one instant ordered randomly by id. The test now advances the clock.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| Different-city rule removed | 2 |
| Branch-conflict rule removed | 4 |
| Same core name auto-treated as exact | 19 |
| Explicit version check removed | **Survived**: the CAS `UPDATE … WHERE version` still rejects stale writes (defence in depth) |
| Version check **and** CAS rowcount removed | 1 |
| Undo ignores held facts | 1 |
| Replay ignores the payload digest | 1 |
| Chain-domain rule removed | 2 |
| Re-run rewrites reviewed suggestions | **Survived at first** → added `test_identity_01_reviewed_decisions_survive_later_source_revisions` (`0c9bf27`) → now caught (1) |

### Security and data integrity

- No network or model calls.
- Features carry no upstream text; reasons and names are inert data.
- Organization-scoped composite FKs make cross-org associations impossible at the database level.
- Roles: observers are read-only. CSRF applies to every mutation.
- **Nothing is deleted:**
  - candidates, sources, accounts and facts are never deleted;
  - links are ended, not removed;
  - decisions are append-only.
- **No accounts are created** (P2.4) and no contacts are touched.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/resolution/{matcher,models,service,routes}.py` | Matcher, persistence, review service, API |
| `apps/api/alembic/versions/0008_identity_resolution.py`, `tests/integration/test_migrations.py` | Schema; HEAD 0008 |
| `apps/api/app/discovery/{contracts,staging}.py` | `SourceKey` tightened; revision history values |
| `apps/api/app/main.py`, `app/persistence/registry.py` | Router; model registry |
| `apps/api/tests/fixtures/identity_gold_v1.json`, `tests/unit/test_identity_matcher.py`, `tests/integration/test_identity.py` | Gold set and IDENTITY-01…10 |
| `docs/adr/ADR-014-campus-identity-resolution.md`, `docs/contracts/identity-resolution.md`, `README.md` | Decision, contract, documentation |

### Rollback

- **Stop generating suggestions:** stop calling `/identity/resolve`.
- **Keep the history:** decisions and links are retained.
- **Reverse associations:** use undo (application-level compensation).
- **Revert code:** revert `a2c4680` and `0c9bf27`.
- **Schema:** downgrade 0008 only on a disposable database (rehearsed in the migration suite).

### VERDICT: VERIFIED (IDENTITY-01…10), under the documented P2.2 fixture-gate exception

P2.4 is next.

## P2.4 — Operator discovery runs, reviewable candidates and explicit admission (2026-10-24)

**Scope:** Batch 04 §P2.4 and `OPUS_P2.4_PROMPT.md`. **Base:** `70ea177`. **Head:** `8ccd204` (code), plus the docs and ledger commit. **Migration:** `0009_discovery_runs` (`discovery_runs`, `discovery_run_candidates`, append-only `discovery_review_decisions`); the dev database is upgraded to `0009 (head)`.

### Gate

**Satisfied:**
- P2.4 requires P2.3 VERIFIED, P1.1, P1.4 and P1.5. All are VERIFIED in this ledger.
- P2.3 is VERIFIED under the documented P2.2 fixture-gate exception.

**Still open:**
- **P2.2 LIVE-10 stays BLOCKED** and is not treated as verified.
- P2.4 is verified with the offline synthetic fixture and with hermetic OSM stubs only; **no live provider evidence exists.**

### Design decisions (ADR-015)

1. **Runs commit atomically** with a `discovery.run` v1 job (payload `{run_id}`) and the P1.5 outbox.
   - Budgets are snapshotted and downward-only (≤30, 5 pages, 20 fetches, 45 s; below the 60 s lease), then re-applied by the worker and the runner.
   - The area is the server-bound area of the provider; the browser never sends geometry.
2. **The worker re-resolves the provider under current policy.** Stale policy gives `failed` before any request.
   - It acts as the requester, after re-checking that the requester is active and allowed to make changes.
   - It then runs the P2.1/P2.2 runner (policy and cancellation are checked before every adapter call), links ≤30 staged candidates and runs the P2.3 resolver.
   - **The terminal state is written only in the fenced completion transaction.** Terminal runs are never resurrected, and unexpected errors fail the run on the last attempt.
3. **Admission happens only by explicit reviewer action.**
   - **`accept_new`:**
     - re-checks rights (candidate and source expiry, provider policy);
     - is refused while any open `suggest_review` same-campus suggestion exists;
     - creates one P1.4 account (`discovered`, research pending) with aliases (Urdu included) carrying the source, plus a P2.3 link and an `account.created` audit (origin `discovery_review`, `source_record_id`).
   - **`attach_existing`** needs the P2.3 reviewed link.
   - **Idempotency and concurrency:** commands are idempotent per key, a stale version gives 409, and concurrent accepts converge on one account.
4. **UI:** `/discovery`, `/discovery/new` and `/discovery/runs/[id]` in the existing Next.js app.
   - Run state comes from durable-state polling.
   - Cards show provenance, rights, expiry, attribution and unknowns, plus P2.3 match decisions.
   - Observers are read-only.
   - Rendering is safe: only escaped text, `https:`-only links and `lang`/`dir` on Urdu names.

### Acceptance evidence

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| RUN-01 | `test_run_01_operator_start_commits_run_job_and_outbox_atomically` | Sources offered: the fixture only (OSM unreviewed); ceilings 30/5/20/45. Operator POST gives 202 with status `pending`, `exhaustive: false` and the budget snapshot. The job `discovery.run` has payload `{run_id}` and `job_id` equal to the run's; there is 1 outbox event and 1 `discovery.run_requested` audit with the budget | VERIFIED |
| RUN-02 | `test_run_02_denials_happen_before_any_write` | No CSRF 403; unreviewed OSM 400; unknown provider 400; budget 31 or 600 s 422; `bbox` / `endpoint` / `organization_id` fields 422; observer 403; anonymous 401. **0 runs, 0 jobs, 0 outbox rows.** For another organization's run: GET, candidates and cancel all 404, and the list is empty | VERIFIED |
| RUN-03 | `test_run_03_worker_progress_counts_and_evidence_survive_reload` | Pending, then a P1.5 worker run (NoSink, no Redis), giving `completed`: examined 9, staged 4, rejected 5, displayed 4, 3 pages, job `succeeded`. A second worker pass claims nothing. Candidate reloads are byte-identical; every item is `unverified`, carries a fixture https source URL, and lists its unknowns. 0 accounts | VERIFIED |
| RUN-04 | `test_run_04_truncation_rate_limit_empty_and_stale_policy_are_truthful`, `test_run_04_worker_enforces_the_snapshotted_operator_budget` | 45 OSM elements: `completed`, `truncated`, 30 displayed, `candidate_cap`, 1 request, ODbL attribution. A 429 with Retry-After 300 gives `partial` (`rate_limited`), 0 shown. Empty gives `completed` with 0 shown. Review withdrawn after enqueue gives `failed` (`provider_disabled`) with **0 requests**. Budget 2/1: 2 displayed, `candidate_cap`, `truncated` (this exposed and fixed the stop-order defect below) | VERIFIED |
| RUN-05 | `test_run_05_create_replay_conflict_and_duplicate_workers`, `test_run_05_concurrent_identical_creates_make_one_run` | Same key and body give one run, with `replayed` true on the replay; a changed body gives 409; 1 run and 1 job. A stalled worker's lease expires and the rescuer completes the job; the stalled worker's late `execute` returns `lease_lost`. The run stays `completed` with 4 displayed, 4 links and 4 candidates. Three concurrent identical creates give 1 created and 2 replays, 1 job | VERIFIED |
| RUN-06 | `test_run_06_accept_new_is_one_audited_account_with_source_proof`, `test_run_06_concurrent_accepts_converge_on_one_account` | Accept gives 200 with an account id. The replay is identical apart from `replayed`; the same key with a different reason gives 409. 1 account (`discovered`, Lahore, **0 facts**), 1 decision, a P2.3 link, candidate `admitted`, and an `account.created` audit with origin and `source_record_id`. Two operators accepting concurrently get one account: one result converged, 1 link | VERIFIED |
| RUN-07 | `test_run_07_attach_requires_reviewed_identity_and_reject_never_merges`, `test_run_07_open_same_campus_match_blocks_new_account_until_decided`, `test_run_07_cancel_pending_and_running_never_resurrects_and_keeps_admissions` | Attach without P2.3 confirmation gives 409 ("same campus"). Reject and defer change review state only; 0 links. Co-located different names (P2.3 `co_located_different_names`): accept gives 409; after `mark_distinct` via the identity API, accept succeeds. Pending cancel: `cancelled`, job `cancelled`, and a repeat cancel is a no-op at the same version; the worker claims nothing. Cancel during a running OSM request: `cancelled` with `stop_reason: cancelled`, 0 shown. A late duplicate handler call returns `skipped` and the run stays cancelled. The earlier-admitted account is still present | VERIFIED |
| RUN-08 | `test_run_08_expired_rights_stale_version_and_foreign_ids_are_refused` | Stale version: 409. Foreign account attach: 404. Another organization deciding on our run: 404. Observer: 403. 400 days later (provenance past retention): accept gives 409 `candidate_rights_expired`. **0 accounts, 0 links** in the org | VERIFIED |
| RUN-09 | `test_run_09_unicode_and_long_names_round_trip_and_survive_restart`; e2e `RUN-09 observer sees the run read-only…`, `RUN-09 accepted review and account survive an api/web restart @after-restart` | A 250-character name round-trips. The Urdu `name:ur` with `<b>` markup is returned as raw text and kept as an alias after accept. App restart: the run is still `completed` with 1 accepted, and the account is readable. Browser: the observer has 0 buttons, no "New discovery run" link, sees the synthetic label, and a POST gives 403. After the real `docker compose restart api web` with volumes kept, the accepted review, tally and account page all persist | VERIFIED |
| RUN-10 | e2e `RUN-10 operator starts a bounded fixture run, reviews evidence and admits one campus` (`scripts/test-e2e.sh`, disposable full stack with real worker container) | The operator navigates Home → Discovery → New run. The source list shows the fixture only, with the synthetic notice, server-area notice and max 30; the operator sets 10 listings and 30 s and submits **by keyboard**. The page polls to "Completed (bounded run)": examined 9, staged 4, rejected 5, shown 4 (max 10), with the bounded-run notice. The card shows "Unverified listing", unknowns and an https source link. Accept as new campus gives review accepted. Opening the account shows the heading, `status discovered; version 1`, and no "qualified" text. **No outbound sends:** the codebase has no messaging client, and egress is limited to `app/egress` used only by `osm.py` (static test) | VERIFIED |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `040b93a` | 0 | 16/16 PASS. Integration 301; unit + contract 237; web 2; **e2e 11 + 2 after restart** (including RUN-10 and RUN-09) |
| `./scripts/test-integration.sh …test_discovery_runs.py test_discovery.py test_discovery_live.py` at `8ccd204` | 0 | 87 passed |
| Dev: build, then `alembic upgrade head` (`0008 -> 0009`), then `up --wait`, then `smoke-local.sh` | 0 | All smoke checks passed |

### Defects found and fixed during verification

**Code**
1. `runs.py` imported the egress client, which the P2.2 static guard caught. Construction moved to `osm.adapter_from_settings`, so `osm.py` stays the only egress user.
2. A second concurrent `accept_new` on the same run row got a 409 instead of converging. Fixed: it now converges when the row already holds the linked account.
3. **Stop order:** with budget 2 listings and 1 page, a full result was reported `partial` (`page_cap`). The candidate-cap check now runs first, so a full bounded result is `completed`, `candidate_cap`, `truncated` (`8ccd204`; SOURCE suites unchanged and passing).

**Test data:** RUN-09 placed two different school names on identical coordinates. P2.3 rightly raised `co_located_different_names` and admission was blocked; the coordinates were separated, and the behaviour became its own RUN-07 test.

**E2E harness and selectors**
- `getByLabel` on a select wrapped in its label is ambiguous, so the form now uses explicit `htmlFor`/`id` labels (better for assistive technology).
- A success message assertion raced the unmount of the control. Debug lines added to the untracked spec were removed by hand.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| No preflight source policy at create | 1 |
| Handler resurrects terminal runs | 2 |
| Open same-campus match ignored at accept | 1 |
| Rights re-check skipped | 1 |
| Convergence removed (the first attempt's anchor didn't match; rerun with the right anchor) | 1 |
| Pending cancel becomes a no-op | 1 |
| Worker ignores the budget snapshot | 2 |
| Attach without a P2.3 link | 1 |
| Cancellation never checked by the runner | 1 |

### Security and data integrity

**Inputs and access**
- No URL, geometry or provider query is accepted from clients, and the provider resolves server-side.
- Mutations require CSRF and owner or operator; observers are read-only (API and UI).
- Queries, foreign keys and links are organization-scoped.

**Execution**
- Policy is re-checked at enqueue, execution and every adapter call.
- Terminal states are fenced; cancellation is cooperative.

**Accounts and data**
- Accounts are never auto-created and nothing is deleted on cancel.
- No facts, contacts or needs are inferred.
- Rights expiry blocks admission.
- No messaging, campaigns or model calls exist.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/discovery/{runs,models,routes,runner,osm,cli}.py` | Runs service, worker and review; models; API; cancellation and stop order; adapter factory |
| `apps/api/app/jobs/{registry,runner}.py` | `discovery.run` v1; `JobContext.environment` and `max_attempts` |
| `apps/api/alembic/versions/0009_discovery_runs.py`, `tests/integration/test_migrations.py` | Schema; HEAD 0009 |
| `apps/api/tests/integration/test_discovery_runs.py` (14), `tests/integration/test_discovery.py` | RUN-01…09; static egress test |
| `apps/web/app/discovery/**`, `apps/web/lib/discovery.ts`, `apps/web/app/page.tsx`, `apps/web/e2e/discovery.spec.ts` | UI and E2E |
| `docs/adr/ADR-015-…`, `docs/contracts/source-adapters.md`, `docs/runbooks/discovery-sources.md`, `README.md` | Documentation |

### Rollback

- **Stop new runs:** disable or unconfigure the provider; creation refuses before writing.
- **Pause execution:** stop the worker. Pending runs stay visible and can be cancelled.
- **Keep the history:** runs, decisions, links and accounts are retained.
- **Revert code:** revert `974e273`, `040b93a` and `8ccd204`.
- **Schema:** downgrade 0009 only on a disposable database.

### VERDICT: VERIFIED (RUN-01…10), with offline fixture and hermetic stubs; live-source evidence still BLOCKED (P2.2 LIVE-10)

Batch 04 is complete except for the owner-gated LIVE-10. P3.1 is next.

## P3.1 — Source-backed research and extraction (2026-10-24)

**Scope:** `OPUS_P3.1_PROMPT.md`. **Base:** P2.4 docs head. **Head:** `82b95f9` (code), plus the docs and ledger commit. **Migration:** `0010_research` (`research_runs`, `research_observations`, `research_claims`); the dev database is upgraded to `0010 (head)`.

### Specification gap (recorded, not hidden)

The prompt binds to `docs/phases/HERMECIOUS_BATCH_05_P3.1-P3.3.md`, which **does not exist** in the repository or nearby folders; only `OPUS_P3.x` and `OPUS_P4.x` prompts were added.

**What served as the specification:** the P3.1 prompt itself (detailed: order, limits and RESEARCH-01…10) and blueprint §4 P3.1.

**The prompt's DTO names** (`ResearchRequest`, `ResearchObservationDTO`, `ExtractedClaimDTO`, `ResearchRunResult`) were mapped onto this codebase as:

| Prompt name | Implementation |
|---|---|
| `ResearchRequest` | `ResearchBody` |
| `ResearchObservationDTO` | observation view |
| `ExtractedClaimDTO` | `extract.Proposal` and the claim view |
| `ResearchRunResult` | `run_view` / `run_detail` |

**Owner action:** supply Batch 05 if it differs in any binding way, and this entry will be reconciled.

### Gate

- P2.4 is VERIFIED.
- P2.2 LIVE-10 remains BLOCKED. P3.1 needs no live discovery source, because research uses associated fixture sources.

### Design decisions (ADR-016)

1. **Sources:** ≤5 sources **already associated** with the account (admitted listing, alias provenance or fact source).
   - Rights are re-checked at scheduling, execution, review and rendering: expiry, provider rights and URL screen, `metadata_only`, reviewed fetch-licensed descriptor, environment and rights version.
   - There are no URLs, hostnames or queries in requests.
2. **Fetch by `(provider, external_key)` only.** The fixture document fetcher is the only enabled fetcher. **Live website research fails closed (`live_fetch_not_authorized`)**, so the live canary is BLOCKED.
3. **Documents:**
   - Refused: compressed, non-text media, over 2 MiB, invalid UTF-8, or no visible text.
   - HTML is reduced to visible text; scripts, styles, iframes and comments are dropped.
   - Budgets: 60 000 characters per run, 30 s per source, 60 s per run.
   - No page body is stored; observations keep a hash and counts only.
4. **Extraction `rules-1.0`:**
   - English and Urdu rules over P1.2 claim types; exact locators and span hashes.
   - An independent verifier re-derives each claim from its span.
   - It abstains on negation and instruction-like text, and never asserts software, ownership, authority or need. At most 25 claims.
   - **No model** (no approved ModelGateway).
5. **Excerpts are stored only for `full_allowed` sources** (a database check enforces it) and are masked of emails and long numbers. `derived_only` sources keep the locator and hash only.
6. **Review:** an idempotency key, a version check and a reason are required. Accept re-checks rights and creates one P1.4 source-supported fact, or links an identical current one.

### Acceptance evidence

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| RESEARCH-01 | `test_research_01_atomic_run_on_admitted_account_with_two_permitted_sources`; e2e RESEARCH-10 (admitted via P2.4) | Two associated eligible sources. 202 with status `pending`, `rules-1.0`, 2 sources. The `research.run` job payload is `{run_id}`, with 1 outbox event. The worker produces `completed`: 2 processed, 10 proposed, every observation processed | VERIFIED |
| RESEARCH-02 | `test_research_02_excerpt_anchored_claims_review_into_source_supported_facts`; unit `test_english_claims_carry_exact_locators`, `test_urdu_claims_are_extracted_without_transliteration` | English `campus_count 2` with the exact excerpt sentence, stored under `full_allowed` with an https fixture source URL. Urdu `campus_count 3` (`ہمارے تین کیمپس ہیں۔`) has `locator_only`, no excerpt (`derived_only`), and a valid span hash. 0 facts before review. Accept (strong) gives a `source_supported` fact with excerpt and source; the derived-only fact has no excerpt; audit `account.fact_added` origin `research_review` | VERIFIED |
| RESEARCH-03 | `test_research_03_evidence_never_crosses_between_similarly_named_campuses` | Same-named Johar Town and DHA accounts. A DHA run citing the Johar source gives 400 `source_not_associated`; a DHA run on its own metadata-only source gives 400. After the Johar run: 0 claims or runs on DHA, 6 claims on Johar | VERIFIED |
| RESEARCH-04 | `test_research_04_abstains_on_injection_negation_and_absence`; unit abstention (5) and verifier (10) tests | Abstained exactly `{instruction_like_text: 1, negated_statement: 1}`. No `{count: 40}`, no "Excel" or "SYSTEM" text, and claim types limited to signals, campus count and contact channel. The phone claim's excerpt is masked (`[number]`). "No portal" and "every school needs an ERP" give 0 claims. The verifier rejects disallowed type, invalid value, unsupported value, out-of-bounds span, unknown rule, changed span and injected span | VERIFIED |
| RESEARCH-05 | `test_research_05_revoked_or_expired_rights_store_and_publish_nothing` | Rights expire between scheduling and execution: the observation is `skipped` (`source_rights_expired`) with 0 claims. Accept after expiry gives 409 `source_rights_expired`. Rendering after expiry withholds the excerpt with that reason. 0 facts. Database: 0 non-`full_allowed` claims with excerpt text. Metadata-only sources are refused at scheduling (RESEARCH-03) | VERIFIED |
| RESEARCH-06 | `test_research_06_unsafe_documents_and_budgets_fail_safely`; unit `test_unsafe_or_unsupported_documents_are_refused` (8), `test_html_is_reduced…`, `test_normalized_text_respects…`, `test_only_the_fixture_provider_can_fetch…` | gzip, PDF, more than 2 MiB and invalid UTF-8 each give `failed` with that reason and 0 claims. A 31 s fetch gives `source_time_budget`. A 61 s first source gives `partial` (`job_time_budget`) and **only one source fetched**. A first-party website source gives 400 `live_fetch_not_authorized`. br and SVG are refused; scripts, iframes, comments and bidi are removed. **SSRF, redirect and DNS:** no URL fetch path exists in research. The only egress client is P2.2's pinned client (LIVE-09), unused here | VERIFIED (fixture). The live fetch path does not exist and is BLOCKED |
| RESEARCH-07 | `test_research_07_replay_stale_lease_and_redelivery_never_duplicate`, `test_research_07_crash_mid_run_retries_without_duplicates` | Same key gives the same run; the same key on another account gives 409. A stalled worker's lease expires and the rescuer completes; the late `execute` returns `lease_lost`; a redelivered handler is skipped. Exactly 6 claims and 1 observation. A crash after the first source commits gives `retry_wait` with the run still running; the retry completes with 10 claims, so the first source's claims were not doubled | VERIFIED |
| RESEARCH-08 | `test_research_08_rate_limits_partial_and_cancellation_keep_true_status` | One source 429: `partial` (`rate_limited`), 1 failed, 6 claims. Both 503: `failed` (`unavailable`), 0 claims. Pending cancel: `cancelled`, and the worker claims nothing. Cancel committed during the first fetch: `cancelled`, **1 fetch only** | VERIFIED |
| RESEARCH-09 | `test_research_09_auth_roles_org_scope_csrf_and_review_races`, `test_research_09_review_replay_is_idempotent` | Anonymous 401; observer POST 403 (GET 200); missing CSRF 403; `source_url` field 422; 6 sources 422. Another org: run, sources and claim review all 404; using our source id gives 400. Observer review 403. Racing accept and reject: `[200, 409]`, ≤1 fact; `research.claim_reviewed` audit present. Review replay returns the same fact; the same key with a different reason gives 409 | VERIFIED |
| RESEARCH-10 | e2e `research.spec.ts` (3 tests, disposable stack, real worker); `bash scripts/check.sh` | The operator admits the Johar Town listing, opens the account, selects the fixture source and clicks **Run research**. The page polls to "Completed: 6 proposed claims from 1 source(s)" with "2 statement(s) skipped". There is no injection text, "40 campuses" or "Excel" on the page. The claim shows "Proposed (not verified)", the excerpt and an https source link. Accept gives "Accepted by a reviewer"; the Evidence section shows a Source-supported `campus_count: count: 2` with the excerpt and a `account.fact_added` audit. The observer has 0 buttons in Research. After restart, the accepted claim and fact persist. **No sends:** there is no messaging code; egress is unchanged. All prior suites pass | VERIFIED (fixture); **live canary BLOCKED** |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `82b95f9` | 0 | 16/16 PASS. Integration **313** (+11); unit + contract **262** (+25); web 2; **e2e 13 + 3** |
| `./scripts/test-integration.sh tests/integration/test_research.py` ×2 | 0 | 11 passed each time |
| Dev: build, `alembic upgrade head` (`0009 -> 0010`), `up --wait`, smoke | 0 | All smoke checks passed |

### Defects found and fixed during verification

**Test design**
- A hand-scripted monotonic tick list was fragile. It was replaced by a fake clock advanced by the fetch itself.
- Source order follows the sorted run ids, so the test now asserts one fetch rather than which key is fetched first.

**Fixture**
- The fixture's phone line included "not real", which correctly triggered negation. It was reworded so the extractor's contact-channel rule is exercised.
- The injection sentence was made claim-shaped, so abstention is actually tested.

**E2E:** the P2.4 after-restart tally assertion was hard-coded, and later specs admit more listings. It now matches a range.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| Association check removed | 1 |
| Metadata-only allowed | 1 |
| Excerpts for all rights classes | 3 |
| Injection abstention removed | 8 |
| Verifier accepts anything | 3 |
| gzip allowed | 3 |
| Review skips the rights re-check | 1 |
| Runner ignores cancellation | 1 |
| Excerpt redaction removed | 2 |
| Rendering ignores lapsed rights | 1 |

### Security, privacy and cost

- **Data minimisation:** no page bodies, cookies or raw exceptions are stored. Excerpts are bounded and redacted, and kept only with full rights.
- **No egress or model:** no URL fetch in research, no model calls and no network in tests (fixture fetcher).
- **No N+1 fetching:** one fetch per selected source.
- **Bounded cost:** characters, time, claims and sources are all capped.
- **Organization scope:** composite FKs and scoped queries throughout.
- **No duplicate facts:** an identical current fact is linked, not repeated.
- **No fabricated confidence:** the reviewer chooses the confidence. A proposal is never displayed as verified.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/research/{models,documents,extract,service,routes}.py`, `fixtures/school_documents_v1.json` | Research slice |
| `apps/api/app/jobs/registry.py`, `app/main.py`, `app/persistence/registry.py` | `research.run` v1; router; models |
| `apps/api/alembic/versions/0010_research.py`, `tests/integration/test_migrations.py` | Schema; HEAD 0010 |
| `apps/api/tests/unit/test_research_extract.py` (25), `tests/integration/test_research.py` (11) | Tests |
| `apps/web/app/accounts/[id]/{research,research-actions}.tsx`, `page.tsx`, `lib/research.ts`, `e2e/research.spec.ts`, `e2e/discovery.spec.ts` | UI and E2E |
| `docs/adr/ADR-016-…`, `docs/contracts/research.md`, `README.md` | Documentation |

### Rollback

- **Stop:** stop scheduling research.
- **Keep:** runs, claims and facts are retained; facts are corrected through the P1.4 chain.
- **Revert code:** revert `45d4717` and `82b95f9`.
- **Schema:** downgrade 0010 only on a disposable database.

### VERDICT: VERIFIED (RESEARCH-01…10) with fixture documents; live website research BLOCKED (not authorized; fails closed)

**P3.2 is UNBLOCKED:** source-backed facts with locators and reviewer acceptance exist for the rubric to read. P3.2 remains subject to the same missing-Batch-05 caveat.

## P3.2 — School operations signals (2026-10-24)

**Scope:** `OPUS_P3.2_PROMPT.md` (Batch 05 absent; same caveat as P3.1). **Base:** `ce7ab23`. **Head:** `cf6b1c6` (code), plus the docs and ledger commit. **Migration:** `0011_school_signals` (`school_signal_snapshots`, append-only); the dev database is upgraded to `0011 (head)`.

### Gate

- P3.1 RESEARCH-01…10 are VERIFIED with fixture documents; live research is BLOCKED.
- P3.2 consumes only P1.4 facts, including those created by P3.1 reviewer acceptance, so the live block does not prevent verification.

### Design decisions (ADR-017)

1. **A pure, pinned rubric** `school-signals-1.0` with exactly six keys. Inputs are the account's current facts plus the reviewed-link count.
   - **Fact eligibility:** usable, stale (rights expired), unauditable (metadata-only), hypothesis, disputed or rejected.
   - **States:** observed only from usable facts. Conflicting keeps every reference. Hypothesis covers unverified, unauditable or disputed evidence. Unknown otherwise, listing stale facts for re-checking.
2. **Fixed, cautious wording.** Operator text is quoted as data. Each key carries a caveat (the notice is not process, tool, need, budget or consent) and one respectful discovery question. `ranking` is always `null`.
3. **Immutable snapshots**, deduped on `(org, account, rubric, input_digest)`.
   - The digest includes each fact's eligibility now, so expiry, corrections, rejections and new facts all produce a new digest.
   - Reads flag `needs_reassessment`.
   - JSONB key order is restored to the canonical order on read.

### Acceptance evidence

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| SCHOOL-01 | `test_school_01_one_admissions_notice_gives_a_six_key_cited_brief`; unit `test_gate_01_admissions_notice_cites_exactly_its_fact` | One accepted admissions claim; generate gives 201 with `school-signals-1.0` and the six keys in canonical order. Admissions is `observed` and cites exactly that fact id; the other five are `unknown`. The citation carries the fixture https URL and excerpt flag; `ranking` is null. Latest has `needs_reassessment: false` | VERIFIED |
| SCHOOL-02 | `test_school_02_listing_only_account_keeps_campus_and_autonomy_unknown`; unit `test_gate_02…`, cases 02 and 20 | A metadata-only listing admitted via P2.4 gives `linked_listings` 1, with all six keys `unknown`. The campus statement says "a listing is not a campus count" | VERIFIED |
| SCHOOL-03 | `test_school_03_04_05_notices_never_become_process_tool_or_consent_claims`; unit case 03 plus the `FORBIDDEN` scan on all 20 cases | Admissions is `observed`, complexity `unknown`. The rubric's own words contain none of paper, Excel, no ERP, manual, arrears, opt-in, consented or priority | VERIFIED |
| SCHOOL-04 | Same test; unit case 04 | Fee process is `observed`; the caveat reads "do not show how payments are reconciled"; no reconciliation or arrears claim | VERIFIED |
| SCHOOL-05 | Same test; unit case 05 | Public phone listed gives contact route `observed`, with the caveat "not consent…". **The table list is unchanged by generation, and no campaign, contact, message, outbound or task table exists** | VERIFIED |
| SCHOOL-06 | `test_school_06_contradictory_sources_are_conflicting_with_both_citations`; unit cases 06 and 11, `test_gate_06…` | Campus counts 2 vs 3 give `conflicting` with both ids and "none is chosen". A disputed fact alongside a supported one is also conflicting | VERIFIED |
| SCHOOL-07 | `test_school_07_corrections_expiry_and_rejections_force_reassessment`; unit cases 07, 09, 10 and 12, `test_gate_07…`, `test_digest_changes…` | A rejected claim leaves campus `unknown`. A P1.4 correction gives `needs_reassessment: true`; the new snapshot shows fees as `hypothesis`. Source expiry gives reassessment true; the new snapshot shows admissions `unknown` with that fact in `stale_fact_ids` and freshness `stale`. History holds 4 snapshots, newest first, and the first snapshot is unchanged | VERIFIED |
| SCHOOL-08 | `test_school_08_replay_and_concurrent_generation_yield_one_snapshot` | Generate twice: 201, then 200 with `created: false` and the same id. After new evidence, three concurrent generations give `[200, 200, 201]`, for 2 snapshots total. `UPDATE school_signal_snapshots` raises "append-only" | VERIFIED |
| SCHOOL-09 | `test_school_09_auth_scope_urdu_injection_and_unsafe_citations`; unit cases 14 and 17 | Anonymous 401; observer generate 403 (read 200); missing CSRF 403. The Urdu-sourced claim (derived-only) gives "A cited source states: 3 campuses.". An injected operator signal appears only quoted, and "qualified" is not in the rubric's words. A `javascript:` source URL is refused at P1.2 insertion. Other organizations get 404 for generate, latest and snapshot | VERIFIED |
| SCHOOL-10 | e2e `school.spec.ts` (3); `bash scripts/check.sh` | The operator generates the brief on the researched account: six cards appear. Campus is "Observed (cited source)" with "A cited source states: 2 campuses.", an https citation link and the discovery question; autonomy is `Unknown`. The only score, rank or qualify text is the disclaimer. Re-generating says "No evidence changed…"; reload and restart persist; the observer has 0 buttons. All prior suites pass, with no ranking and no sends | VERIFIED |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `cf6b1c6` | 0 | 16/16 PASS. Integration **320** (+7); unit + contract **288** (+26); web 2; **e2e 15 + 4** |
| `./scripts/test-integration.sh tests/integration/test_school_signals.py` ×2 | 0 | 7 passed each time |
| Dev: build, `alembic upgrade head` (`0010 -> 0011`), `up --wait`, smoke | 0 | All smoke checks passed |

### Defects found and fixed during verification

- **JSONB reorders keys,** so the API returned the six signals out of order. Reads now restore canonical rubric order (code fix).
- **Test issues** (no rubric outputs or labels changed):
  - a wording mismatch in the test ("does" vs "do");
  - snapshots generated on one fixed-clock instant ordered by id, so the test now advances the clock.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| Expired evidence counts as usable | 4 |
| Metadata-only certifies an observation | 2 |
| Conflicts collapsed | 4 |
| Hypothesis treated as observed | 3 |
| A listing implies an observed campus | 4 |
| Superseded facts included | 1 |
| Digest ignores eligibility | 2 |
| Snapshot dedupe removed | 1 |

### Self-review of wording (as a school administrator would read it)

- Statements only repeat what a cited source says ("A cited source states: …") or say "Unknown".
- Caveats explain what the evidence does **not** show, without implying a deficiency.
- The six discovery questions are open, neutral and answerable (for example "How are fee payments recorded and matched to students today?").
- I removed nothing further. No statement presumes paper processes, problems, budget or interest.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/signals/{rubric,models,service,routes}.py` | Rubric and snapshots |
| `apps/api/alembic/versions/0011_school_signals.py`, `tests/integration/test_migrations.py` | Schema; HEAD 0011 |
| `apps/api/app/main.py`, `app/persistence/registry.py` | Router; models |
| `apps/api/tests/unit/test_school_signals.py` (26), `tests/integration/test_school_signals.py` (7) | Tests |
| `apps/web/app/accounts/[id]/{school-signals,school-signals-actions}.tsx`, `page.tsx`, `lib/signals.ts`, `e2e/school.spec.ts` | UI and E2E |
| `docs/adr/ADR-017-…`, `docs/contracts/school-signals.md`, `README.md` | Documentation |

### Rollback

- **Stop:** stop generating briefs.
- **Keep:** snapshots are immutable history.
- **Revert code:** revert `20420fb` and `cf6b1c6`.
- **Schema:** downgrade 0011 only on a disposable database.

### VERDICT: VERIFIED (SCHOOL-01…10)

**P3.3 is UNBLOCKED.** Caveats carried forward: Batch 05 is absent; live research is BLOCKED; P2.2 LIVE-10 is BLOCKED.

## P3.3 — Explainable four-axis qualification (2026-10-24)

**Scope:** `OPUS_P3.3_PROMPT.md` (Batch 05 absent; same caveat). **Base:** `546dcae`. **Head:** `2b7ba29` (code), plus the docs and ledger commit. **Migration:** `0012_assessments` (append-only); the dev database is upgraded to `0012 (head)`.

### Gate

- P3.2 SCHOOL-01…10 are VERIFIED.
- P1.3 published-offer constraints are demonstrable: `assert_publishable` and `sales_ready` are covered by existing offer tests.
- The QUALIFY tests publish a real evidenced offer through `offers.service.publish`.

### Design decisions (ADR-018)

1. **Pure rubric `school-qualification-1.0`:** four ordinal dimensions, each with a reason, cited fact ids and questions. `unknown` is never `weak`. There is no percentage, composite or probability.
2. **Precedence:**
   1. `exclude` only on a cited, current `hard_disqualifier`;
   2. `nurture` only on a cited `review_deferral` still in force, with no reminder;
   3. `contact_now` only with fit, need and access ≥ moderate, strong delivery from a currently **published**, matching offer, and no conflicting, stale or possible-disqualifier evidence;
   4. otherwise `investigate`, listing the blockers.
3. **Wording and safety:** `contact_now` displays "Research priority: contact candidate — channel eligibility not checked." `channel_eligibility` is fixed to `not_evaluated` by a database check. There are no send or enroll controls.
4. **Two typed P1.2 claim types** (`hard_disqualifier`, `review_deferral`) make exclude and nurture evidence-based. Unverified entries only raise questions.
5. **Append-only assessments.** Assess refreshes the P3.2 brief and adds a revision only on changed inputs; the digest covers the brief, the offer's published revision and capabilities, and deferral validity. Reads flag `needs_reassessment`.
6. **Overrides:**
   - require the latest id and `expected_revision`, plus a reason and typed changes;
   - keep the machine explanation and record before/after in the audit;
   - cannot contradict a cited hard disqualifier.

### Acceptance evidence

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| QUALIFY-01 | `test_qualify_01_03_…`; unit `test_qualify_01_four_ordinal_dimensions_and_no_probability` | Four dimensions, each with a reason and fact ids. DB row: `school-qualification-1.0`, origin rubric, revision 1, `offer_id`, `offer_revision_id`, `capability_version caps-2026-10` and `signal_snapshot_id`. Re-assess gives 200 with the same id. No percentage, probability or score text | VERIFIED |
| QUALIFY-02 | `test_qualify_02_directory_only_listing_is_unknown_and_investigate`; unit `test_qualify_02…` | A metadata-only listing account: all four `unknown`; DB decision `investigate`; no ERP or budget text | VERIFIED |
| QUALIFY-03 | `test_qualify_01_03_…`; unit `test_qualify_03…` (2) | Accepted fixture facts (2 campuses, admissions, fees, website form) plus a published offer (admissions and fees) give strong / moderate / moderate / strong and `contact_now` with the exact research-priority text, `not_evaluated` and `probability: null`. A generic phone instead of a form gives access `weak` and `investigate`. **The public table list is unchanged by assessment, and no campaign, outreach, permission, message or task table exists** | VERIFIED |
| QUALIFY-04 | `test_qualify_04_05_…`; unit `test_qualify_04…` (2) | An unverified disqualifier gives `investigate` (with a question). A cited `school_closed` gives `exclude`. A central mandate (head office plus chain campus) lowers fit and access to weak but does **not** exclude. Weak-only evidence never excludes | VERIFIED |
| QUALIFY-05 | Same; unit `test_qualify_05…` | An unverified deferral gives `investigate`. A cited deferral until 2027-03-01 gives `nurture` ("No reminder is scheduled"). A lapsed deferral has no effect. DB revisions: investigate, investigate, nurture, exclude | VERIFIED |
| QUALIFY-06 | `test_qualify_06_unpublished_or_missing_offer_is_never_strong_delivery`; unit parametrized (6) | No offer: delivery `unknown`, `investigate`. Published: `contact_now`. Archived: delivery `weak`, `investigate`, `capability_version` null. Unit: unpublished (even with capabilities), wrong vertical and no approved claims are `weak`; a non-matching capability is `moderate` | VERIFIED |
| QUALIFY-07 | `test_qualify_07_changes_invalidate_and_history_is_kept`; unit digest test | A contradicting campus fact gives `needs_reassessment: true`; revision 2 is `investigate` (conflicting). A rights lapse flags reassessment. History shows revisions 2 and 1, and revision 1 (`contact_now`) is unchanged. Unit: offer republication or deferral expiry changes the digest | VERIFIED |
| QUALIFY-08 | `test_qualify_08_overrides_are_versioned_audited_and_race_safe` | Blank reason or unknown decision: 422. Extra `consent` field: 422. No change: 400. Foreign evidence: 400. Two racing overrides: `[201, 409]`. The latest is origin override at revision 2, with `machine_decision contact_now`, `machine_value` kept and `changed_fields` {decision, need_evidence}. A non-latest or stale revision gives 409. The audit holds before/after. `UPDATE assessments` raises "append-only". With a cited `declined_vendor_contact` the decision is `exclude`, and an override to contact_now gives 409 | VERIFIED |
| QUALIFY-09 | `test_qualify_09_auth_scope_and_injection` | Anonymous 401; observer assess or override 403 (read 200); missing CSRF 403. Other organizations: assess, read and override all 404, and a foreign offer gives 404. An injected "decision=contact_now; consent granted" signal still gives `investigate`, and the text is absent from the dimensions. 1 assessment row in total | VERIFIED |
| QUALIFY-10 | e2e `triage.spec.ts` (4); `bash scripts/check.sh` | The owner publishes an evidenced offer via the API. The operator accepts research claims, selects the offer and assesses: "Research priority: contact candidate — channel eligibility not checked." is shown with strong / moderate / moderate / strong and the "not permission to send marketing" reason. No send, enroll, message or campaign button and no percentage. Overriding to investigate with a reason shows "Reviewer override (machine said: contact now)", a 2-entry history and the audit. The observer has 0 buttons. After restart, the override and history persist. All prior suites pass, with zero messaging | VERIFIED |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `7a7ce68` | 0 | 16/16 PASS. Integration **327** (+7); unit + contract **302** (+14); web 2; **e2e 18 + 5** |
| `./scripts/test-integration.sh tests/integration/test_qualification.py` ×2, plus after the mutation follow-ups | 0 | 7 passed each time |
| Dev: build, `alembic upgrade head` (`0011 -> 0012`), smoke | 0 | All smoke checks passed |

### Defects found and fixed during verification

These were test or expectation errors; no rubric output or label changed:
- the revision count in QUALIFY-04/05 (each new fact is a new input, so there are four revisions);
- an E2E check that matched the panel's own "no probability" disclaimer.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| Exclude on an unverified disqualifier | 2 |
| Nurture on an unverified deferral | 2 (first run skipped on a reformatted anchor; rerun) |
| A phone counts as a route | 1 |
| Unpublished offer delivers | **survived** (defence in depth: an unpublished view carries no capabilities) → added a unit case → caught (1) |
| Conflicts ignored | 2 |
| Unknown access becomes moderate | 2 |
| Override ignores the hard disqualifier | 1 |
| Override skips the revision check | **survived** (the latest-id check also catches it) → added a right-id/stale-revision test → caught (1) |
| Assess dedupe removed | 1 |

### Self-review: every path to `contact_now`

- Requires fit ≥ moderate. That needs observed operations or size from usable (current, auditable, source-supported) facts.
- Requires need ≥ moderate: an observed public area. The wording disclaims pain and intent.
- Requires access ≥ moderate: a cited form or email route only. A phone or social page is not enough, and a head office blocks it.
- Requires strong delivery: a published revision's sales-approved capability matching an observed area.
- Blocked by: no conflicts, no stale facts, no possible disqualifier, no deferral, no hard disqualifier.

**If a source expires between read and commit:** assess evaluates eligibility at a single `now`, and the next read's digest flags `needs_reassessment`, which the UI shows. That is fail-safe, because nothing acts on `contact_now` automatically.

### Changed files

| File | Reason |
|---|---|
| `apps/api/app/qualification/{rubric,models,service,routes}.py` | Qualification |
| `apps/api/app/accounts/claims.py` | Two claim types |
| `apps/api/alembic/versions/0012_assessments.py`, `tests/integration/test_migrations.py` | Schema; HEAD 0012 |
| `apps/api/app/main.py`, `app/persistence/registry.py` | Router; models |
| `apps/api/tests/unit/test_qualification.py` (15), `tests/integration/test_qualification.py` (7) | Tests |
| `apps/web/app/accounts/[id]/{qualification,qualification-actions}.tsx`, `page.tsx`, `lib/qualification.ts`, `lib/accounts.ts`, `e2e/triage.spec.ts` | UI and E2E |
| `docs/adr/ADR-018-…`, `docs/contracts/qualification.md`, `README.md` | Documentation |

### Rollback

- **Stop:** stop assessing.
- **Keep:** assessments and overrides are history.
- **Revert code:** revert `44d2c30`, `7a7ce68` and `2b7ba29`.
- **Schema:** downgrade 0012 only on a disposable database.

### VERDICT: VERIFIED (QUALIFY-01…10), on synthetic fixtures. Production accuracy is an unmeasured hypothesis until P3.4.

**P3.4 is UNBLOCKED** for the evaluation harness. A real 30-account evaluation needs real, rights-reviewed data, and live sources are still BLOCKED.

## P3.4 — Evidence quality evaluation (2026-10-24)

**Scope:** `OPUS_P3.4_PROMPT.md`. **Base:** P3.3 docs head. **Head:** `599608e` (code), plus the docs and ledger commit. **Migration:** `0013_evidence_evaluation` (runs and items, plus append-only verdicts and remediations); the dev database is upgraded to `0013 (head)`.

### Specification gap

`docs/phases/HERMECIOUS_BATCH_06_P3.4-P4.2.md` (named as binding) is **absent**, like Batch 05. I implemented from the P3.4 prompt and the blueprint. The owner should supply Batch 06 if it differs.

### Gate

- P3.1–P3.3 are VERIFIED, on fixtures.
- **There are no real, rights-reviewed Lahore accounts**, because the live sources are BLOCKED, **and no authorized human reviewer has audited any.** EVAL-07 therefore cannot be run.

### Design decisions (ADR-019)

1. **Displayed factual claim** means:
   - every current `source_supported` fact;
   - every P3.2 `observed` or `conflicting` statement;
   - every P3.3 dimension shown `strong` or `moderate`.

   Hypotheses, unknowns and questions are labelled as unverified on screen and are not claims.
2. **Seeded deterministic sample:** up to 30 distinct accounts by `sha256(seed:id)`, with real, synthetic or unsourced provenance.
   - Any synthetic account gives `SYNTHETIC_CORPUS`; fewer than 30 real gives `INSUFFICIENT_CORPUS`. Both are BLOCKED.
   - A fingerprint covers the items and their rights versions. Items carry rights-safe summaries and no excerpts.
3. **Human verdicts:** five values, append-only revisions. `supported` is refused for unusable or contradicted evidence.
4. **Metric: supported / all items.** Lapsed evidence does not count. 0/0, below 90% (integer arithmetic) or a still-displayed failure each give FAILED. Finalization is refused while items are pending.
5. **Remediation:** P1.4 demotion of the failed fact, with an append-only link. P3.2/P3.3 are invalidated through their digests. A post-remediation run keeps the baseline intact.
6. **Fail-closed enrollment gate:** it opens only for a finalized, real, PASSED run.

### Acceptance evidence

| ID | Executed test(s) | Observed | Status |
|---|---|---|---|
| EVAL-01 | `test_eval_01_twenty_nine_real_accounts_block…`, `test_eval_01_exactly_thirty_real_distinct_deterministic…` | 29 real, 2 synthetic and 1 unsourced account: `INSUFFICIENT_CORPUS`, BLOCKED, 29 sampled; excluded 2 `synthetic_not_eligible` and 1 `no_sources`. With 32 real plus a duplicate campus: corpus OK with 30. The same seed gives identical account ids and fingerprint; another seed gives another subset. The duplicate campus is never sampled twice | VERIFIED (mechanism) |
| EVAL-02 | `test_eval_02_03_frozen_universe_and_verdicts` | Items are `fact` and `signal` kinds. A hypothesis is excluded. Citations carry no excerpt. 0 accounts without claims. The stored fingerprint equals the reported one, and adding a fact changes it | VERIFIED |
| EVAL-03 | Same | A usable fact accepts `supported` (200). A fake "software_in_use: Excel" fact is recorded `unsupported` | VERIFIED |
| EVAL-04 | `test_eval_04_expired_contradicted_and_metadata_only…` | Metadata-only is `unauditable`, and `supported` gives 409 "unauditable". A conflicting signal is `contradicted`, and `supported` gives 409. A source expiring before finalization lowers the numerator below the count of supported verdicts. The result is FAILED with still-displayed failures counted | VERIFIED |
| EVAL-05 | unit `test_evaluation_metric.py` (10); `test_eval_05_06_synthetic_math…` | 18/20 = 0.90 passes, while 17/20, 26/30, 0/0 and displayed failures fail; 29/29 insufficient and synthetic are BLOCKED. DB: synthetic corpus of 30 (20 facts, 10 zero-fact accounts): numerator 18, denominator 20, ratio 0.9, **BLOCKED** | VERIFIED |
| EVAL-06 | `test_eval_05_06_…`, `test_eval_06_real_corpus_mechanism_fails_then_passes_after_remediation` | Remediation creates 2 links. The corrected facts are `hypothesis` with a reason citing the evaluation. The baseline keeps both `unsupported` verdicts. The P3.2 brief shows `needs_reassessment: true`. The post-remediation run uses the same accounts: 18/18 with 0 displayed failures (still BLOCKED because synthetic). Mechanism corpus: baseline 28/30 FAILED ("still displayed"), then remediation, then a post-run 28/28 **PASSED**, which opens the gate (pointing to the post run). The baseline still reads FAILED | VERIFIED (mechanism) |
| EVAL-07 | — | **NOT-RUN / BLOCKED.** There are no 30 real, policy-permitted Lahore school accounts (P2.2 LIVE-10 and P3.1 live research are BLOCKED) and no authorized human reviewer has adjudicated. **No production evidence-accuracy figure exists.** The production gate is CLOSED in every real environment | **BLOCKED** |
| EVAL-08 | `test_eval_08_replay_concurrency_and_interrupted_finalization` | Replaying a create returns the same run; the same key with a different seed gives 409. Finalizing with pending items gives 409 "incomplete", with state INCOMPLETE and nothing finalized. Two racing verdicts: `[200, 409]`. A finalize replay returns the same `finalized_at`. A verdict after finalization gives 409. `UPDATE evidence_eval_verdicts` raises "append-only". The duplicate campus is excluded (EVAL-01) | VERIFIED |
| EVAL-09 | `test_eval_09_permissions_scope_injection_redaction_and_no_sends` | Anonymous 401; observer create or verdict 403 (read 200); missing CSRF 403. Another organization: run and verdict 404. Injection text is an unreviewed item and data only. The report contains no emails or excerpts. `allow_synthetic` in production is refused. **The outbox count is unchanged; there are no sends** | VERIFIED |
| EVAL-10 | e2e `verify-evidence.spec.ts` (3); `bash scripts/check.sh` | The operator opens Evidence quality: gate CLOSED. Starting a run including synthetic accounts shows SYNTHETIC_CORPUS, BLOCKED. The operator reviews every claim, recording "unverifiable" when the server refuses "supported", and finalizes: "BLOCKED — corpus is synthetic_corpus", "Supported n/m; failed claims still displayed: ≥1". Withdrawing the failed contact fact shows "withdrawn as fact (correction recorded)"; the gate stays CLOSED. The observer has no controls. Everything persists after restart. All P3.1–P3.3 suites pass | VERIFIED (UI path, synthetic) |

### Gate commands

| Command | Exit | Result |
|---|---|---|
| `bash scripts/check.sh` at `599608e` | 0 | 16/16 PASS. Integration **335** (+8); unit + contract **313** (+11); web 2; **e2e 20 + 6** |
| `./scripts/test-integration.sh tests/integration/test_evaluation.py` ×2 | 0 | 8 passed each time |
| Dev: `alembic upgrade head` (`0012 -> 0013`), smoke | 0 | All smoke checks passed |

### Defects found and fixed during verification

**Code:** the 90% check now uses integer arithmetic.

**Test design errors** (no gate semantics changed):
- an "unsourced" helper attached a source;
- a metadata-only first-party source still counts as real provenance;
- two finalizations tied on the fixed clock;
- the E2E expected INCOMPLETE where a synthetic corpus is (correctly) BLOCKED from the start.

### Mutation checks (committed first; restored with `git checkout`; tree clean)

| Mutation | Caught by |
|---|---|
| Synthetic counted as real | 2 |
| 29 real accounts accepted | 1 |
| 0/0 passes | 2 |
| `supported` allowed on any evidence | 1 |
| Displayed failures ignored | 3 |
| Denominator limited to supported items | 3 |
| Gate opens on any run | 2 |
| Duplicate campus allowed | 2 |
| Finalize with pending items | 1 |

### Self-review

- **Metric gaming:**
  - the denominator is every frozen item;
  - failures are never dropped from the baseline;
  - lapsed evidence is re-checked at finalization;
  - synthetic and insufficient corpora cannot pass.
- **Privacy and rights:** no excerpts in items or the report; reviewer ids only.
- **Tamperability:** verdicts and remediations are append-only; results are only written at finalization.
- **Invalidation:** corrections change the P3.2/P3.3 digests.
- **Known limit:** the "real provenance" heuristic trusts non-fixture providers. A real audit must also have the reviewer confirm each school exists, which the verdicts capture.

### Rollback

- **Stop:** stop creating evaluations; the gate is fail-closed.
- **Keep:** history is retained.
- **Revert code:** revert `f730d46` and `599608e`.
- **Schema:** downgrade 0013 only on a disposable database.

### VERDICT: IMPLEMENTATION VERIFIED (EVAL-01…06, 08…10); **EVAL-07 BLOCKED**, so the production quality gate is CLOSED

**Owner inputs required for EVAL-07:**
1. 30 real, rights-permitted Lahore school accounts, through the P2.2 live canary or owner seed lists with real sources.
2. A named human reviewer to adjudicate every displayed claim in `/quality`.

**P4.1 is UNBLOCKED as engineering, but must honour the CLOSED gate:** no real enrollment until EVAL-07 passes.
