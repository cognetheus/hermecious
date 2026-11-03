Synthetic, scrubbed WhatsApp Cloud API fixtures (Batch 08). No real account, phone number, token or message.
Numbers are zero-filled placeholders. Webhook signatures are computed in test code over the exact raw bytes;
no app secret is checked in.

**Webhook fixtures (Batch 08 §5).** Each `webhook_*.json` is posted byte-for-byte (signed in test code) by `test_wahook_fixture_files_parse_as_specified`.

| File | Contents |
|---|---|
| `webhook_inbound_text.json` | One text message from a synthetic sender |
| `webhook_status_{sent,delivered,read,failed}.json` | One status each for the same outbound wamid (`failed` carries error 131026) |
| `webhook_batch_mixed.json` | Two entries: a message and a status, a message for a foreign phone (unmapped), and an `account_update` field (quarantined) |
| `webhook_wrong_waba.json` | A message under another WABA (unmapped: nothing stored) |
| `webhook_get_challenge.txt` | The challenge string used for the GET handshake |

Timestamps are relative to the test clock (`FIXED_NOW`, 2026-10-23 07:00 UTC).
