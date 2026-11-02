"""Sealed inbound message text (P5.4, ADR-029). Pure: no I/O.

P5.2 kept no inbound text. The operator inbox (P5.4) and offline intent review (P6.1) need it, so text is kept only:
- sealed with AES-256-GCM under a key derived (HKDF-SHA256) from `HERMECIOUS_INBOUND_CONTENT_SECRETS`;
- bound by associated data to the connection and the provider message id, so a ciphertext cannot be moved to
  another message or organization;
- for `RETENTION`, after which it is stripped from storage and shown as expired.

Without a configured key nothing is sealed and nothing is kept (fail closed to minimization).
"""

import base64
import os
import re
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.contacts.addresses import Keyring, parse_keyring
from app.core.settings import Settings

RETENTION = timedelta(days=90)
MAX_TEXT_CHARS = 4096  # WhatsApp's own limit for a text message body
_INFO = b"hermecious-inbound-content-v1"
_UNSAFE = re.compile("[\ud800-\udfff\x00]")  # in a Python str every surrogate code unit is a lone one


def keyring(settings: Settings) -> Keyring | None:
    raw = settings.inbound_content_secrets
    return parse_keyring(raw.get_secret_value()) if raw is not None else None  # validated at startup


def clean(text: str) -> str:
    """Valid UTF-8 without NUL: lone surrogates (possible via JSON escapes) become U+FFFD, never crash a batch."""
    return _UNSAFE.sub("\ufffd", text)


def _key(secret: bytes) -> AESGCM:
    return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(secret))


def aad(connection_id: str, provider_message_id: str) -> bytes:
    return f"{connection_id}:{provider_message_id}".encode()


def seal(keys: Keyring, associated: bytes, text: str) -> dict[str, Any]:
    key_id, secret = keys.current
    nonce = os.urandom(12)
    sealed = _key(secret).encrypt(nonce, text[:MAX_TEXT_CHARS].encode("utf-8"), associated)
    return {
        "key_id": key_id,
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(sealed).decode(),
        "truncated": len(text) > MAX_TEXT_CHARS,
    }


def unseal(keys: Keyring | None, associated: bytes, sealed: Any) -> str | None:
    """The text, or None when it cannot be read (no key, rotated-out key, tampering or a malformed record)."""
    if keys is None or not isinstance(sealed, dict):
        return None
    secret = dict(keys.keys).get(str(sealed.get("key_id")))
    if secret is None:
        return None
    try:
        nonce, ct = base64.b64decode(str(sealed["nonce"])), base64.b64decode(str(sealed["ct"]))
        return _key(secret).decrypt(nonce, ct, associated).decode("utf-8")
    except (KeyError, ValueError, InvalidTag):
        return None
