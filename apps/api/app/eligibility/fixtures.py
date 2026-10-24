"""Signed synthetic WhatsApp fixtures (P4.3, ADR-022): provider template states and inbound messages.

Until P5 there is no provider connection, so:
- only these fixtures can say a template is provider-approved (operator-entered template refs never are);
- only these fixtures can supply an inbound message time (a client never sends `last_inbound_at`).

Each entry is signed (HMAC-SHA256 over its canonical JSON) so an edited entry is ignored. Fixtures are refused in
production and apply only to synthetic accounts. Numbers are zero-filled placeholders, never real contacts.
"""

import hashlib
import hmac
import json
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

FIXTURE_FILE = Path(__file__).parent / "fixtures" / "whatsapp_fixtures_v1.json"
SIGNING_KEY = b"hermecious-synthetic-whatsapp-fixtures-v1"  # integrity of test data, not a secret
PREFIX = "fx_"


def sign(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "signature"}
    return hmac.new(SIGNING_KEY, json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def _verified(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in entries if hmac.compare_digest(str(e.get("signature", "")), sign(e))}


@cache
def _load() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    data = json.loads(FIXTURE_FILE.read_text())
    return _verified(data["templates"]), _verified(data["inbound"])


def template(ref: str) -> dict[str, Any] | None:
    return _load()[0].get(ref)


def inbound(ref: str) -> dict[str, Any] | None:
    entry = _load()[1].get(ref)
    if entry is None:
        return None
    return entry | {"received_at": datetime.fromisoformat(entry["received_at"])}


def catalogue() -> dict[str, list[dict[str, Any]]]:
    """What the UI may offer (no addresses)."""
    templates, inbound_messages = _load()
    return {
        "templates": [{k: t[k] for k in ("id", "category", "provider_status", "locale")} for t in templates.values()],
        "inbound": [
            {"id": m["id"], "received_at": m["received_at"], "text_kind": m["text_kind"]}
            for m in inbound_messages.values()
        ],
    }
