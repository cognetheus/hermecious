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
3. **Bind the organization (owner).** `bind_connection` binds the configured IDs to one organization; a phone belongs to exactly one organization. The operator CLI or admin step lands with P5.3.
4. **Subscribe the callback** at Meta: `https://<api-host>/api/v1/integrations/whatsapp/webhook` (HTTPS), with the verify token and the `messages` field. Meta's GET challenge must answer 200.
5. **Check:**
   - envelopes and items appear; the processor job is `provider_inbox.process`;
   - unknown senders stay unassigned;
   - a `STOP` creates a suppression;
   - nothing replies.

**Stop:** unsubscribe at Meta, or unset `HERMECIOUS_WHATSAPP_APP_SECRET` (POST → 503). Keep the stored evidence.
