# Testing and validation

## One command

```sh
bash scripts/check.sh                   # everything; CI runs exactly this
bash scripts/check.sh --no-integration  # skip Docker integration tests (summary says NOT RUN)
```

`check.sh` runs every step even after a failure, prints a PASS/FAIL summary and exits non-zero if any step failed. Never treat a run with `NOT RUN` steps as a full pass.

| Step | Command (run by `check.sh`) |
|---|---|
| Repo baseline | `scripts/verify-setup.sh`, `scripts/verify-setup.test.sh`, `shellcheck scripts/*.sh`, `docker compose config` |
| API install | `uv sync --locked` (fails if `uv.lock` is stale) |
| API lint, format and types | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (strict) |
| API unit and contract tests | `uv run pytest tests/unit tests/contracts` (no database) |
| Web install | `npm ci` (fails if `package-lock.json` is stale) |
| Web lint, types, tests and build | `npm run lint`, `npm run typecheck` (`next typegen` + `tsc`), `npm test` (Vitest), `npm run build` |
| API integration tests | `scripts/test-integration.sh` |

Prerequisites: `uv` 0.7.9, Node 22, Docker with Compose v2, `shellcheck`, `openssl`. CI (`.github/workflows/ci.yml`) installs the same versions and runs `bash scripts/check.sh`.

## Test layout

| Path | What | Needs |
|---|---|---|
| `apps/api/tests/unit/` | Pure logic: settings, clock, worker heartbeat | nothing |
| `apps/api/tests/contracts/` | HTTP and schema contracts: health envelope, Alembic owns the schema, linear and reversible migration chain | nothing |
| `apps/api/tests/integration/` | Real Postgres and Redis: migrations, readiness, worker registration | the disposable stack |
| `apps/web/tests/` | Web route contracts (Vitest, node environment) | nothing |

API tests live beside the Python project. A repo-root `tests/` stays reserved for cross-app suites (E2E and evals, from P7 and P10).

## Integration tests and the disposable stack

`scripts/test-integration.sh` creates a throwaway Compose project (`hermecious-test-<time>-<pid>`) from the same `compose.yaml`, using the `test` profile's `api-test` service. Each run gets:
- a fresh random Postgres password and the database `hermecious_test`. The developer `.env` is never read (`--env-file /dev/null`).
- its own network and volume, both removed on exit (`down -v` on that project only).

Concurrent runs do not interfere. Arguments are passed to pytest, for example `bash scripts/test-integration.sh -k migrations -x`.

**Fail-closed guard:** the integration suite aborts (exit 2) before touching any database unless `HERMECIOUS_ENV=test` and `DATABASE_URL` names a database ending in `_test`.

Migration tests create a separate scratch database per test (`hermecious_scratch_<hex>_test`), run Alembic against it in a subprocess, and drop it afterwards.

## Migrations

- Alembic owns the schema. Application code never calls `create_all()`, and a contract test enforces this.
- Revision IDs are sequential (`0001`, `0002`, …), created with `uv run alembic revision -m "<message>" --rev-id 000N` and reviewed by hand. Autogenerate output is never applied unread.
- Every revision must define `downgrade()` and the chain must stay linear (contract tests).
- `alembic/env.py` reads only the validated `DATABASE_URL`. A missing or invalid URL stops it with `refusing to run: ... DATABASE_URL`, with no fallback.
- To apply migrations to the local stack: `docker compose run --rm --no-deps api python -m alembic upgrade head`.

## Time

Code that needs "now" takes a `Clock` (`app/core/clock.py`). Tests use the `clock` fixture: a `FixedClock` at `2026-10-23T07:00Z`, which is 12:00 in `Asia/Karachi` (`BUSINESS_TZ`). Instants are always timezone-aware UTC (ruff `DTZ` rules), so results do not depend on the host timezone. Never `sleep` to make time pass in a test; use `clock.advance(...)`.

## Writing tests

- pytest runs with `--strict-markers --strict-config` and turns warnings into errors.
- Never put secrets in assertion expressions: pytest prints the values. Pass database URLs as SQLAlchemy `URL` objects, whose repr masks the password.
- Do not suppress or skip a failing test to make CI green.
