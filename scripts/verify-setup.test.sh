#!/usr/bin/env bash
# Deterministic acceptance tests for scripts/verify-setup.sh. Every case runs
# against a throwaway copy of the working tree; the real repository and any
# local .env are never touched or read.
set -u

repo_root=$(cd "$(dirname "$0")/.." && pwd -P)
work=$(mktemp -d "${TMPDIR:-/tmp}/hermecious-verify.XXXXXX") || exit 2
trap 'rm -rf "$work"' EXIT

passed=0
failed=0
n=0

# Copies tracked and addable (non-ignored) files into a fresh git repo.
fresh_copy() {
  n=$((n + 1))
  dest="$work/case$n"
  mkdir -p "$dest"
  (cd "$repo_root" && git ls-files -z --cached --others --exclude-standard |
    while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done |
    tar --null -T - -cf -) | (cd "$dest" && tar -xf -)
  (cd "$dest" && git init -q && git add -A)
}

# expect <name> <exit-status> <required-output> [forbidden-output]
expect() {
  output=$(cd "$dest" && bash scripts/verify-setup.sh 2>&1)
  status=$?
  if [ "$status" -eq "$2" ] && printf '%s' "$output" | grep -qF -- "$3" &&
    { [ -z "${4:-}" ] || ! printf '%s' "$output" | grep -qF -- "$4"; }; then
    printf 'ok      %s\n' "$1"
    passed=$((passed + 1))
  else
    printf 'NOT OK  %s (exit %s)\n%s\n' "$1" "$status" "$output"
    failed=$((failed + 1))
  fi
}

fresh_copy
expect "clean clone passes" 0 "All checks passed"

fresh_copy
cp "$dest/.env.example" "$dest/.env" && chmod 600 "$dest/.env"
expect "README setup (.env copied, chmod 600) passes" 0 ".env permissions are owner-only"

fresh_copy
cp "$dest/.env.example" "$dest/.env" && chmod 644 "$dest/.env"
expect "world-readable .env fails" 1 "FAIL  .env is readable by group/others"

fresh_copy
cp "$dest/.env.example" "$dest/.env" && (cd "$dest" && git add -f .env)
expect "force-tracked .env fails" 1 "FAIL  env files are tracked: .env"

fresh_copy
echo "SESSION_SECRET=hunter2-value" >>"$dest/.env.example"
expect "secret value in .env.example fails without echoing it" 1 \
  "FAIL  .env.example secret SESSION_SECRET must be empty" "hunter2-value"

fresh_copy
echo "DATABASE_URL=postgresql://app:pw-value@db:5432/app" >>"$dest/.env.example"
expect "credentials embedded in a URL fail" 1 \
  "FAIL  .env.example DATABASE_URL embeds credentials" "pw-value"

fresh_copy
echo "HERMECIOUS_ENV=test" >>"$dest/.env.example"
expect "duplicate key fails" 1 "FAIL  .env.example declares HERMECIOUS_ENV twice"

fresh_copy
echo "not a variable" >>"$dest/.env.example"
expect "malformed line fails" 1 "is not KEY=VALUE"

fresh_copy
# Header assembled from parts so this file never matches the scanner itself.
printf '%s\n' "-----BEGIN ""RSA PRIVATE KEY-----" >"$dest/deploy-notes.txt"
expect "private key in an addable file fails" 1 "FAIL  credential-like content in: deploy-notes.txt"

fresh_copy
rm "$dest/AGENTS.md"
expect "missing required document fails" 1 "FAIL  missing: AGENTS.md"

fresh_copy
rm -rf "$dest/.git"
expect "non-git copy is refused" 2 "ERROR not the root of a git work tree"

printf '\n%d passed, %d failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
