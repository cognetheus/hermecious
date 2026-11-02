# WhatsApp Cloud API runbook (Batch 08)

Decision records: ADR-026 (adapter and modes), ADR-027 (webhook), ADR-028 (test send). Contract: `docs/contracts/whatsapp.md`.

> **Production outreach is disabled.** `HERMECIOUS_LIVE_OUTBOUND_ENABLED=true` refuses to start, and production mode has no outbound transport. The only send in Batch 08 is a single, owner-confirmed **test** template to a registered test recipient (P5.3), and it is a **real** WhatsApp message.

## 0. Default: simulation

Nothing to configure. `HERMECIOUS_WHATSAPP_MODE=simulation` refuses every Meta ID and credential. The webhook answers 503 (POST) and 403 (GET).

## 1. Receive webhooks (P5.2)

1. **Create the app in the Meta developer dashboard** with the WhatsApp product. Note the app secret, the WhatsApp Business Account (WABA) ID and the phone-number ID. Choose a verify token: random, 32+ characters.
2. **Configure secrets on the server only:**
   - `HERMECIOUS_WHATSAPP_MODE` (`production` on the production server, or `provider_test` on a test server, §2);
   - `HERMECIOUS_WHATSAPP_WABA_ID` and `HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID`;
   - `HERMECIOUS_WHATSAPP_APP_SECRET` and `HERMECIOUS_WHATSAPP_VERIFY_TOKEN`.

   Never commit them, paste them into tickets, or print them.
3. **Bind the organization (owner).** `POST /api/v1/integrations/whatsapp/connection/bind` (or the P5.3 page) binds the configured IDs to one organization; a phone belongs to exactly one organization.
4. **Subscribe the callback** at Meta: `https://<api-host>/api/v1/integrations/whatsapp/webhook` (HTTPS), with the verify token and the `messages` field. Meta's GET challenge must answer 200.
5. **Check:**
   - envelopes and items appear; the processor job is `provider_inbox.process`;
   - unknown senders stay unassigned;
   - a `STOP` creates a suppression;
   - nothing replies.

**Stop:** unsubscribe at Meta, or unset `HERMECIOUS_WHATSAPP_APP_SECRET` (POST → 503). Keep the stored evidence.

## 2. One real test send (P5.3, ADR-028)

**Needs, from the owner:**
- a Meta developer app with Meta's **test** business phone number;
- an access token with `whatsapp_business_messaging` and `whatsapp_business_management`;
- the recipient added and verified in Meta's test configuration;
- the owner's own decision to send. An agent never performs this step.

**Steps:**

1. **On a non-production server**, set these in the untracked `.env`:
   - `HERMECIOUS_WHATSAPP_MODE=provider_test`;
   - the WABA and phone-number IDs;
   - the access token, app secret and verify token;
   - `HERMECIOUS_WHATSAPP_TEST_IDENTITY_CONFIRMED_BY` and `_AT`: who checked in the Meta dashboard that both IDs are *test* assets, and when;
   - `HERMECIOUS_WHATSAPP_TEST_RECIPIENTS`: your own number, at most 5 numbers;
   - `HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED=true`.

   Startup refuses a phone ID listed in `HERMECIOUS_WHATSAPP_PRODUCTION_PHONE_NUMBER_IDS`.
2. **Subscribe the webhook** (§1) so that statuses come back.
3. **Open `/integrations/whatsapp`** as the owner:
   1. **Bind** if needed.
   2. **Sync templates from Meta.** Only a fresh, `APPROVED`, `UTILITY` or `MARKETING` template without header parameters is usable. Do not assume `hello_world` exists.
   3. **Register** your number with a consent statement. A number that is a school contact is refused.
4. **Preview test.** Check the exact template, language, category, parameters and masked number. Tick the box and press **Send one real test message**. This is the only real send.
5. **Read the result:**
   - `provider_accepted` with a Meta message ID means Meta accepted it, **not** that it was delivered;
   - delivery appears only when a signed webhook arrives;
   - `indeterminate` means unknown: check the phone and the Meta dashboard before any *new* preview. Nothing is retried automatically.
6. **Record redacted proof in the ledger:**
   - the template name;
   - the masked number;
   - the `wamid` prefix;
   - the webhook statuses with timestamps;
   - who confirmed.

   Then set `HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED=false`.

**Stop at any time:** set the kill switch to `false`, which denies confirms immediately, or set the mode to `simulation`.

**Daily cap:** 3 confirmed attempts per Asia/Karachi day.

## 3. Read-only inbox (P5.4, ADR-029)

1. **Optional: keep inbound text.** Set `HERMECIOUS_INBOUND_CONTENT_SECRETS=k1:<32+ random characters>` (a SECRET) and restart the API and worker.
   - Without it, inbound messages are listed but their text is never stored.
   - Text is sealed for 90 days. To rotate, put a new key first and keep the old one until its texts have expired.
2. **Read:** owners and operators open **Inbox**. **Mark reviewed** is local only and sends nothing.
3. **Repair the projection** if needed: `POST /api/v1/inbox/whatsapp/rebuild` (owner). It is safe to repeat and changes nothing if the threads are already correct.
4. **Stop storing text:** unset the key and restart. Text already sealed stays until it expires; it becomes unreadable once the key is gone.

## 4. Production go/no-go and the pilot (P5.5, ADR-030)

**An agent never performs these steps.**

1. **Review:** open **Production readiness** as the owner and press **Evaluate readiness now**. Resolve each non-VERIFIED row with its listed owner. Record only real human decisions as attestations, each with an evidence reference.
2. **Catalog:** sync the production catalog (`POST /api/v1/release/whatsapp/catalog/sync`). This is read-only.
3. **Content approval:** P4.4 cannot yet approve production content (ADR-030 §6). This is an owner decision before any pilot.
4. **Deploy-time live gate:** this is a deployment change that the application cannot make. Set:
   - `HERMECIOUS_ENV=production` and `HERMECIOUS_WHATSAPP_MODE=production`;
   - `HERMECIOUS_BUILD_SHA=<commit>`;
   - `HERMECIOUS_LIVE_OUTBOUND_APPROVED_BY=<name>` and `HERMECIOUS_LIVE_OUTBOUND_APPROVED_AT=<ISO time>`;
   - `HERMECIOUS_LIVE_OUTBOUND_ENABLED=true`.

   Startup refuses any other combination.
5. **Authorize:** evaluate again, then authorize a pilot. Start with 1 message a day and type the acknowledgement exactly.
6. **Send one message:** preview it, check the template, parameters and contact, then confirm with the contact's number. It must match the approved, opted-in contact.
7. **Read the result:**
   - `provider_accepted` means accepted by Meta only; delivery shows when a signed webhook arrives;
   - `indeterminate` means investigate in the Meta dashboard before any new preview. Nothing is retried.

**Stop:** pause (human takeover or quality alert) or revoke the pilot, set `HERMECIOUS_OUTREACH_KILL_SWITCH=true`, or set the live flag to `false` and restart. Messages Meta already accepted cannot be recalled.
