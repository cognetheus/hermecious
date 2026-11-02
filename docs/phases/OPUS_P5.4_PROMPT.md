# OPUS 5.5 HIGH — HERMECIOUS P5.4 | Secure WhatsApp Inbox + Durable Timeline

**YOUR ASSIGNMENT: IMPLEMENT P5.4 ONLY.** The deliverable is a production-quality **read-only operator inbox** backed by actual P5.2 signed normalized events and, when present, P5.3 test-send delivery observations. You must not create a send button, reply editor, AI classifier, contact-enrollment route, production dispatch path or any Meta outbound call. **STOP after P5.4 verification.**

## Read first and establish actual source-of-truth contracts

1. Read `CLAUDE.md` / `AGENTS.md`, ADRs and `EXECUTION_LEDGER.md` and inspect actual repository/branch/dirty status, migrations, test baseline and existing routes. Never invent filenames or recreate modules just because this prompt has conceptual names.
2. Read `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` P1.1–P1.5, P4.3, P5.2–P5.4, and the whole P5.4 section plus §§0,4–6 in `docs/phases/HERMECIOUS_BATCH_09_P5.4-P6.1.md`.
3. Read `docs/phases/HERMECIOUS_BATCH_08_P5.1-P5.3.md` and inspect **implemented**, not merely specified, P5.2 HMAC-verified raw→normalized event log, provider identities, status reducer, pending unmatched status correlation and P5.3 isolated test records. Read P4.3 encrypted/hashed contact identity contract; P1.1 auth/CSRF/org scope; P1.5 job/idempotency patterns.
4. Identify exact existing models/DTOs/services and prerequisites. If P5.2 signed event storage isn't actually verified, report BLOCKED; implement isolated projection scaffolding/contract tests only if possible without inventing signed events. A P5.3 external WATEST-10 block does not prevent synthetic authenticated fixtures for **engineering tests**, but keep the external limitation visible.

## Human journey and product boundaries

- Authenticated operator opens **Inbox → WhatsApp**; sees threads ordered by real last activity, masked identity, unread count, inbound text, real test send observations and status history. Unknown contact is **Unmatched WhatsApp contact**, not an inferred school prospect.
- Clicking thread displays a stable chronological timeline with `inbound`, `TEST outbound`, `provider accepted`, signed `sent/delivered/read/failed`, pending/indeterminate states and safe errors. Timezone shown as `Asia/Karachi`, timestamps stored UTC.
- Operator can **mark reviewed** (one audited local action); no reply, no Meta send, no marketing consent creation, no account enrollment, no AI recommendations.

## Implement in strict bounded order

**1. Contract / schema inventory.** Write `INBOX-01..10` tests and minimal additive migration plan. Prefer existing `incoming_messages`, `provider_events`, `conversation_threads`, `test_send_intents` if they exist. Do not duplicate webhook parsing or contact encryption. Establish org+connection+contact digest thread key and provider message uniqueness scope. Define explicit provenance `verified_inbound|provider_test|existing_verified`. Ensure all foreign keys cannot cross organizations.

**2. Durable projection.** Consume only P5.2 **signature-verified normalized** events via existing P1.5 durable jobs/outbox. Create thread+message+checkpoint atomically, idempotently on event ID and provider message identity. Two concurrent first-inbound jobs for same external contact produce one thread. Duplicate event redelivery does not double unread count. Reuse P5.2 status reconciliation, including status-before-message pending events, out-of-order events, provider-accepted ≠ delivered and test origin markers. Do not conflate fake P4.5 simulation with Meta provider status. Keep the signed event log untouched.

**3. Recovery and pagination.** Add bounded replay/rebuild from normalized immutable records, with transactional checkpoints and safe concurrency/no lost messages after worker kill. Rebuild twice should produce identical counts/revisions; zero outbound side effects. Last activity is max observed event timestamp with stable tie-break, not whichever callback arrived last. Keyset paginate by timestamp/id and apply tenant filters in SQL, not only UI. Handle unsupported media as safe placeholders; never fetch media in P5.4.

