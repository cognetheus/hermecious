#!/usr/bin/env bash
# Browser end-to-end tests (Playwright) against a disposable full stack (P1.4).
# Each run: its own Compose project ("hermecious-e2e-*"), free loopback ports,
# fresh volume, random password, synthetic users seeded via the bootstrap
# *function* (never the interactive CLI); runs the specs, restarts api+web,
# re-checks persistence, then removes only this project and its volume.
# Exit codes: Playwright's exit code, or 2 if the run cannot start.
set -u

cd "$(dirname "$0")/.." || exit 2
root=$(pwd -P)
for tool in docker openssl python3 npx; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR $tool is required"; exit 2; }
done
docker info >/dev/null 2>&1 || { echo "ERROR Docker daemon is not reachable"; exit 2; }

project="hermecious-e2e-$(date +%s)-$$"
case "$project" in
  hermecious-e2e-*) ;;
  *) echo "ERROR refusing to use project $project"; exit 2 ;;
esac
free_port() { python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'; }
api_port=$(free_port)
web_port=$(free_port)
work=$(mktemp -d "${TMPDIR:-/tmp}/hermecious-e2e.XXXXXX") || exit 2
cat >"$work/e2e.env" <<EOF
HERMECIOUS_ENV=test
HERMECIOUS_LOG_LEVEL=INFO
HERMECIOUS_ALLOWED_ORIGINS=http://localhost:$web_port
HERMECIOUS_SESSION_COOKIE_SECURE=false
POSTGRES_USER=hermecious
POSTGRES_DB=hermecious_e2e
POSTGRES_PASSWORD=$(openssl rand -hex 24)
HERMECIOUS_CONTACT_HMAC_SECRETS=e2e:$(openssl rand -hex 32)
HERMECIOUS_API_PORT=$api_port
HERMECIOUS_WEB_PORT=$web_port
EOF
chmod 600 "$work/e2e.env"
E2E_RUN_ID="r$(date +%s)"
export E2E_RUN_ID
E2E_PASSWORD=$(openssl rand -hex 16)
export E2E_PASSWORD
export E2E_BASE_URL="http://localhost:$web_port"
compose() { docker compose --env-file "$work/e2e.env" -p "$project" "$@"; }

# shellcheck disable=SC2329  # invoked via the EXIT trap below
cleanup() {
  compose down -v --remove-orphans >/dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT

wait_http() { # wait_http <url> <seconds>
  local deadline=$((SECONDS + $2))
  until [ "$(curl -s -o /dev/null -w '%{http_code}' "$1")" = 200 ]; do
    [ $SECONDS -ge $deadline ] && return 1
    sleep 2
  done
}

echo "E2E project: $project (web $E2E_BASE_URL)"
# Migrate before the worker starts: it stays unhealthy (by design) until the schema exists.
compose build >/dev/null 2>&1 || { echo "ERROR build failed"; exit 2; }
compose up -d --wait postgres redis >/dev/null 2>&1 || { echo "ERROR postgres/redis did not become healthy"; exit 2; }
compose run --rm --no-deps api python -m alembic upgrade head >/dev/null 2>&1 || { echo "ERROR migrations failed"; exit 2; }
compose up -d --wait >/dev/null 2>&1 || { echo "ERROR stack did not become healthy"; compose ps; exit 2; }
compose run --rm --no-deps -T -e E2E_RUN_ID -e E2E_PASSWORD api python - <<'PY' || { echo "ERROR seeding failed"; exit 2; }
import os

from app.auth import passwords
from app.auth.bootstrap import bootstrap_owner
from app.auth.models import Role, User
from app.core.clock import SystemClock
from app.core.settings import load_settings
from app.persistence.db import make_engine, make_session_factory

run, password, clock = os.environ["E2E_RUN_ID"], os.environ["E2E_PASSWORD"], SystemClock()
factory = make_session_factory(make_engine(str(load_settings().database_url)))
with factory() as db:
    owner = bootstrap_owner(
        db, organization_name="E2E School Ops", email=f"owner-{run}@e2e.example",
        password=password, display_name="E2E Owner", clock=clock,
    )
    for role in (Role.OPERATOR, Role.OBSERVER):
        now = clock.now()
        db.add(User(
            organization_id=owner.organization_id, email_canonical=f"{role.value}-{run}@e2e.example",
            display_name=f"E2E {role.value}", password_hash=passwords.hash_password(password),
            role=role, active=True, created_at=now, updated_at=now,
        ))
    db.commit()
print("seeded synthetic users")
PY

cd "$root/apps/web" || exit 2
npx playwright install chromium >/dev/null 2>&1 || { echo "ERROR could not install Chromium for Playwright"; exit 2; }
npx playwright test --grep-invert @after-restart
status=$?

echo "Restarting api and web (volumes kept) for the persistence check"
compose restart api web >/dev/null 2>&1
if ! wait_http "http://127.0.0.1:$api_port/health/live" 90 || ! wait_http "$E2E_BASE_URL/health/live" 90; then
  echo "ERROR stack did not come back after restart"
  exit 1
fi
npx playwright test --grep @after-restart --project desktop
after=$?
[ "$status" -ne 0 ] && exit "$status"
exit "$after"
