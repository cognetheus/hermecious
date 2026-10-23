# Local development stack

One canonical stack, defined in [`compose.yaml`](../../compose.yaml) at the repo root. Run every command from the repository root.

## Services

| Service | What it is | Host access | Container health check |
|---|---|---|---|
| `api` | FastAPI (`python -m app`) | `127.0.0.1:${HERMECIOUS_API_PORT:-8000}` | `GET /health/live` |
| `worker` | RQ worker (`python -m app.workers`, ADR-009) | none | this worker's own Redis heartbeat is fresh |
| `web` | Next.js standalone server | `127.0.0.1:${HERMECIOUS_WEB_PORT:-3000}` | `GET /health/live` (web server only) |
| `postgres` | PostgreSQL 18.6, system of record | none (internal network only) | `pg_isready` |
| `redis` | Redis 8.10, broker only, no persistence | none (internal network only) | `redis-cli ping` |

Postgres data lives in the named volume `hermecious_postgres-data`. Redis holds nothing durable by design, because Postgres is authoritative (ADR-009).

## Prerequisites

- Docker Engine with the Compose v2 plugin (`docker compose version`). Verified with Docker 28.3 and Compose 2.38.
- `git`, `bash`, `curl` and `openssl`.

## First-time setup

```sh
cp .env.example .env
chmod 600 .env
# Set a URL-safe Postgres password (the api and worker connection URL embeds it):
sed -i.bak "s/^POSTGRES_PASSWORD=$/POSTGRES_PASSWORD=$(openssl rand -hex 32)/" .env && rm .env.bak
bash scripts/verify-setup.sh
```

If `POSTGRES_PASSWORD` is empty, `docker compose` refuses to run with `required variable POSTGRES_PASSWORD is missing a value`.

## Everyday commands

| Task | Command |
|---|---|
| Build and start everything | `docker compose up --build -d` |
| Status and health | `docker compose ps` |
| Smoke test (read-only) | `bash scripts/smoke-local.sh` |
| Follow logs | `docker compose logs -f` (one service: `docker compose logs -f api`) |
| Restart one service | `docker compose restart worker` |
| Stop, keeping containers | `docker compose stop` |
| Stop and remove containers, **keeping data** | `docker compose down` |
| psql shell | `docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` |

## Health endpoints

| Endpoint | 200 | 503 |
|---|---|---|
| api `GET /health/live` | `{"status":"alive"}` whenever the process serves HTTP; dependencies are never checked | n/a |
| api `GET /health/ready` | `{"status":"ready","checks":{"postgres":"ok","redis":"ok"}}` | `{"status":"not_ready","checks":{...}}` with `unavailable` for each failing dependency |
| web `GET /health/live` | `{"status":"alive"}`: the web server is responsive. This is **not** a dependency check. | n/a |

Each readiness probe has a 2-second timeout. Responses never contain hosts, URLs, credentials or exception text. The API logs only the dependency name and the exception class.

## Failure and recovery checks

```sh
bash scripts/recovery-local.sh
```

**This disrupts the running stack.** It stops Postgres and then Redis, and asserts the expected readiness and worker-health changes. It then runs `docker compose down` and `docker compose up -d` (volumes are kept) and confirms that a row in a throwaway database `hermecious_p02_smoke` survives. It drops that database at the end.

What to expect:
- **Postgres or Redis down:** `/health/ready` returns 503 and `/health/live` stays 200. Recovery is automatic once the dependency returns.
- **Redis down:** the worker becomes `unhealthy` within about 30 seconds and recovers without a container restart (RQ reconnects with backoff, capped at 60 seconds).
- **Worker process crash:** `restart: unless-stopped` restarts it, and it registers under a fresh name.

## Troubleshooting

- **`bind: address already in use`:** another process holds the port. Set `HERMECIOUS_API_PORT` or `HERMECIOUS_WEB_PORT` in `.env` to a free port, then run `docker compose up -d`.
- **`refusing to start: missing or invalid settings: NAME`:** the api or worker received an empty or malformed `DATABASE_URL` or `REDIS_URL`. Compose builds both from `.env`, so check `POSTGRES_*` there. The message names the setting but never prints its value.
- **Worker `unhealthy`:** run `docker compose exec worker python -m app.workers.healthcheck`. It prints `not registered`, `broker unreachable (<ErrorClass>)` or `no fresh heartbeat`.
- **`Docker daemon is not reachable`:** start Docker Desktop or the Docker service.

## Destructive cleanup (deletes all local data)

> **Warning:** this permanently deletes the Postgres volume and every record in it. Never use it as a rollback step.

```sh
docker compose down -v
```
