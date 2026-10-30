"""Signed Meta webhook parsing (P5.2, ADR-027). Pure: no I/O, no database.

The order matters:
1. the raw bytes are size-capped;
2. `X-Hub-Signature-256` is verified over those exact bytes (HMAC-SHA256 with the app secret, constant time);
3. only then is anything parsed.

The parsed shape is bounded and validated. A signed but unrecognised event is quarantined with a reason, never
an exception that loses a batch. No sender, organization or account binding is trusted from the payload: the
binding comes from server-side configuration (`provider_connections`).
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_BODY_BYTES = 256 * 1024  # Meta batches are small; this leaves ample room and bounds parse time
MAX_ENTRIES = 50
MAX_CHANGES = 50
MAX_ITEMS_PER_CHANGE = 100
MAX_ID_CHARS = 256
FUTURE_TOLERANCE = timedelta(minutes=5)
MAX_AGE = timedelta(days=8)  # Meta retries deliveries for up to 7 days
_SIGNATURE = re.compile(r"sha256=([0-9a-f]{64})")
_DIGITS = re.compile(r"[0-9]{5,20}")
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_STATUS = {"sent", "delivered", "read", "failed"}
_KINDS = {"text", "image", "document", "interactive"}
# Opt-out cues (English and Urdu). Deliberately narrow: a cue starts the deterministic suppression path; it never
# grants anything.
_STOP = re.compile(r"(?i)^\s*(stop|stop all|unsubscribe|opt[ -]?out|cancel|end|quit|بند کریں|بند|روکیں)\s*[.!]*\s*$")


def valid_signature(app_secret: str, raw: bytes, header: str | None) -> bool:
    if header is None:
        return False
    match = _SIGNATURE.fullmatch(header.strip())
    if match is None:
        return False
    expected = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, match.group(1))


def valid_challenge(mode: str | None, token: str | None, challenge: str | None, verify_token: str) -> bool:
    if mode != "subscribe" or token is None or challenge is None or not _CHALLENGE.fullmatch(challenge):
        return False
    return hmac.compare_digest(token.encode(), verify_token.encode())


@dataclass
class Item:
    item_type: str  # incoming_message | delivery_status | unsupported
    phone_number_id: str
    waba_id: str
    provider_message_id: str | None
    provider_timestamp: datetime | None
    normalized: dict[str, Any]
    quarantine: str | None = None
    sender_e164: str | None = field(default=None, repr=False)  # used for the keyed digest, never stored

    def logical_key(self, connection_id: str) -> str:
        n = self.normalized
        if self.item_type == "incoming_message":
            basis = f"msg:{connection_id}:{self.provider_message_id}"
        elif self.item_type == "delivery_status":
            stamp = self.provider_timestamp.isoformat() if self.provider_timestamp else ""
            basis = f"status:{connection_id}:{self.provider_message_id}:{n.get('status')}:{stamp}:{n.get('error_code')}"
        else:
            basis = f"other:{connection_id}:{json.dumps(n, sort_keys=True)}"
        return hashlib.sha256(basis.encode()).hexdigest()


@dataclass
class Parsed:
    items: list[Item]
    quarantine_reason: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


def _timestamp(value: Any, received_at: datetime) -> tuple[datetime | None, str | None]:
    try:
        seconds = int(str(value))
    except (TypeError, ValueError):
        return None, "timestamp_invalid"
    stamp = datetime.fromtimestamp(seconds, UTC)
    if stamp > received_at + FUTURE_TOLERANCE:
        return stamp, "timestamp_future"  # never extend a service window with a future time
    if stamp < received_at - MAX_AGE:
        return stamp, "timestamp_stale"
    return stamp, None


def _id(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= MAX_ID_CHARS and value.isprintable() else None


def _message(raw: Any, phone: str, waba: str, received_at: datetime) -> Item:
    data = raw if isinstance(raw, dict) else {}
    wamid, sender = _id(data.get("id")), data.get("from")
    stamp, problem = _timestamp(data.get("timestamp"), received_at)
    kind = data.get("type") if data.get("type") in _KINDS else "unsupported"
    body = data.get("text", {}).get("body") if kind == "text" and isinstance(data.get("text"), dict) else None
    text = body if isinstance(body, str) else None
    if wamid is None or not isinstance(sender, str) or not _DIGITS.fullmatch(sender):
        problem = problem or "message_invalid"
    normalized = {
        "kind": kind,
        "text_length": len(text) if text is not None else None,
        "stop_signal": bool(text is not None and _STOP.match(text)),
    }  # the text itself is not kept (Batch 08 §4: minimise inbound content at rest)
    item = Item("incoming_message", phone, waba, wamid, stamp, normalized, problem)
    item.sender_e164 = f"+{sender}" if isinstance(sender, str) and _DIGITS.fullmatch(sender) else None
    return item


def _status(raw: Any, phone: str, waba: str, received_at: datetime) -> Item:
    data = raw if isinstance(raw, dict) else {}
    wamid = _id(data.get("id"))
    stamp, problem = _timestamp(data.get("timestamp"), received_at)
    status = data.get("status") if data.get("status") in _STATUS else "unknown"
    errors = data.get("errors")
    code = None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict) and isinstance(errors[0].get("code"), int):
        code = str(errors[0]["code"])
    if wamid is None:
        problem = problem or "status_invalid"
    return Item("delivery_status", phone, waba, wamid, stamp, {"status": status, "error_code": code}, problem)


def parse(raw: bytes, received_at: datetime) -> Parsed:
    """Bounded parse of an already-verified body into per-item facts (or a quarantine reason)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Parsed([], "payload_invalid")
    if not isinstance(data, dict) or data.get("object") != "whatsapp_business_account":
        return Parsed([], "object_unsupported")
    entries = data.get("entry")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_ENTRIES:
        return Parsed([], "payload_invalid")
    items: list[Item] = []
    counts = {"unsupported_fields": 0, "invalid_changes": 0}
    for entry in entries:
        waba = entry.get("id") if isinstance(entry, dict) else None
        changes = entry.get("changes") if isinstance(entry, dict) else None
        if not isinstance(waba, str) or not _DIGITS.fullmatch(waba) or not isinstance(changes, list):
            counts["invalid_changes"] += 1
            continue
        for change in changes[:MAX_CHANGES]:
            if not isinstance(change, dict) or not isinstance(change.get("value"), dict):
                counts["invalid_changes"] += 1
                continue
            value = change["value"]
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            phone = metadata.get("phone_number_id")
            if not isinstance(phone, str) or not _DIGITS.fullmatch(phone):
                counts["invalid_changes"] += 1
                continue
            if change.get("field") != "messages":
                counts["unsupported_fields"] += 1
                items.append(
                    Item(
                        "unsupported", phone, waba, None, None, {"field": str(change.get("field"))[:64]}, "unsupported"
                    )
                )
                continue
            messages, statuses = value.get("messages"), value.get("statuses")
            for raw_message in (messages if isinstance(messages, list) else [])[:MAX_ITEMS_PER_CHANGE]:
                items.append(_message(raw_message, phone, waba, received_at))
            for raw_status in (statuses if isinstance(statuses, list) else [])[:MAX_ITEMS_PER_CHANGE]:
                items.append(_status(raw_status, phone, waba, received_at))
    return Parsed(items, None if items else "no_items", counts)
