#!/usr/bin/env bash
# Runs the API integration suite against a disposable Postgres + Redis (P0.3).
# Each run uses its own Compose project ("hermecious-test-*"), a fresh random
# password and a fresh volume, and never reads the developer .env. The project
# and its volume are removed on exit. Extra arguments go to pytest.
# Exit codes: pytest's exit code, or 2 if the run cannot start.
set -u

cd "$(dirname "$0")/.." || exit 2
command -v docker >/dev/null 2>&1 || { echo "ERROR docker is required"; exit 2; }
docker info >/dev/null 2>&1 || { echo "ERROR Docker daemon is not reachable"; exit 2; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR openssl is required"; exit 2; }

project="hermecious-test-$(date +%s)-$$"
case "$project" in
  hermecious-test-*) ;;
  *) echo "ERROR refusing to use project $project"; exit 2 ;;
esac

# Disposable credentials; --env-file /dev/null keeps the developer .env out.
export HERMECIOUS_ENV=test HERMECIOUS_ALLOWED_ORIGINS=http://localhost:3000 POSTGRES_USER=hermecious POSTGRES_DB=hermecious_test
POSTGRES_PASSWORD=$(openssl rand -hex 24)
HERMECIOUS_CONTACT_HMAC_SECRETS="test:$(openssl rand -hex 32)"
export POSTGRES_PASSWORD HERMECIOUS_CONTACT_HMAC_SECRETS
compose() { docker compose --env-file /dev/null -p "$project" --profile test "$@"; }

cleanup() {
  compose down -v --remove-orphans >/dev/null 2>&1
  # Drop the images this run built (named "<project>-<service>"), so disposable runs do not pile up.
  docker images -q --filter "reference=${project}-*" | xargs docker rmi -f >/dev/null 2>&1
}
trap cleanup EXIT

echo "Integration project: $project"
if [ "$#" -gt 0 ]; then
  compose run --rm --build api-test python -m pytest -q -p no:cacheprovider "$@"
else
  compose run --rm --build api-test
fi
