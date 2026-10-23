# ADR-010: Identity substrate in P1.1 and server-side opaque sessions

- **Status:** Accepted. The Batch 02 §0.2 sequencing correction and §P1.1 requirements direct this; implemented in P1.1.
- **Date:** 2026-10-23
- **Source:** `docs/phases/HERMECIOUS_BATCH_02_P1.1-P1.3.md` §0.2, §P1.1; blueprint §2 and §4 (P1.1, P1.2)

## Context

The blueprint lists `organizations` and `users` under P1.2 but authentication under P1.1. Authentication needs durable identity, and in-memory or throwaway auth is not allowed.

## Decision

### 1. Sequencing correction

- **P1.1 owns** migration `0002` with `organizations`, `users` and `auth_sessions`, plus the owner bootstrap.
- **P1.2 reuses these tables unchanged** and adds the account, source and fact tables. **P1.3** adds offers. No later subphase re-creates organizations or users or re-platforms sessions.

### 2. Session scheme: opaque, server-side, hashed at rest

- The cookie value is `<session_id>.<verifier>`. `session_id` is the row's UUID (32 hex characters), a lookup key that proves nothing by itself. `verifier` is 32 random bytes from `secrets` (256 bits), base64url-encoded.
- The database stores only `verifier_hash = sha256(verifier)` (64 hex characters) and compares it with `hmac.compare_digest`. A database leak does not yield usable cookies.
- **Postgres is the only authority.** There are no JWTs, no signed role claims, nothing in `localStorage`, and no session state in Redis. Role, organization and active status are read from the database on every request.
- **Lifetimes:** idle 8h and absolute 24h by default, validated configuration in the `Settings` component. Expiry is checked against the injected UTC `Clock`. `last_seen_at` and the idle extension are written at most every 5 minutes, and never past the absolute expiry.
- **Rotation:** every login issues a new session and revokes any session presented with the login request (fixation defence). A session issued before a user's `credentials_changed_at` is rejected. Logout sets `revoked_at` immediately.
- **Cookies:** production uses `__Host-hermecious_session` with `Secure; HttpOnly; Path=/; SameSite=Lax` and no `Domain`. Outside production, `hermecious_dev_session` without `Secure` is allowed for loopback HTTP. Production settings validation rejects insecure cookies, non-HTTPS origins and wildcard origins.

### 3. CSRF

- For every cookie-authenticated unsafe method (`POST`/`PUT`/`PATCH`/`DELETE`), both checks below must pass **before** any database write. `SameSite` is defence in depth, not proof.
  1. `Origin` (or, if absent, the `Referer`'s origin) must exactly match a configured allowed origin. If both are missing, or `Origin: null`, the request is refused.
  2. `X-CSRF-Token` must equal `base64url(HMAC-SHA256(key=verifier, "hermecious-csrf-v1"))`. The token is bound to the session secret, changes when the session rotates, and reveals nothing about the verifier. It is returned by login and `GET /api/v1/auth/csrf`, and the web app keeps it in memory only.
- **Login CSRF:** login requires an allowed `Origin`/`Referer` and `Content-Type: application/json`. A cross-site page cannot send that without a CORS preflight, and the API enables no CORS at all.

### 4. Login abuse controls

- Redis fixed 15-minute windows: at most 5 failed attempts per canonical email (keyed by a SHA-256 hash, never the address) and 30 attempts per client IP. A limited request gets 429 `RATE_LIMITED` with `Retry-After` and no password check.
- **If Redis is unavailable, login fails closed** with 503 `DEPENDENCY_UNAVAILABLE`, so an outage cannot be used for unlimited guessing. Existing sessions keep working, because they live in Postgres.
- Unknown email, wrong password, disabled user and suspended organization all return the same 401 body. Unknown emails still run an Argon2id verification against a fixed dummy hash, to keep timing uniform.
- The client IP is the direct peer address. Proxy headers are not trusted (`proxy_headers=False`) until a trusted reverse proxy exists (P11).

### 5. Authorization

- Every `/api/v1` route is authenticated by default. The public allowlist is `/api/v1/auth/login`, plus the non-API `/health/*` probes, and a contract test enforces it.
- The roles `owner`, `operator` and `observer` map to capabilities. A route can widen its allowed roles explicitly with `allow_roles(...)`. Any unsafe-method route that does not do so is **owner-only**. Organization scope always comes from the session's user row, never from the request.

### 6. Passwords

Argon2id (`argon2-cffi`) with t=3, m=64 MiB, p=1, above the OWASP minimum of m=19 MiB, t=2, p=1. Verification takes about 107 ms on the development machine. Hashes are upgraded on login when the parameters change. Passwords must be 12–256 characters. The owner is created only through an interactive TTY prompt, with no password argument and no default credential.

## Consequences

- Every authenticated request reads the session, user and organization rows (one indexed join) and writes at most once per 5 minutes.
- Revocation and role changes take effect on the next request.
- The rate-limit state is lost on a Redis restart. That is accepted: windows are short, and a Redis outage fails closed.

## Rollback

`alembic downgrade 0001` on a disposable database. In a data-bearing environment, take a backup and review live users and sessions before any downgrade. Never revert to anonymous access.
