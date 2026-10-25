"""Canonical WhatsApp addresses, keyed digests and masking (P4.3, ADR-022). Pure.

A contact address is never stored in plaintext. We keep:
- `address_digest`: HMAC-SHA256(key, canonical E.164), under a named key (`key_id`);
- `address_hint`: a masked form showing the country code and last three digits.

Key rotation: keys are listed newest first. New rows use the newest key; lookups (suppressions, duplicates)
compute the digest under every listed key, so an old key must stay listed while rows still use it.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass

_KEY_ID = re.compile(r"[a-z0-9_-]{1,16}")
# ASCII digits only: `\d` would also accept Urdu/Arabic digits, giving the same number a different digest.
_E164 = re.compile(r"\+[1-9][0-9]{7,14}")
_PK_LOCAL = re.compile(r"0(3[0-9]{9})")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class KeyringError(ValueError):
    pass


class AddressError(ValueError):
    pass


@dataclass(frozen=True)
class Keyring:
    keys: tuple[tuple[str, bytes], ...]  # newest first

    @property
    def current(self) -> tuple[str, bytes]:
        return self.keys[0]


def parse_keyring(raw: str) -> Keyring:
    keys: list[tuple[str, bytes]] = []
    for part in raw.split(","):
        key_id, sep, secret = part.strip().partition(":")
        if not sep or not _KEY_ID.fullmatch(key_id) or len(secret) < 32 or any(k == key_id for k, _ in keys):
            raise KeyringError("invalid contact key")
        keys.append((key_id, secret.encode()))
    if not keys:
        raise KeyringError("no contact key")
    return Keyring(tuple(keys))


def canonical(raw: str) -> str:
    """Strict E.164. Spaces, dashes, dots and brackets are ignored; Pakistani `03xx…` becomes `+923xx…`."""
    compact = re.sub(r"[\s\-.()]", "", raw.translate(_DIGITS))
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if local := _PK_LOCAL.fullmatch(compact):
        compact = "+92" + local.group(1)
    if not _E164.fullmatch(compact):
        raise AddressError("not a valid international phone number")
    return compact


def digest(key: bytes, e164: str) -> str:
    return hmac.new(key, f"whatsapp:{e164}".encode(), hashlib.sha256).hexdigest()


def digests(keyring: Keyring, e164: str) -> dict[str, str]:
    """{key_id: digest} under every listed key, for lookups across a rotation."""
    return {key_id: digest(key, e164) for key_id, key in keyring.keys}


def mask(e164: str) -> str:
    """`+92 ••••••• 567`: country code (for +92 numbers) and the last three digits only."""
    head = "+92" if e164.startswith("+92") else "+"
    return f"{head} {'•' * (len(e164) - len(head) - 3)} {e164[-3:]}"


def proof_digest(key: bytes, reference: str) -> str:
    """The proof reference (e.g. a form serial) is kept only as a keyed digest."""
    return hmac.new(key, f"proof:{' '.join(reference.split())}".encode(), hashlib.sha256).hexdigest()
