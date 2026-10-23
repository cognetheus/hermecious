#!/usr/bin/env bash
# Verifies the repository baseline on a fresh clone: required P0.1 documents
# exist and the mechanically checkable secrets rules hold
# (docs/runbooks/secrets.md). Never prints secret values.
# Exit codes: 0 all checks passed, 1 a check failed, 2 cannot run.
set -u

cd "$(dirname "$0")/.." || exit 2

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR git is required (see README.md prerequisites)"
  exit 2
fi
if [ "$(git rev-parse --show-toplevel 2>/dev/null)" != "$(pwd -P)" ]; then
  echo "ERROR not the root of a git work tree; clone the repository with git"
  exit 2
fi

failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# 1. Required P0.1 documents.
for f in README.md AGENTS.md EXECUTION_LEDGER.md \
  HERMECIOUS_EXECUTION_BLUEPRINT_v1.md .env.example .gitignore \
  docs/adr/ADR-001-modular-monolith-and-stack.md docs/runbooks/secrets.md; do
  if [ -f "$f" ]; then pass "present: $f"; else fail "missing: $f"; fi
done

# 2. .env.example declares names only: KEY=VALUE lines, no duplicates,
#    empty secret values, no credentials embedded in URLs.
secret_name='(PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY|ENCRYPTION_KEY)'
url_with_credentials='://[^/@[:space:]]*:[^/@[:space:]]*@'
if [ -f .env.example ]; then
  example_failures=$failures
  seen=' '
  n=0
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    case "$line" in '' | '#'*) continue ;; esac
    if ! printf '%s\n' "$line" | grep -Eq '^[A-Z][A-Z0-9_]*='; then
      fail ".env.example line $n is not KEY=VALUE"
      continue
    fi
    key=${line%%=*}
    value=${line#*=}
    case "$seen" in *" $key "*) fail ".env.example declares $key twice (line $n)" ;; esac
    seen="$seen$key "
    if printf '%s\n' "$key" | grep -Eq "$secret_name" && [ -n "$value" ]; then
      fail ".env.example secret $key must be empty (line $n)"
    fi
    if printf '%s\n' "$value" | grep -Eq "$url_with_credentials"; then
      fail ".env.example $key embeds credentials in a URL (line $n)"
    fi
  done <.env.example
  if [ "$failures" -eq "$example_failures" ]; then pass ".env.example holds no secret values"; fi
fi

# 3. Local env files are ignored; the template is not.
for p in .env .env.local .env.production; do
  if git check-ignore -q "$p"; then pass "git-ignored: $p"; else fail "not git-ignored: $p"; fi
done
if git check-ignore -q .env.example; then
  fail ".env.example must not be git-ignored"
else
  pass ".env.example is trackable"
fi

# 4. No env file other than the template is tracked.
tracked_env=$(git ls-files --cached | grep -E '(^|/)\.env(\.[^/]*)?$' | grep -vE '(^|/)\.env\.example$')
if [ -n "$tracked_env" ]; then
  fail "env files are tracked: $(printf '%s' "$tracked_env" | tr '\n' ' ')"
else
  pass "no env files tracked"
fi

# 5. No well-known credential formats in tracked or addable files.
#    Lists file names only, never the matching content.
credential_formats='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|xox[abprs]-[A-Za-z0-9-]{10,}|EAA[A-Za-z0-9]{60,}'
matches=$(git grep --untracked -lIE -e "$credential_formats")
case $? in
  0) fail "credential-like content in: $(printf '%s' "$matches" | tr '\n' ' ')" ;;
  1) pass "no credential-like content in tracked or addable files" ;;
  *) fail "credential scan could not run" ;;
esac

# 6. A local .env, if present, is readable by its owner only.
if [ -e .env ]; then
  if [ -n "$(find .env -prune \( -perm -040 -o -perm -004 \) -print)" ]; then
    fail ".env is readable by group/others; run: chmod 600 .env"
  else
    pass ".env permissions are owner-only"
  fi
fi

if [ "$failures" -gt 0 ]; then
  printf '\n%d check(s) failed\n' "$failures"
  exit 1
fi
printf '\nAll checks passed\n'