**4. API authorization.** Implement existing-style operator-only read endpoints: list threads, messages, optional status details and mark-reviewed. Authorization and org scope enforced before retrieval; CSRF on mutation; optimistic compare/mark-reviewed under concurrency. Limit page size; use `Cache-Control: private, no-store` for message details. Redact raw E.164 phone/token/webhook signatures, safe error codes only. Do not log full message bodies or raw webhook content. Avoid decrypted contact info in browser cache, SSR page source, URL path or analytics.

**5. UI.** Build functional, accessible, responsive inbox/timeline, explicit `READ ONLY` marker, masked unknown contacts, distinctive `TEST` versus production (production never synthetic), actual signed status provenance and errors. Implement unread/reviewed state, empty/loading/unauthorized/retry UX, right-to-left Urdu rendering, Unicode-safe text, XSS-safe plain text. Polling is sufficient; no new realtime infrastructure without existing patterns.

**6. Tests and failure simulation.** Run real current repository commands (discovered, not assumed) for format/lint, types, migration up/down on disposable DB, unit, contract, Postgres integration, concurrent jobs/restarts, and Playwright E2E. Regress P5.2 signature verification and WATEST fixture states. Intercept/deny network to Meta, assert zero calls and no send-capable queue route/UI. Inspect logs and UI for contact/secret leaks. Self-review, fix issues, rerun.

## Exact acceptance matrix (all ten)

| Gate | Expected observable proof |
|---|---|
| `INBOX-01` | Verified P5.2 inbound materializes one correct tenant/phone thread+message and no lead auto-enrollment |
| `INBOX-02` | Duplicates+concurrent first arrivals do not double-create threads/messages/unread |
| `INBOX-03` | Signed status histories correctly reconciled and not downgraded, status-before-message handled |
| `INBOX-04` | Restart, transaction rollback, replay/backfill twice retains same persisted timeline and zero Meta calls |
| `INBOX-05` | Wrong tenant/WABA/connection/role/expired session cannot access or mutate any thread |
| `INBOX-06` | Masking/redaction of phone, secrets, raw payload and HTML injection in UI/API/logs |
| `INBOX-07` | Stable pagination, late-arriving messages, identical UTC timestamps, proper Lahore UI time |
| `INBOX-08` | Unmatched contact and Meta TEST send are not school prospects or simulated delivery |
| `INBOX-09` | Mark-reviewed owner/operator action has CSRF, audit, replay idempotency and no provider effect |
| `INBOX-10` | E2E inbox and failure coverage; no reply/send UI, no outbound queue, zero egress |

## Mandatory negative-path cases

- Duplicate webhooks with different envelope/event IDs but same provider message ID; two workers race on first contact.
- Two organizations with identical contact digests/phone digits, two WABAs with same provider message string; no cross-scope collisions.
- Status callback preceding Graph accepted response; provider accepted without later delivery; conflicting `failed` and `delivered` observations.
- Invalid content, script tags, malformed Unicode, unsupported media, empty payload and expired redacted content.
- Worker crash before/after DB commit, transaction rollback, interrupted replay, backdated events and thread-level last-activity tie.
- Stale session/CSRF, cross-org UUID enumeration, pagination abuse, browser developer tools/SSR exposure, log scanning for secrets.
- Test phone is erroneously linked to live sales account—must deny or require explicit audited manual mapping with no permission grant.

## Scope exclusions / safety

No Meta POST, no send preview/confirm, no inferred opt-in, no provider SDK init just to render inbox, no auto account match, no model calls, no opportunity/booking actions, no P5.5 readiness gate, no P6 classifier. Do not edit `HERMECIOUS_LIVE_OUTBOUND_ENABLED` away from false. Do not claim full live replay proof without externally verified P5.2/P5.3 evidence.

## Completion report

Provide base/final Git SHA, changed files and migrations, actual contract mappings, route names and UI behavior, executed commands+exit codes for `INBOX-01..10`, failure evidence, no-egress proof, redaction audit, P5.3 external-test status, rollback and exact blockers. Ledger status only `VERIFIED` with actual evidence; unrun = `NOT_RUN`, missing external proof = `BLOCKED_EXTERNAL` where relevant. If blocked, show a narrowly scoped unblock without turning off security controls.

**STOP AFTER P5.4. DO NOT BEGIN P5.5 UNTIL P5.4 IS VERIFIED AND THE NEXT ASSIGNMENT IS GIVEN.**
