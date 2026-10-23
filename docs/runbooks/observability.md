# Observability: logs, request IDs and errors

## Log format

The API and the worker write one JSON object per line to stdout. This covers our own events and also uvicorn, RQ and Alembic messages.

```json
{"ts": "2026-10-23T07:00:00.123Z", "level": "info", "service": "api", "env": "development",
 "logger": "app.http", "event": "http.request", "request_id": "req_3af1…",
 "context": {"method": "GET", "path": "/health/live", "status": 200, "duration_ms": 0.8}}
```

| Field | Meaning |
|---|---|
| `ts` | UTC, millisecond precision |
| `level` | `debug` / `info` / `warning` / `error` / `critical` (`HERMECIOUS_LOG_LEVEL`; production rejects DEBUG) |
| `service`, `env` | `api` or `worker`; `HERMECIOUS_ENV` |
| `event` | Stable event name for our code (`http.request`, `job.finished`, …); scrubbed free text for third-party libraries |
| `request_id` | Correlation ID of the current request or job (absent outside one) |
| `context` | Allowlisted, redacted details |
| `error` | `class` and a scrubbed, truncated traceback, server-side only |

### Events emitted today

| Event | Where | Context |
|---|---|---|
| `app.starting` | API start | — |
| `config.invalid` | API or worker start, then exit 1 | `settings`: names only |
| `http.request` | Every HTTP request | `method`, `path` (no query string), `status`, `duration_ms`, `error_code` if any |
| `http.unhandled_exception` | Unhandled error (500) | `error` block |
| `http.dependency_unavailable` | Driver outage mapped to 503 | `error_class` |
| `health.dependency_unavailable` | Readiness probe failure | `dependency`, `error_class` |
| `job.started` / `job.finished` | Every RQ job | `job_id`, `job_type`, `queue`, `status`, `duration_ms` |

## Redaction rules (`app/core/logging.py`)

1. **Allowlist for context keys.** Only keys in `SAFE_CONTEXT_KEYS` keep their values. Any other key is logged as `"[REDACTED]"`, at every nesting level. Nesting is capped at 5 levels and lists at 50 items. To log a new field, add its key to the allowlist in a reviewed change.
2. **Every string is scrubbed**, including our messages, third-party messages, allowed context values and tracebacks. The scrubber removes:
   - credentials in URLs (`scheme://user:pass@`, including `redis://:pass@`)
   - bearer tokens
   - `password=` / `token:` / `api_key` / `cookie` / `session` style pairs
   - email addresses
   - Pakistani and international phone numbers
   
   Strings are truncated at 512 characters, and tracebacks at 4000.
3. **Never logged:** query strings (uvicorn access logs are disabled), request and response bodies, headers, cookies, job arguments (`log_job_description=False`) and `Settings` values. The `Settings` repr masks URLs.
4. **JSON encoding escapes newlines and quotes,** so a value can never start a forged log line.
5. **The formatter never raises.** An unformattable record becomes `{"event": "log.format_error"}`, and `logging.raiseExceptions = False` stops a broken sink from dumping records to stderr.

When adding logging, log a stable event name and put details in `extra={"context": {...}}` using allowlisted keys. Never interpolate user data into the message.

## Request IDs

- Every HTTP response carries `X-Request-ID`. The same value appears in that request's log lines and in its error envelope.
- A client-supplied `X-Request-ID` is kept only if it matches `[A-Za-z0-9][A-Za-z0-9._-]{7,63}`. Anything else (too long, newlines, quotes, markup) is replaced with a fresh `req_<32 hex>`.
- **Jobs:** `app.workers.tracing.enqueue()` stores the caller's request ID in job meta. The worker binds it, after validation, for exactly one job, or uses a fresh `job_<hex>` ID. It clears the context afterwards, even if the job fails.

**Tracing a problem:** take `X-Request-ID` from the response, or `request_id` from the error body, then run:

```sh
docker compose logs api worker --no-log-prefix | grep '"request_id": "req_…"'
```

## Error envelope (`app/core/errors.py`)

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Request could not be processed", "request_id": "req_…", "retryable": false}}
```

| Code | Status | Retryable | Raised by |
|---|---|---|---|
| `VALIDATION_ERROR` | 400, 422 (and other 4xx such as 405, keeping their status) | no | `InvalidRequest`, request validation, malformed JSON |
| `UNAUTHENTICATED` | 401 | no | `Unauthenticated` |
| `FORBIDDEN` | 403 | no | `Forbidden` |
| `NOT_FOUND` | 404 | no | `NotFound`, unknown routes |
| `CONFLICT` | 409 | no | `Conflict` |
| `RATE_LIMITED` | 429 | yes | `RateLimited` |
| `DEPENDENCY_UNAVAILABLE` | 503 | yes | `DependencyUnavailable`; any uncaught psycopg/SQLAlchemy operational or Redis connection error |
| `INTERNAL_ERROR` | 500 | no | any other unhandled exception |

Messages are fixed strings: either the defaults above or a developer-written message passed to an `AppError`. Never put user input or exception text in one. `HTTPException.detail` and pydantic error details are deliberately not returned, because they can echo submitted data.

`/health/ready` keeps its own status contract (P0.2). It is a probe, not an error.

## Known limitations

- Next.js (`web`) logs keep Next's own format. They hold no request IDs and no redaction beyond Next's defaults.
- If an exception happens after a response has started streaming, there is nothing left to wrap in an envelope. It is logged and the connection is closed.
- Scrubbing is pattern-based. Unusual secret formats in third-party free text could slip through, which is why our code never interpolates data into messages.
- `logging.raiseExceptions = False` means a failing log sink drops records silently.
