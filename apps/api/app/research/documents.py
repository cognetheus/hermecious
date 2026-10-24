"""Research documents: fetch by provider-scoped source key, then validate and normalize (P3.1, ADR-016).

There is no URL fetch here. A document comes from a `DocumentFetcher` keyed by
`(provider, external_key)`. Only the synthetic fixture fetcher is enabled; any
other provider fails closed with `live_fetch_not_authorized` until a live
source is rights-reviewed. Validation refuses compressed, oversized,
non-text, PDF/image and undecodable bodies. HTML is reduced to visible text;
scripts, styles and comments are dropped and never executed or stored.
Normalized text lives in memory for one run only.
"""

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Protocol

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_NORMALIZED_CHARS_PER_JOB = 60_000
ALLOWED_TYPES = frozenset({"text/html", "text/plain"})
FIXTURE_DOCUMENTS = Path(__file__).with_name("fixtures") / "school_documents_v1.json"


class DocumentError(Exception):
    """A fixed, log-safe reason code."""

    def __init__(self, reason: str, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True)
class RawDocument:
    content_type: str  # e.g. "text/html; charset=utf-8"
    content_encoding: str | None
    body: bytes
    retrieved_at: datetime


@dataclass(frozen=True)
class NormalizedDocument:
    text: str
    sha256: str
    language: str
    truncated: bool


class DocumentFetcher(Protocol):
    def fetch(self, *, provider: str, source_key: str, now: datetime) -> RawDocument: ...


@cache
def _fixture_documents() -> dict[str, dict[str, str]]:
    data = json.loads(FIXTURE_DOCUMENTS.read_text(encoding="utf-8"))
    documents: dict[str, dict[str, str]] = data["documents"]
    return documents


class FixtureDocumentFetcher:
    """Synthetic, internally authored school pages keyed by fixture source key. Makes no network requests."""

    def fetch(self, *, provider: str, source_key: str, now: datetime) -> RawDocument:
        if provider != "fixture_lahore_schools":
            raise DocumentError("live_fetch_not_authorized")
        doc = _fixture_documents().get(source_key)
        if doc is None:
            raise DocumentError("no_document_for_source")
        return RawDocument(doc["content_type"], doc.get("content_encoding"), doc["body"].encode("utf-8"), now)


_SKIP_BLOCKS = re.compile(r"(?is)<(script|style|noscript|template|iframe|object)\b.*?</\1\s*>|<!--.*?-->")
_BREAKS = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\b[^>]*>")
_TAGS = re.compile(r"(?s)<[^>]*>")
_SPACES = re.compile(r"[ \t ]+")
_FORBIDDEN = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f‪-‮⁦-⁩‎‏]")


def _arabic_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if "؀" <= ch <= "ۿ") / len(letters)


def normalize(raw: RawDocument, budget_chars: int) -> NormalizedDocument:
    media = raw.content_type.split(";", 1)[0].strip().lower()
    if raw.content_encoding not in (None, "", "identity"):
        raise DocumentError("compressed_content_refused")  # never decompress: no zip/gzip bombs
    if media not in ALLOWED_TYPES:
        raise DocumentError("unsupported_media_type")
    if len(raw.body) > MAX_BODY_BYTES:
        raise DocumentError("response_too_large")
    try:
        decoded = raw.body.decode("utf-8")
    except UnicodeDecodeError:
        raise DocumentError("undecodable_body") from None
    if media == "text/html":
        decoded = _SKIP_BLOCKS.sub(" ", decoded)
        decoded = _BREAKS.sub("\n", decoded)
        decoded = html.unescape(_TAGS.sub(" ", decoded))
    text = _FORBIDDEN.sub(" ", unicodedata.normalize("NFKC", decoded))
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    truncated = len(text) > budget_chars
    text = text[: max(budget_chars, 0)]
    if not text:
        raise DocumentError("no_visible_text")
    ratio = _arabic_ratio(text)
    language = "ur" if ratio > 0.6 else ("mixed" if ratio > 0.1 else "en")
    return NormalizedDocument(text, hashlib.sha256(text.encode("utf-8")).hexdigest(), language, truncated)
