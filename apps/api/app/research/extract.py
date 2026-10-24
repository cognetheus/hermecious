"""Deterministic claim extraction and independent verification (P3.1, ADR-016). Pure; no models.

Rules propose typed P1.2 claims from single sentences of a normalized
document, each with an exact `[start, end)` locator into that text. The
verifier re-derives every proposal from its own span, so a proposal from any
other origin (for example a future model adapter) cannot be accepted unless
the cited text itself supports it.

The extractor abstains on:
- negated statements;
- instruction-like text (prompt injection is data, never a command);
- anything outside the allowlisted rules.

It never infers needs, software, ownership or decision authority; "no portal
mentioned" produces nothing.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.accounts import claims, policy

EXTRACTOR_VERSION = "rules-1.0"
MAX_CLAIMS_PER_RUN = 25
MAX_SPAN = 1000

_SENTENCE = re.compile(r"[^.!?۔\n]+[.!?۔]?")
_NEGATION = re.compile(r"(?i)\b(not|no|never|don't|do not|doesn't|does not|without|closed|cannot)\b|نہیں|بند")
_INSTRUCTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+instructions|\bsystem\s*:|\bassistant\s*:"
    r"|\byou\s+are\s+(an?\s+)?(ai|assistant|language\s+model)|\brecord\s+that\b|\bpretend\b)"
)
_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9,
                 "دس": 10}  # fmt: skip
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_LONG_NUMBER = re.compile(r"\+?\d[\d\s-]{6,}\d")


@dataclass(frozen=True)
class Proposal:
    claim_type: str
    value: dict[str, Any]
    rule_id: str
    start: int
    end: int

    def span_sha256(self, text: str) -> str:
        return hashlib.sha256(text[self.start : self.end].encode("utf-8")).hexdigest()


Rule = Callable[[str], tuple[str, dict[str, Any]] | None]


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _WORD_NUMBERS.get(token.casefold())


def _admissions_en(s: str) -> tuple[str, dict[str, Any]] | None:
    low = s.casefold()
    if re.search(r"\badmissions?\b", low) and re.search(r"\b(open|apply|application|admission form|register)\b", low):
        online = bool(re.search(r"\bonline\b", low))
        return "public_workflow_signal", {"area": "admissions",
                                          "signal": "online admission form mentioned" if online
                                          else "admissions process announced"}  # fmt: skip
    return None


def _admissions_ur(s: str) -> tuple[str, dict[str, Any]] | None:
    if "داخل" in s and ("جاری" in s or "فارم" in s):
        return "public_workflow_signal", {"area": "admissions", "signal": "admissions process announced"}
    return None


def _fees_en(s: str) -> tuple[str, dict[str, Any]] | None:
    low = s.casefold()
    if re.search(r"\bfees?\b", low) and re.search(r"\b(challan|voucher|bank|deposit|installments?)\b", low):
        return "public_workflow_signal", {"area": "fees", "signal": "fee voucher or bank challan process described"}
    return None


def _fees_ur(s: str) -> tuple[str, dict[str, Any]] | None:
    if "فیس" in s and ("چالان" in s or "بینک" in s):
        return "public_workflow_signal", {"area": "fees", "signal": "fee voucher or bank challan process described"}
    return None


def _campuses_en(s: str) -> tuple[str, dict[str, Any]] | None:
    match = re.search(r"(?i)\b(?:we\s+(?:have|operate|run)|our)\b[^.]*?\b(\d{1,3}|[a-z]+)\s+campus(?:es)?\b", s)
    count = _number(match.group(1)) if match else None
    if count is not None and 1 <= count <= 500:
        return "campus_count", {"count": count}
    return None


def _campuses_ur(s: str) -> tuple[str, dict[str, Any]] | None:
    match = re.search(r"(\d{1,3}|ایک|دو|تین|چار|پانچ|چھ|سات|آٹھ|نو|دس)\s*کیمپس", s)
    count = _number(match.group(1)) if match and "ہمار" in s else None
    if count is not None and 1 <= count <= 500:
        return "campus_count", {"count": count}
    return None


def _contact_form_en(s: str) -> tuple[str, dict[str, Any]] | None:
    low = s.casefold()
    if re.search(r"\b(contact|enquiry|inquiry)\b", low) and re.search(r"\bform\b", low):
        return "public_contact_channel", {"channel": "website_form"}
    return None


def _phone_listed_en(s: str) -> tuple[str, dict[str, Any]] | None:
    if re.search(r"(?i)\b(call|phone|telephone|tel)\b", s) and _LONG_NUMBER.search(s):
        return "public_contact_channel", {"channel": "public_phone_listed"}  # the number itself is never kept
    return None


def _portal_en(s: str) -> tuple[str, dict[str, Any]] | None:
    if re.search(r"(?i)\b(parent|student)s?\s+portal\b", s):
        return "public_workflow_signal", {"area": "student_records", "signal": "parent or student portal mentioned"}
    return None


def _results_en(s: str) -> tuple[str, dict[str, Any]] | None:
    if re.search(r"(?i)\b(results?|report cards?)\b", s) and re.search(r"(?i)\bonline\b", s):
        return "public_workflow_signal", {"area": "reporting", "signal": "results published online"}
    return None


RULES: dict[str, Rule] = {
    "admissions_en": _admissions_en,
    "admissions_ur": _admissions_ur,
    "fees_en": _fees_en,
    "fees_ur": _fees_ur,
    "campuses_en": _campuses_en,
    "campuses_ur": _campuses_ur,
    "contact_form_en": _contact_form_en,
    "phone_listed_en": _phone_listed_en,
    "portal_en": _portal_en,
    "results_en": _results_en,
}


def _abstain_reason(sentence: str) -> str | None:
    if _INSTRUCTION.search(sentence):
        return "instruction_like_text"
    if _NEGATION.search(sentence):
        return "negated_statement"
    return None


def sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    for match in _SENTENCE.finditer(text):
        start, end = match.start(), match.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start >= 3:
            spans.append((start, min(end, start + MAX_SPAN)))
    return spans


@dataclass
class Extraction:
    proposals: list[Proposal]
    abstained: dict[str, int]


def extract(text: str, limit: int = MAX_CLAIMS_PER_RUN) -> Extraction:
    proposals: list[Proposal] = []
    abstained: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for start, end in sentences(text):
        sentence = text[start:end]
        matched = [(rule_id, out) for rule_id, rule in RULES.items() if (out := rule(sentence)) is not None]
        if not matched:
            continue
        reason = _abstain_reason(sentence)
        if reason is not None:
            abstained[reason] = abstained.get(reason, 0) + 1
            continue
        for rule_id, (claim_type, value) in matched:
            key = (claim_type, repr(sorted(value.items())))
            if key in seen:
                continue
            if len(proposals) >= limit:
                abstained["claim_limit_reached"] = abstained.get("claim_limit_reached", 0) + 1
                return Extraction(proposals, abstained)
            seen.add(key)
            proposals.append(Proposal(claim_type, value, rule_id, start, end))
    return Extraction(proposals, abstained)


def verify(text: str, proposal: Proposal, span_sha256: str | None = None) -> str | None:
    """None if the cited span alone supports exactly this typed claim; otherwise a rejection code."""
    if proposal.claim_type not in claims.CLAIMS:
        return "claim_type_not_allowed"
    try:
        claims.parse_claim(proposal.claim_type, proposal.value)
    except policy.PolicyViolation:
        return "claim_value_invalid"
    if not (0 <= proposal.start < proposal.end <= len(text)) or proposal.end - proposal.start > MAX_SPAN:
        return "span_out_of_bounds"
    if span_sha256 is not None and proposal.span_sha256(text) != span_sha256:
        return "span_mismatch"
    span = text[proposal.start : proposal.end]
    if _abstain_reason(span) is not None:
        return "span_not_assertive"
    rule = RULES.get(proposal.rule_id)
    if rule is None:
        return "unknown_rule"
    derived = rule(span)
    if derived is None or derived != (proposal.claim_type, proposal.value):
        return "span_does_not_support_claim"
    return None


def redact_excerpt(span: str) -> str:
    """Excerpts never carry contact details: emails and long numbers are masked."""
    return _LONG_NUMBER.sub("[number]", _EMAIL.sub("[email]", span))[:MAX_SPAN]
