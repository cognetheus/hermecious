# Jobs runbook

Contract: [job-outbox.md](../contracts/job-outbox.md). All job state lives in Postgres, so the database is the place to look.

## Health at a glance

```sh
docker compose ps worker                                          # healthy = loop heartbeat + Postgres reachable
docker compose logs worker --no-log-prefix | grep jobs.metrics | tail -1
```

`jobs.metrics` carries `pending`, `running`, `retry_wait`, `succeeded`, `dead`, `oldest_due_seconds` and `undispatched_events`. Owners can also call `GET /api/v1/ops/jobs`.

## Common situations

| Symptom | Meaning | Action |
|---|---|---|
| `oldest_due_seconds` keeps growing | No worker is claiming | Check `docker compose ps worker` and its logs. Start the worker; pending jobs are picked up by polling |
| `undispatched_events` keeps growing | The notification sink (Redis) is down | Jobs still run via polling; only wake-ups are slower. Restore Redis; events dispatch on their next backoff |
| Worker `unhealthy` | The loop is stalled or Postgres is unreachable | Run `docker compose exec worker python -m app.workers.healthcheck` to see which. Logs show `worker.database_unavailable` or `worker.schema_not_ready` |
| `worker.schema_not_ready` | Migrations not applied | `docker compose run --rm --no-deps api python -m alembic upgrade head` |
| `dead` jobs | Permanent failure or retries exhausted | Inspect `last_error_class` (see below). Fix the cause, then enqueue a **new** job with a new idempotency key. Dead rows are history; never delete them |

## Inspect (read-only)

```sh
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  SELECT status, count(*) FROM jobs GROUP BY status;
  SELECT id, job_type, attempts, last_error_class, finished_at FROM jobs WHERE status = '\''dead'\'' ORDER BY finished_at DESC LIMIT 20;
  SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL;"'
```

Payloads are typed and contain no secrets or contact data, but avoid exporting them all the same.

## Error classes

`transient_error`, `upstream_timeout`, `database_unavailable` and `unexpected_error` are retried up to `max_attempts`. `permanent_error`, `invalid_payload` and handler classes such as `account_not_found` go dead immediately. `retries_exhausted` and `lease_expired` mean the retry budget ran out. Messages and tracebacks are never stored, only the class. Look up the worker logs by the job's correlation ID: `docker compose logs worker | grep <request_id>`.

## Do not

- Do not `docker compose down -v`: it deletes the queue together with all data.
- Do not `UPDATE jobs` by hand to re-run work. Enqueue a new job. Fenced leases make hand edits unsafe for running jobs.
- Do not assume a dispatched outbox event means the job ran: `dispatched_at` is notification only.
- Do not add a handler that calls an external service without provider-side idempotency and reconciliation (P5).

## Rolling back a worker release

Revert the worker image; rows stay. Unknown job types or versions are refused at execution (`invalid_payload`, dead), so nothing runs with the wrong schema. Re-enqueue after rolling forward.
