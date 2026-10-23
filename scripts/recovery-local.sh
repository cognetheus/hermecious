#!/usr/bin/env bash
# Failure/recovery checks for the local Compose stack (P0.2 A3-A5).
# DISRUPTIVE: stops Postgres and Redis, then recreates all containers with
# `docker compose down` (WITHOUT -v; named volumes are kept). Uses a separate
# throwaway database for the persistence check and drops it afterwards.
# Run against a healthy stack: docker compose up --build -d
# Exit codes: 0 all checks passed, 1 a check failed, 2 cannot run.
set -u

cd "$(dirname "$0")/.." || exit 2
command -v docker >/dev/null 2>&1 || { echo "ERROR docker is required"; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR curl is required"; exit 2; }
docker info >/dev/null 2>&1 || { echo "ERROR Docker daemon is not reachable"; exit 2; }

failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
step() { printf '\n== %s\n' "$1"; }

api_addr=$(docker compose port api 8000 2>/dev/null) || { echo "ERROR api is not running"; exit 2; }

status_of() { curl -s -o /dev/null --max-time 10 -w '%{http_code}' "http://$api_addr$1"; }
body_of() { curl -s --max-time 10 "http://$api_addr$1"; }
worker_health() { docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q worker)"; }

# wait_until <timeout-seconds> <command...>: polls every 2s until the command succeeds.
wait_until() {
  local deadline=$((SECONDS + $1))
  shift
  until "$@"; do
    [ $SECONDS -ge $deadline ] && return 1
    sleep 2
  done
}
ready_is() { [ "$(status_of /health/ready)" = "$1" ]; }
worker_is() { [ "$(worker_health)" = "$1" ]; }

step "A3: Postgres outage"
docker compose stop postgres >/dev/null 2>&1
if wait_until 30 ready_is 503; then
  pass "ready -> 503 $(body_of /health/ready)"
else
  fail "ready did not become 503 with Postgres stopped"
fi
if [ "$(status_of /health/live)" = 200 ]; then pass "live stays 200 during Postgres outage"; else fail "live not 200 during Postgres outage"; fi
docker compose start postgres >/dev/null 2>&1
if wait_until 60 ready_is 200; then pass "ready recovers to 200 after Postgres restart"; else fail "ready did not recover after Postgres restart"; fi

step "A4: Redis outage and worker recovery"
worker_restarts_before=$(docker inspect --format '{{.RestartCount}}' "$(docker compose ps -q worker)")
docker compose stop redis >/dev/null 2>&1
if wait_until 30 ready_is 503; then
  pass "ready -> 503 $(body_of /health/ready)"
else
  fail "ready did not become 503 with Redis stopped"
fi
if docker compose exec -T worker python -m app.workers.healthcheck >/dev/null 2>&1; then
  fail "worker health check passed while Redis was down"
else
  pass "worker health check fails while Redis is down"
fi
outage_started=$SECONDS
if wait_until 90 worker_is unhealthy; then pass "worker container reported unhealthy after $((SECONDS - outage_started))s"; else fail "worker never reported unhealthy (now: $(worker_health))"; fi
docker compose start redis >/dev/null 2>&1
redis_restarted=$SECONDS
if wait_until 60 ready_is 200; then pass "ready recovers to 200 after Redis restart"; else fail "ready did not recover after Redis restart"; fi
if wait_until 150 worker_is healthy; then pass "worker healthy again $((SECONDS - redis_restarted))s after Redis restart"; else fail "worker did not recover (now: $(worker_health))"; fi
worker_restarts_after=$(docker inspect --format '{{.RestartCount}}' "$(docker compose ps -q worker)")
pass "worker container restarts during outage: $((worker_restarts_after - worker_restarts_before))"

step "A5: Postgres data survives a full stack restart"
token="p02-$(date +%s)-$$"
psql_in() { docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -qtA -U "$POSTGRES_USER" -d "$0" -c "$1"' "$1" "$2"; }
if psql_in postgres "DROP DATABASE IF EXISTS hermecious_p02_smoke" >/dev/null 2>&1 &&
  psql_in postgres "CREATE DATABASE hermecious_p02_smoke" >/dev/null &&
  psql_in hermecious_p02_smoke "CREATE TABLE survival (token text NOT NULL); INSERT INTO survival VALUES ('$token')" >/dev/null; then
  pass "test row written to throwaway database"
else
  fail "could not write the test row"
fi
docker compose down >/dev/null 2>&1
docker compose up -d >/dev/null 2>&1
if wait_until 120 ready_is 200; then pass "stack back up after down/up (volumes kept)"; else fail "stack did not become ready after down/up"; fi
found=$(psql_in hermecious_p02_smoke "SELECT token FROM survival" 2>/dev/null)
if [ "$found" = "$token" ]; then pass "test row survived restart"; else fail "test row missing after restart"; fi
if psql_in postgres "DROP DATABASE hermecious_p02_smoke" >/dev/null; then pass "throwaway database dropped"; else fail "could not drop throwaway database"; fi

if [ "$failures" -gt 0 ]; then
  printf '\n%d check(s) failed\n' "$failures"
  exit 1
fi
printf '\nAll recovery checks passed\n'
