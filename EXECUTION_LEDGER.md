# Execution Ledger

The authoritative record of subphase progress. Statuses: `not-started`, `in-progress`, `verified`, `blocked`, `not-run` (see AGENTS.md). Entries are append-only, and corrections are recorded as new notes.

## Subphase status

| ID | Title (blueprint §4) | Status |
|---|---|---|
| P0.1 | AGENTS.md, README, ADR-001, ledger, `.env.example`, secrets rules | verified; awaiting owner review |
| P0.2 | Compose (API, web, Postgres, Redis, worker), health/readiness | not-started |
| P0.3 | CI lint/typecheck/test, migrations, fixtures, time control | not-started |
| P0.4 | Structured logging, typed errors, config validation, secret masking | not-started |
| P1.1 to P12.4 | See blueprint §4 | not-started |

## P0.1 — Repository foundation (2026-10-23)

**Scope (blueprint §4 P0):** `AGENTS.md`, project README, ADR-001 (modular monolith and approved stack), task ledger, `.env.example`, secrets rules.
**Gate:** setup instructions reproduce on a clean machine.

### Starting state

The repository had no commits. Its only file was `HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, which was committed unchanged as the baseline (`0dce235`). There was no code, no dependencies, no tests and no ADRs.

### Conflicts and the safe defaults chosen

1. **Blueprint location.** The task prompt cited `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md`, but the file is at the repo root, and blueprint §8 refers to it by bare name. It stays at the root. Moving it is a one-line `git mv` if the owner prefers `docs/`.
2. **ADR-001 status is `Proposed`, not `Accepted`.** §8 forbids an agent from self-approving decisions. The owner accepts it at this review.
3. **Worker library (Dramatiq vs RQ)** is left open, because §1 requires a separate ADR for that choice. It must be decided before P0.2 builds the worker.
4. **`.env.example` content.** No code reads any variable yet. Listing future variables (DB, Redis, WhatsApp) would be speculative scaffolding, so the template declares only the two values the blueprint fixes: the environment name and the `Asia/Karachi` timezone. Later subphases add a variable when their code first reads it (secrets rule 5).
5. **`scripts/` is not in the suggested tree (§1).** It was added because both the gate and the secrets rules need an executable check. Without one, "reproduces on a clean machine" could not be verified.

### Acceptance cases and results

| # | Case | Result |
|---|---|---|
| AC1 | The README setup steps reproduce from a fresh public clone on a clean machine: macOS with empty HOME/env, and Debian 12 container as non-root | **pass** (both) |
| AC2 | All P0.1 documents are present, and every relative markdown link resolves | **pass** |
| AC3 | A secret value or a credentialed URL in `.env.example` is rejected, and the value is never echoed | **pass** |
| AC4 | `.env` and its variants are git-ignored, and a force-added `.env` is detected | **pass** |
| AC5 | A local `.env` readable by group or others is rejected | **pass** |
| AC6 | A private key or well-known token format in any tracked or addable file is detected (file name reported, not content) | **pass** |
| AC7 | Failure handling: a malformed or duplicate `.env.example` entry, a missing required document, or a non-git copy each fail with a specific message and exit code | **pass** |
| AC8 | The tests discriminate: sabotaging the permission check and the secret-value check makes the matching tests fail | **pass** (9/11 with the mutation, then restored) |

### Commands and observed outcomes

| Command | Where | Outcome |
|---|---|---|
| `shellcheck scripts/verify-setup.sh scripts/verify-setup.test.sh` | macOS | exit 0, no findings |
| `bash -n` on both scripts | macOS (bash 3.2.57) | exit 0 |
| `bash scripts/verify-setup.sh` | working tree | 15 PASS, "All checks passed", exit 0 |
| `bash scripts/verify-setup.test.sh` | working tree | 11 passed, 0 failed, exit 0 |
| Mutation run: two checks disabled with `sed` in a scratch copy | scratch copy | 9 passed, 2 failed (expected), copy deleted |
| README steps under `env -i HOME=<empty> PATH=/usr/bin:/bin`, cloning `https://github.com/cognetheus/hermecious.git` at `7d4ad51` | macOS | verify exit 0 (16 PASS including .env perms); tests 11/0, exit 0 |
| The same README steps as user `dev` in `debian:bookworm-slim` (git 2.39.5, bash 5.2.15, GNU tar 1.34), clone at `7d4ad51` | Linux container | verify exit 0; tests 11/0, exit 0 |
| Relative link check over all tracked `*.md` | working tree | 15 links, 0 broken |

**Not run, and why:**
- `markdownlint` and `shfmt` are not installed locally. They will be added with CI in P0.3.
- `ruff`, `mypy`, `pytest`, `vitest` and Playwright do not apply, because there is no Python or TypeScript code yet.
- There are no contract or integration tests yet, because there are no integrations.

### Changed files

`.env.example`, `.gitignore`, `AGENTS.md`, `README.md`, `EXECUTION_LEDGER.md`, `docs/adr/ADR-001-modular-monolith-and-stack.md`, `docs/runbooks/secrets.md`, `scripts/verify-setup.sh`, `scripts/verify-setup.test.sh`. The blueprint is unchanged.

### Review notes

- **Security.** The checks never print secret values; this is tested. The scan is pattern-based and covers only the working tree. It is not a full secret scanner (no entropy analysis, no git-history scan). A dedicated scanner such as gitleaks is a candidate for P0.3 CI. No pre-commit hook was added, so enforcement relies on AGENTS.md and, later, CI.
- **Correctness and portability.** Verified on bash 3.2 with BSD tools and on bash 5.2 with GNU tools.
- **Idempotency.** `verify-setup.sh` is read-only. The test suite writes only to a `mktemp` directory that it removes on exit, and it never reads the developer's `.env`.
- **Architecture.** No application directories were created. ADR-001 records the approved stack and the exclusions.

### Blockers

None for P0.1. **Owner action:** accept or amend ADR-001, and confirm that the blueprint should stay at the repo root.

### Rollback

P0.1 is documentation and scripts only, with no data and no migrations. Run `git revert` on the P0.1 commits. `0dce235`, the blueprint baseline, remains.

### Next safe step

Owner review of P0.1, then the worker-library ADR (Dramatiq vs RQ), then **P0.2** (Compose, health and readiness probes). Do not start P0.2 until the owner approves it.
