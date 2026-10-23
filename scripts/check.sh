#!/usr/bin/env bash
# Canonical validation: the same command runs locally and in CI (P0.3).
# Runs every step even after a failure, prints a summary, and exits non-zero
# if any step failed.
#   bash scripts/check.sh                   # everything
#   bash scripts/check.sh --no-integration  # skip the Docker integration suite (reported as NOT RUN)
set -u

cd "$(dirname "$0")/.." || exit 2
root=$(pwd -P)

run_integration=1
for arg in "$@"; do
  case "$arg" in
    --no-integration) run_integration=0 ;;
    *) echo "usage: $0 [--no-integration]"; exit 2 ;;
  esac
done

results=()
failed=0
step() { # step <name> <command...>
  local name=$1
  shift
  printf '\n==> %s\n' "$name"
  local started=$SECONDS
  "$@"
  local status=$?
  local took="$((SECONDS - started))s"
  if [ "$status" -eq 0 ]; then
    results+=("PASS     $name ($took)")
  else
    results+=("FAIL($status)  $name ($took)")
    failed=1
  fi
}

api() { (cd "$root/apps/api" && "$@"); }
web() { (cd "$root/apps/web" && "$@"); }

step "repo: verify-setup" bash scripts/verify-setup.sh
step "repo: verify-setup tests" bash scripts/verify-setup.test.sh
step "repo: shellcheck" shellcheck scripts/*.sh
step "repo: compose config" env HERMECIOUS_ENV=test HERMECIOUS_ALLOWED_ORIGINS=http://localhost:3000 POSTGRES_USER=check POSTGRES_PASSWORD=check POSTGRES_DB=check_test \
  docker compose --env-file /dev/null --profile test config --quiet

step "api: install (locked)" api uv sync --locked --quiet
step "api: ruff check" api uv run --locked ruff check .
step "api: ruff format" api uv run --locked ruff format --check .
step "api: mypy" api uv run --locked mypy
step "api: unit + contract tests" api uv run --locked pytest -q -p no:cacheprovider tests/unit tests/contracts

step "web: install (locked)" web npm ci --no-audit --no-fund
step "web: lint" web npm run lint
step "web: typecheck" web npm run typecheck
step "web: test" web npm test
step "web: build" web env NEXT_TELEMETRY_DISABLED=1 npm run build

if [ "$run_integration" -eq 1 ]; then
  step "api: integration tests (disposable stack)" bash scripts/test-integration.sh
else
  results+=("NOT RUN  api: integration tests (disposable stack)")
fi

printf '\n==> Summary\n'
printf '  %s\n' "${results[@]}"
if [ "$failed" -ne 0 ]; then
  printf '\nCHECKS FAILED\n'
  exit 1
fi
printf '\nAll checks passed\n'
