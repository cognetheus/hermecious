#!/usr/bin/env bash
# Read-only smoke test for the running local Compose stack (P0.2).
# Checks: five healthy services, health endpoint contracts, and that only
# api/web publish ports, on 127.0.0.1 only. Start the stack first:
#   docker compose up --build -d
# Exit codes: 0 all checks passed, 1 a check failed, 2 cannot run.
set -u

cd "$(dirname "$0")/.." || exit 2
command -v docker >/dev/null 2>&1 || { echo "ERROR docker is required"; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR curl is required"; exit 2; }
docker info >/dev/null 2>&1 || { echo "ERROR Docker daemon is not reachable"; exit 2; }

failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

services="api postgres redis web worker"

# 1. All five services running and healthy (allow up to 120s to settle).
deadline=$((SECONDS + 120))
while :; do
  states=$(docker compose ps --format '{{.Service}}={{.State}}/{{.Health}}' 2>/dev/null | sort | tr '\n' ' ')
  expected=""
  for s in $services; do expected="$expected$s=running/healthy "; done
  [ "$states" = "$expected" ] && break
  [ $SECONDS -ge $deadline ] && break
  sleep 3
done
if [ "$states" = "$expected" ]; then
  pass "services healthy: $services"
else
  fail "services not all running/healthy: ${states:-none}"
fi

# 2. Published ports: api and web on 127.0.0.1 only; postgres and redis none.
for s in postgres redis; do
  if docker compose ps --format '{{.Ports}}' "$s" | grep -q -- '->'; then
    fail "$s publishes a host port"
  else
    pass "$s has no host port"
  fi
done
api_addr=$(docker compose port api 8000 2>/dev/null)
web_addr=$(docker compose port web 3000 2>/dev/null)
for pair in "api=$api_addr" "web=$web_addr"; do
  case "${pair#*=}" in
    127.0.0.1:*) pass "${pair%%=*} published on loopback only (${pair#*=})" ;;
    *) fail "${pair%%=*} published on unexpected address: ${pair#*=}" ;;
  esac
done

# 3. Endpoint contracts: exact status code and body.
probe() { # probe <label> <url> <status> <body>
  response=$(curl -s --max-time 5 -w '\n%{http_code}' "$2")
  body=${response%$'\n'*}
  status=${response##*$'\n'}
  if [ "$status" = "$3" ] && [ "$body" = "$4" ]; then
    pass "$1 -> $status $body"
  else
    fail "$1 -> expected $3 $4, got ${status:-no response} $body"
  fi
}
probe "api /health/live" "http://$api_addr/health/live" 200 '{"status":"alive"}'
probe "api /health/ready" "http://$api_addr/health/ready" 200 '{"status":"ready","checks":{"postgres":"ok","redis":"ok"}}'
probe "web /health/live" "http://$web_addr/health/live" 200 '{"status":"alive"}'

# 4. The worker's own heartbeat check, run directly.
if docker compose exec -T worker python -m app.workers.healthcheck >/dev/null 2>&1; then
  pass "worker heartbeat fresh"
else
  fail "worker heartbeat check failed"
fi

if [ "$failures" -gt 0 ]; then
  printf '\n%d check(s) failed\n' "$failures"
  exit 1
fi
printf '\nAll smoke checks passed\n'
