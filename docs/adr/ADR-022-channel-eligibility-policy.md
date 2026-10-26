# ADR-022: Channel eligibility is a deterministic, simulation-only policy reading over masked, owner-verified evidence

- **Status:** Accepted on 2026-10-25 by owner delegation (the owner instructed "you decide and go ahead" after reviewing the audit; recorded in EXECUTION_LEDGER.md)
- **Date:** 2026-10-24
- **Source:** `OPUS_P4.3_PROMPT.md`; blueprint §4 P4.3 and §2 ("No outbound messaging occurs without channel eligibility and authorization; opt-out halts future outreach"). Batch 07 is absent from the repository.

## Context

Nothing upstream stored contacts, permissions or suppressions: the P1.2 data model has no `contacts`, `contact_permissions` or `suppression_entries` tables. P4.3 therefore adds a minimal, boundary-compatible slice. There is no WhatsApp provider, SDK, token or send path, and P4.3 adds none.

## Decision

### 1. Data (migration 0016)

| Table | Contents | Mutability |
|---|---|---|
| `contacts` | Account, channel `whatsapp`, a role (`school_office`, `admissions_office`, `accounts_office`, `principal_office`; never a person's name), `key_id`, `address_digest`, masked `address_hint` (`+92 ••••••• 101`) | Append-only |
| `contact_permissions` | Channel, purpose (`marketing` or `utility`), named business, basis `explicit_opt_in`, capture method, consent wording version, proof kind, keyed proof digest, captured/recorded/effective/expiry/revocation times, recorder, reviewer, reasons, `supersedes_id`, version | Evidence immutable; status moves forward only |
| `suppression_entries` | Channel, `key_id`, `address_digest`, masked hint, reason, contact, creator | Append-only; never lifted in P4.3 |
| `contact_commands` | Idempotency key, request digest, outcome | Insert-only |

- **No plaintext.** Numbers are canonicalised to E.164 and stored only as `HMAC-SHA256(key, "whatsapp:" + e164)` with a masked hint. Proof references (form serials, message ids) are stored only as keyed digests.
- **Keys.** `HERMECIOUS_CONTACT_HMAC_SECRETS` holds `key_id:secret[,older_id:older_secret]`, newest first, each secret at least 32 characters. Production refuses to start without it. Other environments have **no built-in key**: contact endpoints answer 503 until it is set (secrets rule 3).
- **Rotation.** New rows use the newest key. Duplicate checks compute the digest under every listed key. A key stays listed while any row uses it; rows are never re-keyed, because the plaintext is not kept.
- **Database guards.**
  - A verified row must have a reviewer different from the recorder.
  - Rejected and revoked rows need reasons.
  - At most one open (pending or verified) row per contact, channel and purpose.
  - A trigger refuses edits to evidence columns, backward transitions, a second review, and any version step other than +1.
- **Retention.** Suppressions are kept indefinitely. Downgrading 0016 refuses while any suppression exists.

### 2. Evidence lifecycle

- **Capture** (`record_permission`, owner or operator) always creates `pending`. It refuses, with 422 `EVIDENCE_REJECTED`, a business other than CoderzHunt, unknown consent wording, a capture time more than 5 minutes in the future or more than 365 days old, and unknown fields such as `verified` or `status`. Expiry is the capture time + 365 days.
- **New evidence for the same purpose** supersedes the open row. An edit therefore always returns to `pending`.
- **Verification** is owner-only. The owner must not be the recorder (four-eyes), and every evidence check runs again, plus expiry and suppression. There is no automatic, model or inbound-message grant.
- **Revocation** (owner or operator) and **suppression** (owner or operator, org-wide) are independent. Both use idempotency keys and expected versions with row locks.

### 3. Policy `eligibility-policy-1.0` (pure function)

Decisions are `allow_for_simulation`, `deny` or `defer`. Every deny reason is reported in precedence order:

1. kill switch (`HERMECIOUS_OUTREACH_KILL_SWITCH`), campaign paused or cancelled;
2. suppression;
3. verified opt-in for this channel and purpose (business-initiated purposes);
4. scope: purpose and named business;
5. freshness: expiry, age over 365 days, future dating, current consent wording;
6. **business-initiated:** a provider-approved template of the matching category. **Service reply:** an official inbound message from the same number less than 24 hours old (`now − received_at < 24h`; exactly 24h is closed);
7. campaign state, the evidence-quality gate, membership, rules, offer, assessment and evidence currency (Draft Studio's `blockers`);
8. an active human owner (the membership's approver; for service replies, the contact's creator);
9. **only when nothing denies:** business hours Mon–Sat 09:00–18:00 Asia/Karachi, a 20-per-day organization cap and a 7-day per-contact gap. These `defer`, with `next_window_at`.

- A public number, a research priority or an inbound "hello" never counts as an opt-in.
- `live_send_authorized` is always false.
- Each evaluation reads the database afresh and is audited (actor, decision, reasons, input digest, policy version; no address or proof). It is not a token and cannot be presented later.

### 4. Trust boundary until P5

- **Provider template state and inbound messages** come only from `app/eligibility/fixtures/whatsapp_fixtures_v1.json`. Each entry carries an HMAC (with a key committed in the repo), so accidentally edited entries are ignored; it is not protection against deliberate forgery. The trust boundary is that fixtures apply only outside production, to accounts whose every source is a synthetic fixture.
- **Fixtures apply only** to synthetic accounts outside production. A real account, or any production evaluation, therefore cannot reach `allow_for_simulation` for business initiation or service replies.
- **Operator-entered template references** are always `template_unverified`.
- **Clients cannot supply** `last_inbound_at`, `verified` or a template status (`extra="forbid"`).
- **Usage counters are zero:** no send ledger exists. P4.5 simulations will feed them.

## Consequences

- **Real outreach is impossible.** There is no provider, template approval or inbound feed, and the P3.4 gate is closed.
- **The engine is ready** for P4.4 to show eligibility reasons, and for P4.5 to simulate.

## Rollback

- **Stop:** set `HERMECIOUS_OUTREACH_KILL_SWITCH=true` (every decision denies), or stop using the endpoints.
- **Schema:** downgrade 0016 only on a disposable database without suppressions; the downgrade refuses otherwise.
