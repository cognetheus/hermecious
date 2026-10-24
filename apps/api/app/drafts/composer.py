"""Deterministic, source-grounded first-contact drafts, `draft-contract-1.0` (P4.2, ADR-021). Pure; no models.

A draft is a list of typed sentences:
- **Static sentences** (greeting, identity, call to action, opt-out, sign-off) come from a reviewed template.
- **Observations** must cite one current, usable fact, and say only what its source says.
- **Capability sentences** must cite one sales-approved claim of the currently published offer revision.
- **Questions** come from the P3.2 brief's discovery questions for unknown areas.

The verifier re-checks the assembled text: sender identity, opt-out and ≤650 characters, and the absence of
links, contact details, names, prices, timelines, guarantees, deficiency claims and insults.

No model is configured, so no model output is used. Drafts are never sendable.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.signals.rubric import EvidenceFact

CONTRACT_VERSION = "draft-contract-1.0"
SENDER = {"organization": "CoderzHunt", "location": "Lahore"}
TEMPLATES = ("school_introduction_v1", "school_question_v1")
REVIEWED_LOCALES = ("en-PK",)
MAX_CHARS = 650
OPT_OUT = "If you would prefer not to hear from us, just reply STOP and we will not contact you again."

Category = Literal[
    "greeting", "identity", "observation", "generic", "capability", "question", "cta", "opt_out", "signoff"
]


class DraftError(ValueError):
    """A typed, user-safe reason (e.g. TEMPLATE_UNAVAILABLE, OFFER_CLAIM_UNAVAILABLE, VALIDATION_FAILED)."""

    def __init__(self, code: str, details: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or []


@dataclass(frozen=True)
class OfferClaim:
    offer_id: str
    revision_id: str
    capability_version: str
    content_sha256: str
    capability_code: str
    summary: str


@dataclass
class Sentence:
    category: Category
    text: str
    grounding: dict[str, Any] = field(default_factory=dict)


def _observation(fact: EvidenceFact) -> str | None:
    """Only what the cited source says. Never a deficiency, a tool or an internal process."""
    v = fact.value
    if fact.claim_type == "public_workflow_signal":
        if v.get("area") == "admissions":
            if v.get("signal") == "online admission form mentioned":
                return "We noticed that your public page mentions an online admission form."
            return "We noticed that your public page describes your admissions process."
        if v.get("area") == "fees":
            return "We noticed that your public page explains how fee vouchers or bank challans are paid."
        if v.get("area") == "reporting":
            return "We noticed that your school shares results online."
    if fact.claim_type == "campus_count" and isinstance(v.get("count"), int) and v["count"] >= 2:
        return f"We noticed that your school lists {v['count']} campuses."
    return None


_AREA_OF_CODE = (
    ("admission", "admissions"),
    ("fee", "fees"),
    ("payment", "fees"),
    ("report", "reporting"),
    ("record", "reporting"),
    ("result", "reporting"),
)


def _area(code: str) -> str | None:
    return next((area for needle, area in _AREA_OF_CODE if needle in code), None)


def compose(
    *,
    template_id: str,
    locale: str,
    facts: list[EvidenceFact],
    usable: set[str],
    claims: list[OfferClaim],
    questions: list[tuple[str, str]],
    snapshot_id: str | None,
) -> list[Sentence]:
    """`usable`: fact ids that are current and rights-usable now. `questions`: (signal key, question) for unknowns."""
    if template_id not in TEMPLATES:
        raise DraftError("TEMPLATE_UNAVAILABLE", [f"unknown template {template_id}"])
    if locale not in REVIEWED_LOCALES:
        raise DraftError("TEMPLATE_UNAVAILABLE", [f"no reviewed {locale} template"])
    if not claims:
        raise DraftError("OFFER_CLAIM_UNAVAILABLE", ["the campaign offer has no current sales-approved claim"])
    sentences = [
        Sentence("greeting", "Assalam-o-Alaikum,"),
        Sentence("identity", f"This is the {SENDER['organization']} team in {SENDER['location']}."),
    ]
    observed_area: str | None = None
    if template_id == "school_introduction_v1":
        chosen = None
        for fact in sorted(facts, key=lambda f: f.fact_id):
            text = _observation(fact) if fact.fact_id in usable else None
            if text:
                chosen = (fact, text)
                break
        if chosen is None:
            sentences.append(Sentence("generic", "We work with schools in Lahore on day-to-day administration."))
        else:
            fact, text = chosen
            observed_area = fact.value.get("area") if fact.claim_type == "public_workflow_signal" else None
            sentences.append(
                Sentence(
                    "observation",
                    text,
                    {
                        "fact_id": fact.fact_id,
                        "claim_type": fact.claim_type,
                        "source_record_id": fact.source_id,
                        "storage_class": fact.storage_class,
                        "observed_at": fact.observed_at.isoformat(),
                    },
                )
            )
        claim = next((c for c in claims if _area(c.capability_code) == observed_area), None) or claims[0]
        sentences.append(
            Sentence(
                "capability",
                f"Our team offers {claim.summary.rstrip('.')} for schools.",
                {
                    "offer_id": claim.offer_id,
                    "offer_revision_id": claim.revision_id,
                    "capability_code": claim.capability_code,
                    "capability_version": claim.capability_version,
                    "content_sha256": claim.content_sha256,
                },
            )
        )
    if questions:
        key, question = questions[0]
        sentences.append(Sentence("question", question, {"signal_snapshot_id": snapshot_id, "signal_key": key}))
    sentences += [
        Sentence("cta", "If it would help, could we share a short overview with you?"),
        Sentence("opt_out", OPT_OUT),
        Sentence("signoff", f"— {SENDER['organization']}, {SENDER['location']}"),
    ]
    return sentences


def static_sentences() -> list[Sentence]:
    """Reviewed template text an edit may keep, drop or reorder (never reword)."""
    return [
        Sentence("greeting", "Assalam-o-Alaikum,"),
        Sentence("identity", f"This is the {SENDER['organization']} team in {SENDER['location']}."),
        Sentence("generic", "We work with schools in Lahore on day-to-day administration."),
        Sentence("cta", "If it would help, could we share a short overview with you?"),
        Sentence("opt_out", OPT_OUT),
        Sentence("signoff", f"— {SENDER['organization']}, {SENDER['location']}"),
    ]


def candidates(
    *,
    facts: list[EvidenceFact],
    usable: set[str],
    claims: list[OfferClaim],
    questions: list[tuple[str, str]],
    snapshot_id: str | None,
) -> list[Sentence]:
    """Every sentence an edit may use now: reviewed template text, plus sentences grounded in current evidence."""
    library = static_sentences()
    for fact in sorted(facts, key=lambda f: f.fact_id):
        text = _observation(fact) if fact.fact_id in usable else None
        if text:
            grounding = {
                "fact_id": fact.fact_id,
                "claim_type": fact.claim_type,
                "source_record_id": fact.source_id,
                "storage_class": fact.storage_class,
                "observed_at": fact.observed_at.isoformat(),
            }
            library.append(Sentence("observation", text, grounding))
    for claim in claims:
        grounding = {
            "offer_id": claim.offer_id,
            "offer_revision_id": claim.revision_id,
            "capability_code": claim.capability_code,
            "capability_version": claim.capability_version,
            "content_sha256": claim.content_sha256,
        }
        library.append(Sentence("capability", f"Our team offers {claim.summary.rstrip('.')} for schools.", grounding))
    for key, question in questions:
        library.append(Sentence("question", question, {"signal_snapshot_id": snapshot_id, "signal_key": key}))
    return library


def canonical_text(text: str) -> str:
    """NFC with collapsed whitespace: the form used for parsing, rendering and content digests."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def parse(edited_text: str, library: list[Sentence]) -> list[Sentence]:
    """Decompose an edit into library sentences (longest match first). Anything else is `UNGROUNDED_TEXT`.

    Edits may drop, reorder or swap grounded sentences; they cannot introduce new wording, so every factual
    assertion still cites current evidence or a published claim.
    """
    text = canonical_text(edited_text)
    by_text: dict[str, Sentence] = {}
    for sentence in library:
        by_text.setdefault(canonical_text(sentence.text), sentence)
    options = sorted(by_text, key=len, reverse=True)
    out: list[Sentence] = []
    i = 0
    while i < len(text):
        match = next(
            (o for o in options if text.startswith(o, i) and (i + len(o) == len(text) or text[i + len(o)] == " ")),
            None,
        )
        if match is None:
            raise DraftError("UNGROUNDED_TEXT", [text[i : i + 60]])
        if any(s.text == by_text[match].text for s in out):
            raise DraftError("DUPLICATE_SENTENCE", [match[:60]])
        out.append(by_text[match])
        i += len(match) + 1
    if not out:
        raise DraftError("UNGROUNDED_TEXT", ["empty"])
    return out


