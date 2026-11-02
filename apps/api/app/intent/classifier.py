"""Deterministic intent classifier, `intent.v1` (P6.1, ADR-031). Pure: no I/O, no model, no side effects.

It labels a signed inbound message for **human review**. Nothing it returns is executable: the recommended action
is a read-only string from a fixed allowlist, and the classifier never sends, suppresses, grants consent or
schedules anything. The P5.2/P4.3 STOP path remains the authority for suppression.

**Pipeline:**
1. Fold the text for matching while keeping a map back to the original offsets: NFKC, Cyrillic and Greek
   look-alikes, Arabic-to-Urdu letter variants, case. Zero-width and bidi controls are dropped.
2. Match high-precision patterns per intent in English, Roman Urdu and Urdu script.
3. Opt-out matches that are quoted or reported ("sent me the text "stop"") or negated ("don't stop", "روکیں
   نہیں") do not count.
4. Pick the primary by a fixed precedence; keep every safety flag whatever the primary is.
5. Return evidence spans anchored to the original text.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.intent.schema import ACTION_FOR, PRECEDENCE, IntentObservation, Span

CLASSIFIER_VERSION = "intent-rules-1.0"
_INVISIBLE = {"​", "‌", "‍", "⁠", "﻿", "‎", "‏", "‪", "‫", "‬",
              "‭", "‮", "⁦", "⁧", "⁨", "⁩"}  # fmt: skip
_CONFUSABLE = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j", "к": "k",
    "м": "m", "т": "t", "в": "b", "н": "h", "А": "a", "Е": "e", "О": "o", "Р": "p", "С": "c", "Т": "t", "Ѕ": "s",
    "Х": "x", "К": "k", "М": "m", "Н": "h", "В": "b", "ο": "o", "Ο": "o", "α": "a", "ρ": "p", "Τ": "t",
    "ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ",
})  # fmt: skip


def fold(text: str) -> tuple[str, list[int]]:
    """A matching copy of `text` and, for each of its characters, the index of the original character."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch in _INVISIBLE or unicodedata.category(ch) == "Cf":
            continue
        for c in unicodedata.normalize("NFKC", ch).translate(_CONFUSABLE).casefold():
            out.append(c)
            index.append(i)
    return "".join(out), index


def _p(*patterns: str) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


