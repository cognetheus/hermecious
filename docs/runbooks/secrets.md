# Secrets rules

These rules apply to every contributor, human or agent, and to every subphase. `scripts/verify-setup.sh` enforces the mechanically checkable ones.

## Rules

1. **Never commit a secret.** `.env` and any `.env.*` file except `.env.example` are git-ignored. Do not force-add them.
2. **`.env.example` holds names, not values.** Secret variables have an empty value. Their names contain `PASSWORD`, `SECRET`, `TOKEN`, `PRIVATE_KEY`, `API_KEY` or `ENCRYPTION_KEY`. A URL value may not embed credentials (`scheme://user:password@host`). Pass credentials in their own secret variable instead. Non-secret defaults, such as the timezone, may have values.
3. **Empty means fail closed.** A component that needs a secret must refuse to start when the secret is missing or empty. It must never fall back to a built-in default. Config validation lands in P0.4.
4. **Local `.env` is owner-only.** Run `chmod 600 .env`. Verification fails if the file is readable by the group or by others.
5. **Add variables when they are first used.** The P0.1 baseline declares only the environment name and the business timezone, which the blueprint fixes. Any later variable is added to `.env.example` only by the subphase whose code first reads it, and is documented in the same change.
6. **Secrets never reach logs, model prompts, model-run records, audit digests, fixtures or error messages.** Secret masking and its gate (“no secrets in logs”) land in P0.4.
7. **Use unique values per environment.** Do not reuse development secrets in production. Generate them with a CSPRNG, for example `openssl rand -base64 48`.
8. **Production secrets stay off the repository and off developer laptops.** They are provisioned only on the VPS (P11.3).

## If a secret is committed or leaked

1. Rotate the secret at its provider immediately. Treat it as compromised even if the commit was never pushed.
2. Remove it from the working tree and add the ignore rule if one was missing.
3. Rewriting published git history requires the owner's explicit approval. Rotation is the actual fix and comes first.
4. Record the incident and the rotation in `EXECUTION_LEDGER.md`, without the secret value.
