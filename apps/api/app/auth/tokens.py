"""Session cookie values and session-bound CSRF tokens (ADR-010 §2-3).

Cookie value: `<session_id hex>.<verifier>`. Only sha256(verifier) is stored.
CSRF token: base64url(HMAC-SHA256(key=verifier, CSRF_LABEL)).
"""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass

VERIFIER_BYTES = 32  # 256 bits
CSRF_LABEL = b"hermecious-csrf-v1"
_COOKIE_VALUE = re.compile(r"([0-9a-f]{32})\.([A-Za-z0-9_-]{43})")


@dataclass(frozen=True)
class SessionToken:
    session_id: uuid.UUID
    verifier: str

    @property
    def cookie_value(self) -> str:
        return f"{self.session_id.hex}.{self.verifier}"


def new_token() -> SessionToken:
    return SessionToken(uuid.uuid4(), secrets.token_urlsafe(VERIFIER_BYTES))


def parse_cookie(value: str | None) -> SessionToken | None:
    if value is None:
        return None
    match = _COOKIE_VALUE.fullmatch(value)
    if match is None:
        return None
    return SessionToken(uuid.UUID(hex=match.group(1)), match.group(2))


def verifier_hash(verifier: str) -> str:
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def verifier_matches(verifier: str, stored_hash: str) -> bool:
    return hmac.compare_digest(verifier_hash(verifier), stored_hash)


def csrf_token(verifier: str) -> str:
    digest = hmac.new(verifier.encode("ascii"), CSRF_LABEL, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def csrf_matches(verifier: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_token(verifier).encode("ascii"), presented.encode("utf-8", "replace"))