_MSG = r"(?:message|messages|msg|msgs|mesej|massage|sms|text)"
_KAR = r"(?:ka?r\w*|bhej\w*)"  # kar/kr spellings
PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "opt_out": _p(
        r"^\W*stop\W*$",
        r"\bstop\s+(?:messag\w*|text\w*|contact\w*|send\w*|spamm\w*|it|this)\b",
        r"\bplease\s+stop\b",
        r"\bunsubscrib\w*",
        r"\bopt[\s-]?out\b",
        r"\bremove\s+(?:our|my|this)\s+(?:number|contact)",
        r"\b(?:do\s+not|don'?t)\s+(?:contact|message|text|call)\s+(?:us|me)\b",
        r"\bno\s+more\s+messages\b",
        rf"\b{_MSG}\s+(?:mat|na|nah)\s+{_KAR}",
        r"\bdobara\b.{0,25}?\b(?:mat|na)\s+ka?r",
        r"\bband\s+kar(?:o|ein|en|dein|do|iye)\b",
        r"\b(?:number|nmbr)\s+(?:list\s+se\s+)?hata\s*d(?:ein|o|en)",
        r"\brabta\s+(?:mat|na)\s+kar",
        r"(?:میسج|پیغام)\s+(?:نہ|مت)\s+(?:کر|بھیج)",
        r"رابطہ\s+(?:نہ|مت)\s+کر",
        r"(?:^|\s)بند\s+کر(?:یں|و|دیں)",
        r"نمبر.{0,20}?ہٹا\s*د",
        r"\bun\s*sub\w*",
        r"\b(?:list|fehrist)\s+se\s+(?:nikal|hata)\w*",
        r"(?:لسٹ|فہرست)\s+سے\s+(?:نکال|ہٹا)",
        r"(?:messages?|msgs?|میسجز?|پیغامات?)\s+(?:نہ|مت)\s+(?:بھیج|کر)",
    ),
    "abusive": _p(
        r"\bscam(?:mer)?s?\b",
        r"\bfraud\b",
        r"\bidiots?\b",
        r"\bstupid\b",
        r"\bget\s+lost\b",
        r"\breport\s+you\b",
        r"\bpolice\b",
        r"\bliars?\b",
        r"\bbakwas\b",
        r"\bchor\b",
        r"\bdhoke\s*baz\b",
        r"\bbewa?qoof\b",
        r"دھوکے\s*باز",
        r"بکواس",
        r"فراڈ",
        r"پولیس",
    ),
    "request_demo": _p(
        r"\bdemo\b",
        r"\bsee\s+how\s+it\s+works\b",
        r"\bshow\s+(?:us|me)\s+(?:how|a\s+demo)\b",
        r"\bdikha(?:yein|ein|o|ain|\s+sakte)\b",
        r"\bkaise\s+kaam\s+karta\b",
        r"ڈیمو",
        r"دکھا(?:ئیں|\s+سکتے)",
        r"کیسے\s+کام",
        r"\bwalk\s*through\b",
        r"\bsee\s+it\s+(?:working|in\s+action)\b",
    ),
    "needs_details": _p(
        r"\bhow\s+much\b",
        r"\bpric(?:e|es|ing)\b",
        r"\bcosts?\b",
        r"\bfees?\b",
        r"\bfeatures?\b",
        r"\bdetails\b",
        r"\bbrochure\b",
        r"\bmodules?\b",
        r"\bdoes\s+it\s+(?:handle|have|support)\b",
        r"\bqeemat\b",
        r"\bkitn[ei]\s+(?:paise|fees?)\b",
        r"\bkitni\b",
        r"\brate\b",
        r"قیمت",
        r"تفصیلات",
        r"فیس",
        r"بتائیں",
        r"\bdetail\b",
        r"\bpa?c?kage\b",
    ),
    "human_request": _p(
        r"\b(?:speak|talk)\s+(?:to|with)\s+(?:a\s+|your\s+)?(?:person|human|someone|manager|principal|"
        r"representative|agent)\b",
        r"\b(?:have|ask)\s+someone\s+call\b",
        r"\bcall\s+(?:me|us|our\s+principal)\b",
        r"\bsomeone\s+call\b",
        r"\bbaat\s+karwa",
        r"\bcall\s+kar(?:ein|en|e|o|iye|ain)\b",
        r"\bmujhe\s+call\b",
        r"بات\s+کروا",
        r"فون\s+کر(?:یں|و)",
        r"\b(?:speak|talk)\s+(?:to|with)\s+(?:an?\s+)?(?:actual|real)\s+(?:person|human)\b",
        r"\bcall\s+(?:the\s+)?(?:principal|owner|manager)\b",
        r"\b(?:insaan|banda|bande|sahab|sahiba|principal|owner|manager)\b.{0,15}?\bse\s+baat\s+kar",
        r"(?:صاحب|صاحبہ|پرنسپل|مینیجر|انسان|نمائندے|نمائندہ|principal|owner|manager).{0,15}?سے\s+(?:بات|فون\s+پر)",
        r"کال\s+کر(?:یں|و|دیں)",
        r"\bcall\s+ka?r\s+l\w*",
        r"کال\s+کر\s+ل",
    ),
    "objection": _p(
        r"\balready\s+(?:use|have)\b",
        r"\b(?:too\s+)?expensive\b",
        r"\bcostly\b",
        r"\bcan'?t\s+afford\b",
        r"\b(?:don'?t|do\s+not)\s+trust\b",
        r"\bno\s+budget\b",
        r"\bpehle\s+se\b",
        r"\bmehen?ga\b",
        r"\bmehngi\b",
        r"\bnahi\s+chala\s+sakta\b",
        r"\bbharosa\s+nahi\b",
        r"پہلے\s+سے",
        r"مہنگ[ای]",
        r"نہیں\s+چلا\s+سکت",
        r"\banother\s+vendor\b",
        r"\balready\s+paid\b",
        r"\b(?:not|arent|aren\'t|isnt|isn\'t)\s+(?:very\s+)?(?:computer|tech)[\s-]*savvy\b",
        r"\bmeh[ae]?nga\b",
        r"\bbudget\s+nahi\b",
        r"بجٹ\s+نہیں",
        r"کمپیوٹر.{0,20}?نہیں\s+آتا",
    ),
    "defer": _p(
        r"\bbusy\b",
        r"\blater\b",
        r"\bnext\s+(?:month|week|year)\b",
        r"\bafter\s+(?:the\s+)?(?:exams?|admissions?)\b",
        r"\bnot\s+now\b",
        r"\bin\s+(?:january|february|march|april|may|june|july|august|september|october|"
        r"november|december)\b",
        r"\babhi\s+nahi\b",
        r"\bke\s+baad\b",
        r"\bbaad\s+mein\b",
        r"\bagle\s+(?:mahine|hafte|saal)\b",
        r"مصروف",
        r"اگلے\s+(?:مہینے|ہفتے|سال)",
        r"کے\s+بعد",
        r"ابھی\s+نہیں",
        r"جنوری",
    ),
    "not_interested": _p(
        r"\bnot\s+interested\b",
        r"\bno\s+thank(?:s|\s+you)\b",
        r"\b(?:don'?t|do\s+not)\s+need\b",
        r"\bnot\s+for\s+us\b",
        r"\binterest\s+nahi\b",
        r"\bzaroorat\s+nahi\b",
        r"\bnahi\s+chahiye\b",
        r"\bdilchaspi\s+nahi\b",
        r"دلچسپی\s+نہیں",
        r"ضرورت\s+نہیں",
        r"نہیں\s+چاہیے",
        r"\bnot\s+looking\s+for\b",
        r"\bzar[ou]{1,2}rat\s+nahi",
        r"\binterest\s+نہیں",
    ),
    "interested": _p(
        r"(?<!not\s)\binterested\b",
        r"\bsounds\s+good\b",
        r"\buseful\b",
        r"\bwe'?d\s+like\b",
        r"\binterest\s+hai\b",
        r"\bdilchaspi\s+hai\b",
        r"\bkaam\s+ka\b",
        r"\bzabardast\b",
        r"\bacha\s+lag\b",
        r"\btheek\s+hai\b",
        r"دلچسپی\s+ہے",
        r"فائدہ\s+مند",
        r"اچھا\s+لگ",
        r"\binteresting\b",
        r"\bcould\s+(?:actually\s+|really\s+)?help\b",
        r"\blooks\s+(?:good|great|useful)\b",
        r"ایسی\s+ہی\s+چیز",
        r"بہت\s+اچھا",
    ),
}
_REQUEST_CUE = re.compile(
    r"\?|؟|\b(?:what|how|does|do\s+you|can\s+you|tell|send|share|kya|kitn\w*|bata\w*|bhej\w*)\b|کیا|کتن|بتا|بھیج"
)
_WEAK_DETAILS = ("needs_details:3", "needs_details:7", "needs_details:15")
_NEGATED_STOP = re.compile(
    r"(?:\b(?:don'?t|do\s+not|no\s+need\s+to|never)\s+stop\b|\bband\s+(?:mat|na)\s+kar|روکیں\s+نہیں|بند\s+نہ\s+کر"
    r"|\bmat\s+rok)"
)
_REPORTED = re.compile(r"\b(?:sent\s+me|example|likh\s+(?:ke|kar)|bheja\s+tha|said|says|wrote)\b|مثال|لکھ\s+کر")
_INJECTION = re.compile(
    r"ignore\s+(?:all\s+|the\s+|any\s+)?(?:prior|previous|above|earlier)\s+instructions|system\s+admin|"
    r"disable\s+(?:the\s+)?(?:approval|safety|filters?)|you\s+are\s+(?:an?\s+)?(?:ai|assistant|bot)|"
    r"send\s+me\s+a\s+message|whatsapp\s+this\s+number|سسٹم\s+ایڈمن"
)
_SENSITIVE = re.compile(
    r"\d[\d\s-]{3,}\d|\b(?:my\s+(?:son|daughter|child|kid)|meri\s+beti|mera\s+beta|roll\s+(?:number|no))\b"
    r"|میرا\s+بیٹا|میری\s+بیٹی"
)
_CONTRACTION = re.compile(r"(?<=\w)['’](?=\w)")
_URDU = re.compile(r"[؀-ۿ]")
_LATIN_WORD = re.compile(r"[a-z]{2,}")
_ROMAN_URDU = frozenset(  # word lists read better than 150-item literals
    "hai hain ka ki ke nahi nahin karein karen kar dein se mein hum hamein hamare aap ji jee kya kaun abhi baad "  # noqa: SIM905
    "bhej karna mat na ye acha theek shukriya zaroorat kitne qeemat dobara rabta dikha chahiye kab hoga lagta "
    "band tum log bakwas paas pehle bohat mehenga insaan baat karwa mujhe meri beti agle mahine dilchaspi haan "
    "assalam alaikum koi banda kisi likh bheja tha raha karo hata liye sakte dikhayein kaise karta hun hoon "
    "zabardast kare pe".split()
)
_ENGLISH = frozenset(
    "the a an we us our you your is are be this that it to of for and or but no not yes please thanks thank can "  # noqa: SIM905
    "could would like do does have has how what who when much send me my i in on at with from about stop message "
    "messages contact again number list remove price cost fee fees demo details school student interested need "
    "busy later next month week after exams admissions call speak person manager principal ok okay hello received "
    "sounds good useful already use system expensive trust records unsubscribe".split()
)