_FORBIDDEN = [
    (re.compile(r"(?i)https?://|www\.|\.com\b|\.pk\b"), "link"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "email_address"),
    (re.compile(r"\+?\d[\d\s-]{6,}\d"), "phone_number"),
    (re.compile(r"(?i)\b(rs\.?|pkr|price|cost|discount|\d+\s*%|free trial|offer ends)\b"), "price_or_discount"),
    (
        re.compile(r"(?i)\b(guarantee\w*|within \d+|in \d+ (days|weeks)|go[- ]live|by (monday|next week))\b"),
        "commitment",
    ),
    (
        re.compile(
            r"(?i)\b(excel|paper[- ]based|manual(ly)?|outdated|no software|don'?t have|lack(s|ing)?|struggl\w*|"
            r"inefficien\w*|mess|chaos)\b"
        ),
        "deficiency_claim",
    ),
    (re.compile(r"(?i)\b(stupid|backward|poor|incompetent|old-fashioned)\b"), "insulting_wording"),
    (re.compile(r"\b(Mr|Mrs|Ms|Dr|Sir|Madam|Principal)\.?\s+[A-Z][a-z]+"), "personal_name"),
    (re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f‪-‮⁦-⁩]"), "unsafe_character"),
    (re.compile(r"(?i)\b(ignore (all|previous)|system:|assistant:)"), "instruction_text"),
]
_STATIC = {"greeting", "identity", "generic", "cta", "opt_out", "signoff"}


