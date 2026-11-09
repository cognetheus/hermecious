"""Deterministic grounded reply proposer `reply-rules-1.0` (P6.2, ADR-032). Pure: no I/O, no model, no tools.

Order of decisions:
1. **Safety first** (from the P6.1 observation): opt-out, abuse, injection, a request for a person, sensitive personal
   data, unsupported language, ambiguous intent or unavailable content -> no draft (abstain) with a visible reason.
   The human-request flag wins even when a details question is also present.
2. **What was asked:** capabilities (admissions, fees, attendance, ...) and commercial topics (price, discount,
   migration, timelines and guarantees, integrations, SLAs, ROI). Each needs a current approved claim from the pinned
   knowledge snapshot. Anything unanswerable -> abstain with the missing claim named; nothing is ever improvised.
3. **Draft:** fixed template sentences plus approved claim text quoted verbatim, each with a citation. English only:
   approved wording exists in English only, so other languages get an English draft flagged `language_fallback`.
4. **Verify** the final text independently: any sentence that asserts a capability, price, discount, timeline,
   guarantee, integration, migration, SLA or ROI without a citation from the snapshot turns the result into an
   abstention (`ungrounded_assertion`). The same verifier will check any future model output.

The prospect's own statements become `confirmed_facts` quoted from the message, marked `prospect_stated` and
unverified; they never change an account record.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.replies.knowledge import UNIT_LABEL, Knowledge
from app.replies.schema import MAX_REPLY_CHARS, SCHEMA_VERSION, InvalidProposal, ReplyProposal

COMPOSER_VERSION = "reply-rules-1.0"
POLICY_VERSION = "reply-policy-1.0"
SIGNOFF = "— CoderzHunt team"

# Product vocabulary -> canonical capability codes (P1.3 codes). Matching a word is not a claim; a claim comes only
# from the published offer.
CAPABILITIES: dict[str, re.Pattern[str]] = {
    "admissions_intake": re.compile(r"(?i)\badmissions?\b|\bdakh(?:i)?la\b|داخل[ہے]"),
    "fee_tracking": re.compile(r"(?i)\bfees?\b(?!\s+(?:bhi\s+)?(?:parents|time))|\bchallan\b|\barrears?\b|فیس"),
    "attendance": re.compile(r"(?i)\battendance\b|\bha+zi?ri\b|\bhaziri\b|حاضری"),
    "results": re.compile(r"(?i)\bresults?\b|\breport\s+cards?\b|\bexam\s+results?\b|رزلٹ|نتائج"),
    "timetable": re.compile(r"(?i)\btime\s*tables?\b|ٹائم\s*ٹیبل"),
    "transport": re.compile(r"(?i)\btransport\b|\bbus(?:es)?\b|\bvan\b"),
    "parent_app": re.compile(r"(?i)\bparents?\s+(?:app|portal)\b|\bmobile\s+app\b"),
    "payroll": re.compile(r"(?i)\bpayroll\b|\bsalar(?:y|ies)\b|تنخواہ"),
}
# Commercial topics that are always grounded assertions. P1.3 publication forbids commitments in claims, so only
# `price` can ever be answered (by an approved price rule); the rest always need a person.
TOPICS: dict[str, re.Pattern[str]] = {
    "price": re.compile(
        r"(?i)\bpric(?:e|es|ing)\b|\bcosts?\b|\bcharges?\b|\brates?\b|\bhow\s+much\b|\bkitn[ae]\s+ka\b"
        r"|\bqeemat\b|قیمت|\bfee\s+for\s+(?:the\s+)?(?:software|system)\b"
    ),
    "discount": re.compile(r"(?i)\bdiscounts?\b|\bfree\s+trial\b|\bconcession\b|رعایت"),
    "migration": re.compile(r"(?i)\bmigrat\w*|\bdata\s+(?:transfer|shift\w*)|\bpurana\s+data\b|\bimport\s+our\b"),
    "timeline_guarantee": re.compile(
        r"(?i)\bguarantee\w*|\bdeliver\w*\s+by\b|\bdeadline\b|\bby\s+(?:monday|tuesday|wednesday|thursday|friday|"
        r"saturday|sunday|tomorrow|next\s+week|november|december|january|\d{1,2}(?:st|nd|rd|th)?)\b"
        r"|\bwithin\s+\d+|\bhow\s+(?:long|soon)\b|\bkab\s+tak\b|گارنٹی"
    ),
    "integration": re.compile(
        r"(?i)\bintegrat\w*|\bapi\b|\bjazzcash\b|\beasypaisa\b|\bbank\s+link\w*|\bconnect\s+with\b"
    ),
    "sla": re.compile(r"(?i)\buptime\b|\bsla\b|\b24\s*/\s*7\b|\bsupport\s+hours\b"),
    "roi": re.compile(r"(?i)\broi\b|\bsave\s+(?:money|time|\d)|\breturn\s+on\b"),
}
# Statements a correspondent makes about themselves (quoted, unverified).
FACTS: list[tuple[str, re.Pattern[str]]] = [
    (
        "current_tool",
        re.compile(
            r"(?i)\b(?:we(?:'re| are)?\s+(?:using|use)|we\s+still\s+(?:use|do\s+\w+\s+on)|using|hum\s+\w*\s*"
            r"(?:use|istemal)\s+kar\w*)\s+(?:an?\s+|the\s+)?(?:excel|google\s+sheets|registers?|paper"
            r"|manual\s+registers?)\b|\bexcel\s+(?:use|istemal)\s+kar\w*|\bon\s+excel\b"
        ),
    ),
    ("campus_count", re.compile(r"(?i)\b(?:\d{1,2}|one|two|three|four|five)\s+campus(?:es)?\b")),
    ("student_count", re.compile(r"(?i)\b\d{2,5}\s+(?:students|bachay|bachon|bachche)\b")),
    (
        "decision_maker",
        re.compile(
            r"(?i)\b(?:principal|owner|board|director)\s+(?:decides|will\s+decide|makes\s+the\s+decision)\b"
            r"|\b(?:she|he)\s+decides\b"
        ),
    ),
    (
        "timing",
        re.compile(
            r"(?i)\bafter\s+(?:the\s+)?(?:exams?|admissions?|results?|eid|ramzan|summer)\b"
            r"|\b(?:exams?|admission|ramzan|eid)\s+ke\s+baad\b"
        ),
    ),
]
# An independent check on the final text: assertions of any of these need a citation.
_ASSERTION = re.compile(
    r"(?i)\b(?:pkr|rs\.?|rupees?|price|cost|discount|free\s+trial|guarantee\w*|deliver\w*|deadline|within\s+\d+|"
    r"\d+\s*(?:days?|weeks?|months?|%)|integrat\w*|migrat\w*|uptime|sla|24\s*/\s*7|roi|save[sd]?\b|"
    r"we\s+(?:support|offer|provide|include|handle|manage|track|cover)|our\s+(?:system|software|product)\s+"
    r"(?:supports|offers|provides|includes|handles|manages|tracks|covers))"
)

# The proposer's own injection check (independent of P6.1): inbound text is data, never instructions.
_INJECTION = re.compile(
    r"(?i)\bignore\s+(?:all\s+|the\s+|any\s+|your\s+)?(?:prior|previous|above|earlier|system)?\s*"
    r"(?:rules|instructions|prompts?|polic(?:y|ies))\b|\bsystem\s+(?:prompt|admin)\b|\b(?:curl|wget|bash|sudo)\b"
    r"|\bdisable\s+(?:the\s+)?(?:approval|safety|filters?|checks?)\b|\byou\s+are\s+now\b|\bact\s+as\b"
)

TEMPLATE = {
    "greeting": "Thank you for your message.",
    "interested": "We are glad this could be useful for your school.",
    "details_intro": "Here is what our currently published offer covers:",
    "demo": "We would be happy to arrange a demonstration; which day and time suit you?",
    "defer": "We understand. When would be a good time to reconnect?",
    "objection": "Thank you for sharing this; it helps us understand your situation.",
    "objection_question": "What would matter most to your school in a system like this?",
    "not_interested": "Thank you for letting us know. We will not follow up unless you ask us to.",
    "which_area": "Which part of school administration matters most to you right now?",
}


@dataclass
class Inputs:
    message_id: str
    text: str | None
    content_state: str
    observation: dict[str, Any] | None  # the P6.1 intent.v1 observation (current classifier version) or None
    knowledge: Knowledge
    matched_contact: bool
    now: datetime


@dataclass
class _Draft:
    sentences: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)

    def add(self, text: str, cite: dict[str, Any] | None = None) -> None:
        self.sentences.append(text)
        if cite is not None:
            self.citations.append(cite | {"sentence": len(self.sentences) - 1})


def asked(text: str) -> tuple[list[str], list[str]]:
    capabilities = [code for code, p in CAPABILITIES.items() if p.search(text)]
    topics = [code for code, p in TOPICS.items() if p.search(text)]
    if (
        "price" in topics
        and "fee_tracking" in capabilities
        and not TOPICS["price"].search(CAPABILITIES["fee_tracking"].sub(" ", text))
    ):
        topics.remove("price")  # "fees" means the school's fee module here, not our price
    return capabilities, topics


def stated_facts(message_id: str, text: str) -> list[dict[str, Any]]:
    out = []
    for code, pattern in FACTS:
        m = pattern.search(text)
        if m:
            out.append({"code": code, "text": text[m.start() : m.end()], "message_id": message_id,
                        "start": m.start(), "end": m.end(), "attribution": "prospect_stated",
                        "verified": False})  # fmt: skip
    return out


def ungrounded(sentences: list[str], citations: list[dict[str, Any]], knowledge: Knowledge) -> list[int]:
    """Indexes of sentences that assert something commercial without a valid citation from this snapshot."""
    cited = {c["sentence"] for c in citations if c["digest"] in knowledge.digests}
    return [i for i, s in enumerate(sentences) if _ASSERTION.search(s) and i not in cited]


def _abstain(i: Inputs, codes: list[str], action: str, *, missing: list[str] | None = None,
             facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    return {"status": "abstained", "proposed_reply": None, "reply_language": None, "codes": codes, "action": action,
            "missing": missing or [], "facts": facts or [], "citations": [], "questions": []}  # fmt: skip


def decide(i: Inputs) -> dict[str, Any]:
    obs = i.observation
    if obs is None:
        return _abstain(i, ["intent_missing"], "manual_triage")
    flags = set(obs["safety_flags"])
    if "explicit_opt_out" in flags:
        return _abstain(i, ["opt_out"], "opt_out_review_no_reply")
    if "abusive_or_threatening" in flags:
        return _abstain(i, ["abusive"], "abuse_review_no_reply")
    if "injection_attempt_suspected" in flags or (i.text is not None and _INJECTION.search(i.text)):
        return _abstain(i, ["injection_suspected"], "manual_triage")
    if "human_escalation_requested" in flags:  # wins even when a details question is present
        return _abstain(i, ["human_requested"], "human_handoff")
    if "possible_sensitive_personal_data" in flags:
        return _abstain(i, ["sensitive_personal_data"], "manual_triage")  # nothing quoted, nothing drafted
    if i.content_state != "available" or i.text is None:
        return _abstain(i, ["content_unavailable"], "manual_triage")
    if "unsupported_language" in flags or obs["language"] == "unknown":
        return _abstain(i, ["unsupported_language"], "manual_triage")
    facts = stated_facts(i.message_id, i.text)
    if not i.matched_contact:
        return _abstain(i, ["unmatched_contact"], "manual_triage", facts=facts)
    capabilities, topics = asked(i.text)
    k = i.knowledge
    claims = {c.key: c for c in k.claims}
    missing = [t for t in topics if t != "price"] + [c for c in capabilities if c not in claims]
    if "price" in topics and not k.prices:
        missing.append("price")
    if (capabilities or topics) and k.offer_id is None:
        return _abstain(i, ["no_published_offer"], "manual_review_missing_claim", missing=sorted(set(missing)),
                        facts=facts)  # fmt: skip
    if missing:  # named even when the intent is unclear: the reviewer needs to know what cannot be answered
        return _abstain(i, ["missing_approved_claim"], "manual_review_missing_claim", missing=sorted(set(missing)),
                        facts=facts)  # fmt: skip
    if obs["primary_intent"] == "ambiguous":  # never a draft for an unclear message
        return _abstain(i, ["ambiguous_intent"], "manual_triage", facts=facts)
    d = _Draft()
    d.add(TEMPLATE["greeting"])
    intent = obs["primary_intent"]
    questions: list[str] = []
    if intent == "interested":
        d.add(TEMPLATE["interested"])
    if intent in ("needs_details", "interested", "request_demo"):
        wanted = [claims[c] for c in capabilities]
        if intent == "needs_details" and not wanted and "price" not in topics:
            wanted = list(k.claims[:3])
            if wanted:
                d.add(TEMPLATE["details_intro"])
            else:
                return _abstain(i, ["no_published_offer"], "manual_review_missing_claim", facts=facts)
        for claim in wanted:
            line = claim.summary.rstrip(".") + "."
            if claim.limitations:
                line += " Limitations: " + "; ".join(claim.limitations).rstrip(".") + "."
            d.add(line, {"kind": "capability", "key": claim.key, "digest": claim.digest})
        if "price" in topics:
            for rule in k.prices:
                d.add(f"Approved pricing: {rule.description.rstrip('.')} (PKR {rule.amount} {UNIT_LABEL[rule.unit]}).",
                      {"kind": "price_rule", "key": rule.key, "digest": rule.digest})  # fmt: skip
        if intent == "request_demo":
            d.add(TEMPLATE["demo"])
        elif not capabilities and "price" not in topics:
            d.add(TEMPLATE["which_area"])
            questions.append(TEMPLATE["which_area"])
    elif intent == "defer":
        d.add(TEMPLATE["defer"])
        questions.append(TEMPLATE["defer"])
    elif intent == "objection":
        d.add(TEMPLATE["objection"])
        d.add(TEMPLATE["objection_question"])
        questions.append(TEMPLATE["objection_question"])
    elif intent == "not_interested":
        d.add(TEMPLATE["not_interested"])
    d.add(SIGNOFF)
    if ungrounded(d.sentences, d.citations, k):
        return _abstain(i, ["ungrounded_assertion"], "manual_triage", facts=facts)
    text = " ".join(d.sentences)
    if len(text) > MAX_REPLY_CHARS:
        return _abstain(i, ["ungrounded_assertion"], "manual_triage", facts=facts)
    return {"status": "proposed", "proposed_reply": text, "reply_language": "en", "codes": [], "action": "review_draft",
            "missing": [], "facts": facts, "citations": d.citations, "questions": questions}  # fmt: skip


def propose(i: Inputs) -> ReplyProposal:
    """The validated reply.v1 proposal for these inputs (deterministic: same inputs, same proposal)."""
    obs = i.observation or {}
    outcome = decide(i)
    language = obs.get("language", "unknown")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "status": outcome["status"], "proposed_reply": outcome["proposed_reply"],
        "reply_language": outcome["reply_language"],
        "language_fallback": outcome["status"] == "proposed" and language != "english",
        "inbound_language": language, "intent": obs.get("primary_intent", "ambiguous"),
        "intent_observation_id": obs.get("observation_id"), "safety_flags": list(obs.get("safety_flags", [])),
        "confirmed_facts": outcome["facts"], "open_questions": outcome["questions"],
        "missing_claims": outcome["missing"], "recommended_action": outcome["action"],
        "escalate": outcome["action"] != "review_draft", "citations": outcome["citations"],
        "snapshot": {"offer_id": i.knowledge.offer_id, "offer_revision": i.knowledge.revision,
                     "content_sha256": i.knowledge.content_sha256, "claims_digest": i.knowledge.claims_digest,
                     "locale": "en"},
        "abstention_codes": outcome["codes"], "composer_version": COMPOSER_VERSION, "policy_version": POLICY_VERSION,
        "model_version": None, "prompt_version": None, "tool_calls": 0, "generated_at": i.now.isoformat(),
    }  # fmt: skip
    try:
        return ReplyProposal.validated(payload, i.text or "", i.knowledge.digests)
    except InvalidProposal:  # pragma: no cover  # defence in depth: never return an unvalidated draft
        fallback = _abstain(i, ["ungrounded_assertion"], "manual_triage")
        payload |= {"status": "abstained", "proposed_reply": None, "reply_language": None, "language_fallback": False,
                    "confirmed_facts": [], "open_questions": [], "missing_claims": [], "citations": [],
                    "recommended_action": fallback["action"], "escalate": True,
                    "abstention_codes": fallback["codes"]}  # fmt: skip
        return ReplyProposal.validated(payload, i.text or "", i.knowledge.digests)
