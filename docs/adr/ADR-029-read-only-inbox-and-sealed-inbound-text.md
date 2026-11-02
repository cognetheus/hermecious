# ADR-029: A read-only WhatsApp inbox over signed facts, with inbound text sealed at rest

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-11-02
- **Source:** `docs/phases/OPUS_P5.4_PROMPT.md`, blueprint §4 P5.4. The prompt also cites `docs/phases/HERMECIOUS_BATCH_09_P5.4-P6.1.md`, which is not in the repository; the prompt and the blueprint were used instead.

## Context

P5.2 (ADR-027) deliberately kept **no inbound text**, under Batch 08 §4: "encrypt or minimize at rest". The P5.4 inbox must show inbound text, and P6.1 must classify it. Those requirements conflict with P5.2's minimization.

## Decision

### 1. Inbound text is kept only sealed, only with a key, and only for 90 days (the safe default for the conflict)

- **Key:** `HERMECIOUS_INBOUND_CONTENT_SECRETS` (`key_id:secret`, newest first, like the contact keyring) seals text with **AES-256-GCM**. The key is derived with HKDF-SHA256.
- **Binding:** the associated data is `connection_id:provider_message_id`, so a ciphertext copied to another message or organization does not open.
- **Where it is stored:** sealing happens at receive, after the signature check. The ciphertext lives on the P5.2 event item (`normalized_json.sealed_text`). There is no plaintext column anywhere, and the text is never logged.
- **Without a key:** behaviour is exactly P5.2's. Nothing is kept, and the inbox says "Text not retained".
- **Retention:** 90 days. Older text shows as expired, and the P5.2 processor and the rebuild strip it from storage. The signed fact and its metadata stay.
- **Validity:** lone surrogates and NUL become U+FFFD. Text over 4,096 characters is truncated and flagged.
- **New dependency:** `cryptography` (AES-GCM, HKDF). It is well maintained; no cryptography is hand-written.

### 2. Threads are a forward-only projection; the timeline is read from the sources

- **`inbox_threads`:** one row per (connection, sender key id, sender digest), with org-scoped composite foreign keys. It holds only the last activity, the arrival sequence of the newest inbound, and the review marker.
- **Writers:**
  - the P5.2 processor (in the same transaction as the inbound message);
  - the P5.3 reservation (in the same transaction as the reservation);
  - `inbox.rebuild` (owner-triggered job, recomputed from the immutable source tables).

  All of them use `greatest(...)`, so redelivery, racing workers and repeated rebuilds converge, and a rebuild with no change bumps no version.
- **Unread:** count of inbound with `arrival_seq > reviewed_through_seq`. It is never a counter, so redelivery cannot double it, and a backdated message arriving after a review stays unread.
- **Timeline entries:**
  - inbound (provenance `verified_inbound`);
  - P5.3 test sends (provenance `provider_test`);
  - signed status observations (provenance `signed_webhook`).

  P4.5 simulated delivery never appears here.
- **Pagination:** keyset on `(time, id)`, with page caps of 50 threads and 100 entries.

### 3. Identity is shown from server-side registries only

The party label is chosen in this order:

1. A registered test recipient → `TEST recipient: <label>`. If the number also matches a sourced contact, it is flagged `matches_sourced_contact` and **not** mapped to the school.
2. A known contact → `Contact at <account>`.
3. Otherwise → **Unmatched WhatsApp contact**.

Numbers are shown masked. A raw number never leaves the server. Nothing is created, enrolled, matched by content or granted.

### 4. API and UI

- **Routes:** `/api/v1/inbox/whatsapp/threads`, `/threads/{id}`, `POST /threads/{id}/review`, `POST /rebuild`.
- **Roles:** owners and operators; **observers get 403**, because the content is business correspondence. The rebuild is owner-only.
- **Headers:** responses carry `Cache-Control: private, no-store`.
- **Mark reviewed** is the only local action. It is monotonic, clamped to what exists, audited once, needs CSRF, and has no provider effect.
- **UI:** `/inbox/whatsapp` shows a persistent READ ONLY marker and polls every 10–15 s.
  - TEST connections are labelled; times show in Asia/Karachi.
  - Message text is a plain text node with `dir="auto"`, so Urdu renders right to left and markup stays inert.
  - Attachments are placeholders and are never downloaded.
  - There is no reply, send, enroll or consent control.

## Consequences

- **Owner decision:** whether to provision `HERMECIOUS_INBOUND_CONTENT_SECRETS`, and whether 90 days is the right retention.
- **Rollback:** unset the key, and text stops being stored from that point. Migration 0023 drops only the derived thread table.
- **Old messages:** text received before a key existed can never be recovered.
- **Key rotation:** a rotated-out key makes old text unreadable, which is shown as such. Contact-key rotation would split one sender's threads by key id; that is accepted until a re-keying job exists.
