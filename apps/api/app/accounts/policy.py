"""Source rights and ingestion screening (blueprint §7, Batch 02 §P1.2.2).

Public availability is not permission: every source must come from an
allowlisted provider whose policy permits the requested storage class.
URL screening here is an ingestion baseline only; outbound fetch/SSRF
protection belongs to P2.1/P11.1.
"""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from app.accounts.models import StorageClass

RIGHTS_POLICY_VERSION = "rights-2026-10-23"
MAX_URL_LENGTH = 2048
MAX_EXCERPT_CHARS = 1000
MAX_EXCERPT_BYTES = 4000


class PolicyViolation(ValueError):
    """Ingestion refused by policy. The message is fixed and safe to show."""


class RightsViolation(PolicyViolation):
    """Refused because source rights forbid it (as opposed to malformed input)."""


@dataclass(frozen=True)
class ProviderPolicy:
    allowed_classes: frozenset[StorageClass]
    allow_http: bool = False
    allow_payload: bool = False
    requires_external_key: bool = False


ALL_CLASSES = frozenset(StorageClass)

# Allowlist. Unknown providers are refused, not guessed.
PROVIDERS: dict[str, ProviderPolicy] = {
    # Typed in by an operator from their own knowledge or a document they hold.
    "manual_entry": ProviderPolicy(ALL_CLASSES, allow_http=True, allow_payload=True),
    # Owner-supplied seed lists (Pilot A).
    "owner_seed_list": ProviderPolicy(ALL_CLASSES, allow_http=True, allow_payload=True),
    # A school's own public website where access is allowed (many Lahore sites are HTTP-only).
    "first_party_website": ProviderPolicy(
        frozenset({StorageClass.METADATA_ONLY, StorageClass.DERIVED_ONLY, StorageClass.FULL_ALLOWED}),
        allow_http=True,
    ),
    # Google Places: only the place ID may be kept; no content caching (blueprint §7).
    "google_places": ProviderPolicy(frozenset({StorageClass.METADATA_ONLY}), requires_external_key=True),
    # Deterministic test fixtures.
    "fixture": ProviderPolicy(ALL_CLASSES, allow_payload=True),
    # P2.1 synthetic discovery fixture: provenance only (no payloads), stable provider-scoped keys.
    "fixture_lahore_schools": ProviderPolicy(ALL_CLASSES, requires_external_key=True),
}

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
_SECRET_PARAM = re.compile(
    r"(?i)^(token|access_token|id_token|auth|authorization|key|api_key|apikey|secret|password|passwd|pwd|"
    r"session|sessionid|sid|sig|signature|code|otp|x-amz-signature|x-goog-signature)$"
)
_FORBIDDEN_CHARS = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f‪-‮⁦-⁩‎‏]")


def provider_policy(provider: str) -> ProviderPolicy:
    policy = PROVIDERS.get(provider)
    if policy is None:
        raise RightsViolation("source provider is not on the allowlist")
    return policy


def check_storage(provider: str, storage_class: str, payload_reference: str | None, external_key: str | None) -> None:
    policy = provider_policy(provider)
    try:
        storage = StorageClass(storage_class)
    except ValueError:
        raise RightsViolation("storage class is not permitted") from None
    if storage not in policy.allowed_classes:
        raise RightsViolation("provider rights do not permit this storage class")
    if payload_reference is not None and (storage != StorageClass.FULL_ALLOWED or not policy.allow_payload):
        raise RightsViolation("provider rights do not permit storing a payload")
    if policy.requires_external_key and not external_key:
        raise RightsViolation("provider requires a stable external key")


def screen_url(url: str, provider: str) -> str:
    """Return the URL if it is safe to store as provenance; raise otherwise."""
    if len(url) > MAX_URL_LENGTH or _FORBIDDEN_CHARS.search(url) or any(c.isspace() for c in url):
        raise PolicyViolation("source URL is malformed")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"https", "http"} or (scheme == "http" and not provider_policy(provider).allow_http):
        raise PolicyViolation("source URL scheme is not permitted")
    if parts.username is not None or parts.password is not None:
        raise PolicyViolation("source URL must not contain credentials")
    if parts.fragment:
        raise PolicyViolation("source URL must not contain a fragment")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise PolicyViolation("source URL has no host")
    if _is_internal_host(host):
        raise PolicyViolation("source URL points to a private or internal host")
    if any(_SECRET_PARAM.match(name) for name, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise PolicyViolation("source URL contains secret-bearing query parameters")
    return url


def _is_internal_host(host: str) -> bool:
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return "." not in host  # single-label intranet names
    return not address.is_global


def check_excerpt(excerpt: str | None, storage_class: str | None) -> str | None:
    """Verbatim excerpts need full storage rights and are bounded in size."""
    if excerpt is None:
        return None
    if storage_class != StorageClass.FULL_ALLOWED:
        raise RightsViolation("source rights do not permit storing a verbatim excerpt")
    if len(excerpt) > MAX_EXCERPT_CHARS or len(excerpt.encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise PolicyViolation("evidence excerpt is too long")
    if _FORBIDDEN_CHARS.search(excerpt):
        raise PolicyViolation("evidence excerpt contains control characters")
    return excerpt


def clean_text(value: str, field: str, max_length: int, *, required: bool = True) -> str:
    """NFKC-normalize, trim and reject control/bidi-override characters."""
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if _FORBIDDEN_CHARS.search(cleaned):
        raise PolicyViolation(f"{field} contains control characters")
    if (required and not cleaned) or len(cleaned) > max_length:
        raise PolicyViolation(f"{field} must be 1-{max_length} characters")
    return " ".join(cleaned.split())


def normalize_name(name: str) -> str:
    """Matching key: casefolded, punctuation-insensitive, single-spaced. Never used to merge on its own."""
    folded = unicodedata.normalize("NFKC", name).casefold()
    kept = "".join(ch if ch.isalnum() else " " for ch in folded)
    return " ".join(kept.split())
