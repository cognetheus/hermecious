# Authentication and sessions

Design: [ADR-010](../adr/ADR-010-identity-and-server-sessions.md). The API enforces everything. The web app's redirect to `/login` is only a convenience.

## Create the first owner (once per deployment)

```sh
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose run --rm -it --no-deps api python -m app.auth.bootstrap \
  --organization "CoderzHunt" --email you@example.com --display-name "Your Name"
```

- You are prompted for the password twice (12–256 characters, not equal to the email). There is no `--password` flag, and the command refuses to run without an interactive terminal (`-it`).
- Prints only `bootstrap: organization and owner created`, or `bootstrap: refused: <reason>`. It never prints the email, password or hash.
- **Exactly once:** if any organization exists, it refuses. Concurrent runs are serialized by a Postgres advisory lock.
- No other user-management UI, invitations, password reset or OAuth exist yet. Additional users need a later subphase.

## Signing in

Open the web app (default `http://localhost:3000`) and sign in. The browser only talks to the web origin, and Next rewrites `/api/v1/*` to the API inside the Compose network, so the session cookie is first-party and no CORS is involved.

## Configuration

| Setting | Development (loopback HTTP) | Production |
|---|---|---|
| `HERMECIOUS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` (must match the URL in your browser, including the port) | `https://<your host>` only; HTTP origins are rejected at startup |
| `HERMECIOUS_SESSION_COOKIE_SECURE` | `false` → cookie `hermecious_dev_session` | `true` (required) → cookie `__Host-hermecious_session` with `Secure`, served only over HTTPS |
| `HERMECIOUS_SESSION_IDLE_MINUTES` / `_ABSOLUTE_MINUTES` | 480 / 1440 (defaults) | same unless reviewed; idle must be ≤ absolute |

Origins must be exact (`scheme://host[:port]`). Wildcards, paths, credentials and trailing slashes are rejected in every environment. The API never enables CORS.

## Session behaviour

| Event | Effect |
|---|---|
| Login | New opaque session; any session presented with the request is revoked (fixation defence) |
| Each request | Session, user and organization re-read from Postgres. Idle window slides, written at most every 5 min, never past the absolute expiry |
| Idle 8h / absolute 24h reached | 401; the cookie is cleared |
| Logout | Revoked immediately; replaying the old cookie gives 401 |
| User disabled / org suspended | Next request returns 401 and the session is revoked |
| `credentials_changed_at` set | Older sessions are rejected |
| API or Redis restart | Sessions survive (Postgres-backed) |

`GET /api/v1/auth/session-status` is intentionally **not** implemented, because `GET /api/v1/auth/me` already answers whether the session is valid.

## Calling mutating endpoints (frontend developers)

Every cookie-authenticated `POST`/`PUT`/`PATCH`/`DELETE` needs both of these:
1. **Origin:** browsers send it automatically for same-origin `fetch`. Requests without `Origin` and `Referer` are refused.
2. **`X-CSRF-Token`:** take it from the login response, or from `GET /api/v1/auth/csrf`. Keep it in memory only (never `localStorage`). It changes on every new login.

A failure gives 403 `FORBIDDEN`, and nothing is changed.

## Roles

| Role | Capabilities |
|---|---|
| `owner` | read, mutate, publish, administer |
| `operator` | read, mutate (only on routes that explicitly allow operators) |
| `observer` | read |

Unsafe-method routes are **owner-only** unless the route declares `@allow_roles(...)`. A route can also require a capability with `Depends(require_capability(Capability.PUBLISH))`. Organization scope always comes from the session, never from request parameters.

## Login limits and failure modes

- **5 failed logins per email in a 15-minute window, and 30 attempts per client IP:** further attempts get 429 `RATE_LIMITED` with `Retry-After`.
- **Redis down:** logins fail closed with 503 `DEPENDENCY_UNAVAILABLE`. Existing sessions keep working. Rate-limit counters reset when Redis restarts.
- **Postgres down:** authenticated requests return 503 `DEPENDENCY_UNAVAILABLE`.
- Wrong password, unknown email, disabled user and suspended organization all give the same 401 `Invalid email or password`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Login returns 403 | The browser origin is not in `HERMECIOUS_ALLOWED_ORIGINS` (check host *and* port), or the request is not `application/json` |
| Mutations return 403 | Missing or stale `X-CSRF-Token` (fetch a fresh one from `/api/v1/auth/csrf`), or a disallowed origin |
| `refusing to start: ... HERMECIOUS_SESSION_COOKIE_SECURE` | Production requires `true` (and HTTPS) |
| Locked out after failed attempts | Wait for `Retry-After` (at most 15 min) |

Events to grep for (no personal data is logged): `auth.login_succeeded`, `auth.login_denied`, `auth.logout`, `auth.session_rejected`, `auth.session_revoked`, `auth.csrf_rejected`, `auth.forbidden`.

## Rollback

On a disposable database: `alembic downgrade 0001`. Where data exists: back up, review live users and sessions, and prefer a forward fix. A code revert must never re-open private routes to anonymous access.