def render(sentences: list[Sentence]) -> str:
    return unicodedata.normalize("NFC", " ".join(s.text for s in sentences))


def verify(sentences: list[Sentence]) -> list[str]:
    """Empty list = valid. Every rule is re-checked on the final text, whatever produced it."""
    problems: list[str] = []
    text = render(sentences)
    if SENDER["organization"] not in text or not any(s.category == "identity" for s in sentences):
        problems.append("missing_sender_identity")  # the identity sentence itself, not only the sign-off
    if OPT_OUT not in text:
        problems.append("missing_opt_out")
    if len(text) > MAX_CHARS:
        problems.append("too_long")
    for pattern, code in _FORBIDDEN:
        if pattern.search(text):
            problems.append(code)
    for s in sentences:
        if s.category not in _STATIC and not s.grounding:
            problems.append(f"ungrounded_{s.category}")
        if s.category == "observation" and not s.grounding.get("fact_id"):
            problems.append("observation_without_fact")
        if s.category == "capability" and not s.grounding.get("offer_revision_id"):
            problems.append("capability_without_offer_claim")
    if not any(s.category == "question" for s in sentences) and not any(s.category == "cta" for s in sentences):
        problems.append("missing_question_or_cta")
    return sorted(set(problems))


def to_json(sentences: list[Sentence]) -> list[dict[str, Any]]:
    return [asdict(s) for s in sentences]
