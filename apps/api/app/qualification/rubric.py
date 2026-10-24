"""Four-axis qualification, rubric `school-qualification-1.0` (P3.3, ADR-018). Pure and deterministic.

Four separate ordinal dimensions, each `strong`, `moderate`, `weak` or `unknown`:
`customer_fit`, `need_evidence`, `accessibility`, `delivery_fit`. Each carries
a reason, cited fact ids and open questions. `unknown` means "no evidence"
and is never treated as `weak`. There is no percentage and no weighted
composite.

The recommendation follows a fixed precedence:
1. `exclude`, only on a current, auditable `hard_disqualifier` fact;
2. `nurture`, only on a current, auditable `review_deferral` that is still in force;
3. `contact_now`, only when fit, need and access are each at least moderate, delivery is
   strong with a currently published offer, and no signal is conflicting or stale;
4. `investigate` otherwise.

`contact_now` is research prioritisation only. Channel eligibility is never
evaluated here, and nothing is sent, enrolled or scheduled.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from app.signals.rubric import EvidenceFact, eligibility

RUBRIC_VERSION = "school-qualification-1.0"
DIMENSIONS = ("customer_fit", "need_evidence", "accessibility", "delivery_fit")
DECISIONS = ("contact_now", "investigate", "nurture", "exclude")
Level = Literal["strong", "moderate", "weak", "unknown"]
RANK = {"unknown": 0, "weak": 1, "moderate": 2, "strong": 3}
SIGNAL_AREAS = {"admissions_workflow": "admissions", "fee_process": "fees", "operational_complexity": "operations"}
CONTACT_NOW_TEXT = "Research priority: contact candidate — channel eligibility not checked."


@dataclass(frozen=True)
class OfferView:
    offer_id: str
    code: str
    revision_id: str | None
    capability_version: str | None
    published: bool
    vertical_matches: bool
    sellable_capabilities: tuple[str, ...]  # sales-approved capability codes of the published revision


def capability_area(code: str) -> str | None:
    if "admission" in code:
        return "admissions"
    if "fee" in code or "payment" in code:
        return "fees"
    if any(word in code for word in ("record", "report", "attendance", "communicat", "result")):
        return "operations"
    return None


@dataclass
class Dimension:
    value: Level
    reason: str
    fact_ids: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def _usable(facts: list[EvidenceFact], claim_type: str, now: datetime) -> list[EvidenceFact]:
    return [f for f in facts if f.claim_type == claim_type and eligibility(f, now) == "usable"]


def _ids(facts: list[EvidenceFact]) -> list[str]:
    return sorted(f.fact_id for f in facts)


def _customer_fit(facts: list[EvidenceFact], signals: dict[str, Any], now: datetime) -> Dimension:
    authority = _usable(facts, "decision_authority", now)
    ownership = _usable(facts, "ownership_type", now)
    central = [f for f in authority if f.value.get("holder") == "head_office"]
    chain = [f for f in ownership if f.value.get("type") == "chain_campus"]
    question = "Does this campus run its own administration, and how many students and campuses does it serve?"
    if central and chain:
        return Dimension("weak", "Cited sources state this is a chain campus whose decisions sit with a head office.",
                         _ids(central + chain), [question])  # fmt: skip
    if signals["campus_footprint"]["state"] == "conflicting":
        return Dimension("unknown", "Sources disagree on the school's size; fit cannot be judged yet.",
                         signals["campus_footprint"]["conflicting_fact_ids"], [question])  # fmt: skip
    campuses = [f for f in _usable(facts, "campus_count", now) if int(f.value.get("count", 0)) >= 2]
    levels = [f for f in _usable(facts, "school_levels", now) if len(f.value.get("levels", [])) >= 2]
    if campuses or levels:
        return Dimension("strong", "Cited sources describe a multi-campus or multi-level school, the profile this "
                         "offer is designed for.", _ids(campuses + levels))  # fmt: skip
    observed = [k for k in SIGNAL_AREAS if signals[k]["state"] == "observed"]
    if observed:
        cited = sorted({i for k in observed for i in signals[k]["fact_ids"]})
        return Dimension("moderate", "A cited source shows an operating Lahore school; its size is not established.",
                         cited, [question])  # fmt: skip
    return Dimension("unknown", "No cited evidence about this school's profile yet.", [], [question])


def _need(signals: dict[str, Any]) -> Dimension:
    observed = [k for k in SIGNAL_AREAS if signals[k]["state"] == "observed"]
    hypotheses = [k for k in SIGNAL_AREAS if signals[k]["state"] == "hypothesis"]
    cited = sorted({i for k in observed for i in signals[k]["fact_ids"]})
    question = (
        "Which administrative tasks take the most staff time, and is the school looking to change how they are done?"
    )
    names = ", ".join(SIGNAL_AREAS[k] for k in observed)
    if len(observed) >= 2 and "operational_complexity" in observed:
        reason = (f"Cited public notices show administrative activity in: {names}. This is workload evidence, "
                  "not a confirmed problem or purchase intent.")  # fmt: skip
        return Dimension("strong", reason, cited, [question])
    if observed:
        return Dimension("moderate", f"Cited public notices show administrative activity in: {names}. Need is "
                         "not confirmed.", cited, [question])  # fmt: skip
    if hypotheses:
        hypo = sorted({i for k in hypotheses for i in signals[k]["fact_ids"]})
        return Dimension("weak", "Only unverified notes suggest administrative activity.", hypo, [question])
    return Dimension("unknown", "No cited evidence about administrative workload.", [], [question])


def _access(facts: list[EvidenceFact], now: datetime) -> Dimension:
    channels = _usable(facts, "public_contact_channel", now)
    authority = _usable(facts, "decision_authority", now)
    question = "Who at the school should receive a short introduction, and through which administrative channel?"
    if any(f.value.get("holder") == "head_office" for f in authority):
        central = [f for f in authority if f.value.get("holder") == "head_office"]
        return Dimension("weak", "A cited source places decisions with a head office; campus access is limited.",
                         _ids(central), [question])  # fmt: skip
    routes = [f for f in channels if f.value.get("channel") in ("website_form", "public_email_listed")]
    deciders = [f for f in authority if f.value.get("holder") in ("owner", "principal")]
    if routes and deciders:
        reason = ("An administrative contact route is published and a cited source names who decides. "
                  "This is a route, not permission to send marketing.")  # fmt: skip
        return Dimension("strong", reason, _ids(routes + deciders))
    if routes:
        reason = ("An administrative contact route (form or email) is published. It is not decision-maker "
                  "access and not permission to send marketing.")  # fmt: skip
        return Dimension("moderate", reason, _ids(routes), [question])
    if channels:
        return Dimension("weak", "Only a generic public phone number or social page is listed; that is not "
                         "decision-maker access.", _ids(channels), [question])  # fmt: skip
    return Dimension("unknown", "No cited contact route.", [], [question])


def _delivery(offer: OfferView | None, signals: dict[str, Any]) -> Dimension:
    question = "Which of the school's administrative tasks would a new tool need to support first?"
    if offer is None:
        return Dimension("unknown", "No published offer is selected, so delivery fit cannot be judged.", [], [question])
    if not offer.published:
        return Dimension("weak", f"Offer {offer.code} is not currently published; nothing can be promised.", [],
                         [question])  # fmt: skip
    if not offer.vertical_matches:
        return Dimension("weak", f"Offer {offer.code} is published for a different vertical.", [], [question])
    if not offer.sellable_capabilities:
        return Dimension("weak", f"Offer {offer.code} has no sales-approved capabilities in its published revision.",
                         [], [question])  # fmt: skip
    offered = {a for c in offer.sellable_capabilities if (a := capability_area(c))}
    observed = {SIGNAL_AREAS[k] for k in SIGNAL_AREAS if signals[k]["state"] == "observed"}
    matched = sorted(offered & observed)
    if matched:
        cited = sorted({i for k, area in SIGNAL_AREAS.items() if area in matched for i in signals[k]["fact_ids"]})
        reason = (f"A sales-approved capability of published offer {offer.code} ({offer.capability_version}) "
                  f"matches an observed area: {', '.join(matched)}.")  # fmt: skip
        return Dimension("strong", reason, cited)
    return Dimension("moderate", f"Offer {offer.code} is published, but none of its approved capabilities matches "
                     "an observed area yet.", [], [question])  # fmt: skip


def assess(
    facts: list[EvidenceFact], signals: dict[str, Any], offer: OfferView | None, now: datetime
) -> dict[str, Any]:
    dims = {
        "customer_fit": _customer_fit(facts, signals, now),
        "need_evidence": _need(signals),
        "accessibility": _access(facts, now),
        "delivery_fit": _delivery(offer, signals),
    }
    hard = _usable(facts, "hard_disqualifier", now)
    unverified_hard = [f for f in facts if f.claim_type == "hard_disqualifier" and eligibility(f, now) != "usable"
                       and eligibility(f, now) != "rejected"]  # fmt: skip
    deferrals = [
        f for f in _usable(facts, "review_deferral", now) if date.fromisoformat(str(f.value["until"])) > now.date()
    ]
    blocking: list[str] = []
    if hard:
        decision, reason = (
            "exclude",
            f"A cited, current hard disqualifier is recorded ({hard[0].value['reason'].replace('_', ' ')}).",
        )
        cited = _ids(hard)
    elif deferrals:
        latest = max(deferrals, key=lambda f: str(f.value["until"]))
        decision = "nurture"
        reason = (f"A documented deferral is in force until {latest.value['until']} "
                  f"({str(latest.value['reason']).replace('_', ' ')}). No reminder is scheduled.")  # fmt: skip
        cited = _ids(deferrals)
    else:
        for name in ("customer_fit", "need_evidence", "accessibility"):
            if RANK[dims[name].value] < RANK["moderate"]:
                blocking.append(f"{name} is {dims[name].value}")
        if dims["delivery_fit"].value != "strong":
            blocking.append(f"delivery_fit is {dims['delivery_fit'].value}")
        conflicting = [k for k, s in signals.items() if s["state"] == "conflicting"]
        stale = [k for k, s in signals.items() if s["stale_fact_ids"]]
        if conflicting:
            blocking.append("conflicting evidence: " + ", ".join(conflicting))
        if stale:
            blocking.append("evidence needs re-checking: " + ", ".join(stale))
        if unverified_hard:
            blocking.append("an unverified possible disqualifier needs checking")
        cited = []
        if blocking:
            decision, reason = (
                "investigate",
                "More evidence is needed before prioritising: " + "; ".join(blocking) + ".",
            )
        else:
            decision, reason = "contact_now", CONTACT_NOW_TEXT
    questions: list[str] = []
    for dim in dims.values():
        for q in dim.questions:
            if q not in questions:
                questions.append(q)
    if unverified_hard:
        questions.insert(0, "Is the school still operating and open to hearing from suppliers?")
    return {
        "rubric_version": RUBRIC_VERSION,
        "dimensions": {
            k: {"value": d.value, "reason": d.reason, "fact_ids": d.fact_ids, "questions": d.questions}
            for k, d in dims.items()
        },  # fmt: skip
        "decision": decision,
        "decision_reason": reason,
        "decision_fact_ids": cited,
        "blocking": blocking,
        "questions": questions,
        "channel_eligibility": "not_evaluated",
    }


def input_digest(signal_digest: str, offer: OfferView | None, facts: list[EvidenceFact], now: datetime) -> str:
    """Changes when evidence, rights, the offer's published revision or a deferral's validity changes."""
    deferrals = sorted(
        f"{f.fact_id}:{date.fromisoformat(str(f.value['until'])) > now.date()}"
        for f in facts if f.claim_type == "review_deferral" and "until" in f.value
    )  # fmt: skip
    payload = {
        "rubric": RUBRIC_VERSION, "signals": signal_digest, "deferrals": deferrals,
        "offer": None if offer is None else [offer.offer_id, offer.revision_id, offer.published, offer.vertical_matches,
                                             list(offer.sellable_capabilities)],
    }  # fmt: skip
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