@dataclass
class _Hit:
    intent: str
    start: int
    end: int
    reason: str


@dataclass
class Result:
    primary: str
    secondary: list[str]
    flags: list[str]
    language: str
    confidence: str
    requires_human_review: bool
    spans: list[Span] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def language_of(folded: str) -> str:
    urdu = len(_URDU.findall(folded))
    words = _LATIN_WORD.findall(folded)
    if urdu >= 2 and words:
        return "mixed"
    if urdu >= 2:
        return "urdu_script"
    if not words:
        return "unknown"
    if any(w in _ROMAN_URDU for w in words):
        return "roman_urdu"
    if len(words) >= 3 and not any(w in _ENGLISH for w in words):
        return "unsupported"
    return "english"


def _quoted(folded: str, start: int) -> bool:
    """Inside an open quotation, or just after a reporting cue. Apostrophes inside words (don't, I'm) are not
    quotation marks."""
    before = _CONTRACTION.sub("", folded[:start])
    if sum(before.count(q) for q in ('"', "“", "”", "'", "«", "»")) % 2 == 1:
        return True
    return _REPORTED.search(folded[max(0, start - 40) : start]) is not None


def classify(text: str) -> Result:
    folded, index = fold(text)
    hits: list[_Hit] = []
    for intent, patterns in PATTERNS.items():
        for n, pattern in enumerate(patterns):
            for m in pattern.finditer(folded):
                hits.append(_Hit(intent, m.start(), m.end(), f"{intent}:{n}"))
    if not _REQUEST_CUE.search(folded):
        hits = [h for h in hits if h.reason not in _WEAK_DETAILS]
    flags: set[str] = set()
    reasons: list[str] = []
    negated = _NEGATED_STOP.search(folded) is not None
    opt_outs = []
    for h in [h for h in hits if h.intent == "opt_out"]:
        if negated and h.reason in ("opt_out:0", "opt_out:1", "opt_out:2", "opt_out:10", "opt_out:15"):
            reasons.append("opt_out_negated")
        elif _quoted(folded, h.start):
            reasons.append("opt_out_quoted_or_reported")
        else:
            opt_outs.append(h)
    hits = [h for h in hits if h.intent != "opt_out"] + opt_outs
    # "bakwas band karo" is an insult ("shut up"), not a request to stop contact.
    hits = [h for h in hits if not (h.intent == "opt_out" and folded[max(0, h.start - 8) : h.start].strip()
                                    in ("bakwas", "بکواس"))]  # fmt: skip
    language = language_of(folded)
    if language == "unsupported":
        flags.add("unsupported_language")
        hits = []
    if _INJECTION.search(folded):
        flags.add("injection_attempt_suspected")
        hits = [h for h in hits if h.intent not in ("opt_out", "request_demo", "interested")]
    if _SENSITIVE.search(folded):
        flags.add("possible_sensitive_personal_data")
    found = {h.intent for h in hits}
    if "interested" in found and "not_interested" in found:
        found.discard("interested")
    if "opt_out" in found:
        flags.add("explicit_opt_out")
    if "human_request" in found:
        flags.add("human_escalation_requested")
    if "abusive" in found:
        flags.add("abusive_or_threatening")
    if "injection_attempt_suspected" in flags:
        found.discard("needs_details")
        found.discard("human_request")
        flags.discard("human_escalation_requested")
    ordered = [i for i in PRECEDENCE if i in found]
    primary = ordered[0] if ordered else "ambiguous"
    secondary = ordered[1:]
    if not ordered:
        confidence = "low" if reasons or flags else "unknown"
    elif secondary:
        confidence = "medium"
    else:
        confidence = "high"
    review = primary in ("opt_out", "human_request", "abusive", "ambiguous") or bool(flags) or confidence != "high"
    spans = [
        Span(start=index[h.start], end=index[h.end - 1] + 1, text=text[index[h.start] : index[h.end - 1] + 1],
             reason=h.reason)
        for h in sorted(hits, key=lambda h: (h.start, h.reason))
        if h.intent in found and h.end > h.start
    ]  # fmt: skip
    return Result(primary, secondary, sorted(flags), "unknown" if language == "unsupported" else language,
                  confidence, review, spans, sorted(set(reasons)))  # fmt: skip


def observe(text: str, *, message_id: str, now: datetime, content_state: str = "available") -> IntentObservation:
    """The validated `intent.v1` observation. Unavailable content is `ambiguous` with an explicit reason."""
    if content_state != "available":
        result = Result("ambiguous", [], [], "unknown", "unknown", True, [], [f"content_{content_state}"])
    else:
        result = classify(text)
    payload: dict[str, Any] = {
        "schema_version": "intent.v1", "message_id": message_id, "primary_intent": result.primary,
        "secondary_intents": result.secondary, "safety_flags": result.flags, "language": result.language,
        "evidence": [s.model_dump() for s in result.spans], "confidence": result.confidence,
        "requires_human_review": result.requires_human_review, "recommended_action": ACTION_FOR[result.primary],
        "reason_codes": result.reasons, "classifier_version": CLASSIFIER_VERSION, "rules_version": CLASSIFIER_VERSION,
        "model_version": None, "prompt_version": None, "classified_at": now.isoformat(),
    }  # fmt: skip
    return IntentObservation.validated(payload, text if content_state == "available" else "")
