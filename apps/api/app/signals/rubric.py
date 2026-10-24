"""School operations brief, rubric `school-signals-1.0` (P3.2, ADR-017). Pure and deterministic.

Six keys, each with a state:
- `observed`: a current, source-supported, auditable fact;
- `hypothesis`: unverified, or supported only by a metadata-only citation;
- `conflicting`: current facts disagree, or one is disputed; every reference is kept, with no forced winner;
- `unknown`: nothing usable.

Wording is cautious and fixed:
- a published notice describes what a school says publicly, never its internal tools, need, budget or buying process;
- a public contact channel is never consent;
- missing evidence stays unknown, never "no" or "weak".

This is not qualification (P3.3) and it ranks nothing.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

RUBRIC_VERSION = "school-signals-1.0"
KEYS = (
    "campus_footprint",
    "operator_autonomy",
    "admissions_workflow",
    "fee_process",
    "public_contact_route",
    "operational_complexity",
)
AGING_AFTER = timedelta(days=365)
State = Literal["observed", "hypothesis", "conflicting", "unknown"]
Eligibility = Literal["usable", "stale", "unauditable", "hypothesis", "disputed", "rejected"]

QUESTIONS = {
    "campus_footprint": "How many campuses does the school run, and does this campus manage its own administration?",
    "operator_autonomy": "Who usually decides on new administration tools for this campus?",
    "admissions_workflow": "How are admission enquiries and applications handled and recorded today?",
    "fee_process": "How are fee payments recorded and matched to students today?",
    "public_contact_route": (
        "What is the best way to request a short introductory conversation with the administration?"
    ),
    "operational_complexity": "Which administrative tasks take up the most staff time each term?",
}
CAVEATS = {
    "campus_footprint": "A single map listing never shows how many campuses a school has.",
    "operator_autonomy": "Ownership or brand does not show who approves purchases for this campus.",
    "admissions_workflow": "A published notice does not show how admissions are recorded internally.",
    "fee_process": "Published payment instructions do not show how payments are reconciled or followed up.",
    "public_contact_route": "A public channel is not consent to receive marketing and not access to the owner.",
    "operational_complexity": "Public mentions describe operations only, not need, budget or software in use.",
}
_EXCLUSIVE = {"campus_count", "ownership_type", "decision_authority"}


@dataclass(frozen=True)
class EvidenceFact:
    fact_id: str
    claim_type: str
    value: dict[str, Any]
    verification_status: str  # source_supported | hypothesis | disputed | rejected
    observed_at: datetime
    source_id: str | None = None
    source_url: str | None = None
    storage_class: str | None = None
    source_expires_at: datetime | None = None
    attribution: str | None = None


@dataclass
class Signal:
    key: str
    state: State
    statement: str
    caveat: str
    question: str
    fact_ids: list[str] = field(default_factory=list)
    conflicting_fact_ids: list[str] = field(default_factory=list)
    stale_fact_ids: list[str] = field(default_factory=list)
    freshness: Literal["current", "aging", "stale", "none"] = "none"
    evidence_at: str | None = None


def eligibility(fact: EvidenceFact, now: datetime) -> Eligibility:
    if fact.verification_status == "rejected":
        return "rejected"
    if fact.verification_status == "disputed":
        return "disputed"
    if fact.verification_status != "source_supported" or fact.source_id is None:
        return "hypothesis"
    if fact.source_expires_at is not None and fact.source_expires_at <= now:
        return "stale"
    if fact.storage_class == "metadata_only":
        return "unauditable"  # a listing-only citation cannot certify how a school operates
    return "usable"


def _relevant(key: str, fact: EvidenceFact) -> bool:
    area = fact.value.get("area") if fact.claim_type == "public_workflow_signal" else None
    return {
        "campus_footprint": fact.claim_type == "campus_count",
        "operator_autonomy": fact.claim_type in ("ownership_type", "decision_authority"),
        "admissions_workflow": area == "admissions",
        "fee_process": area == "fees",
        "public_contact_route": fact.claim_type == "public_contact_channel",
        "operational_complexity": area in ("student_records", "reporting", "communication")
        or fact.claim_type == "school_levels"
        or (fact.claim_type == "software_in_use" and fact.value.get("status") == "observed"),
    }[key]


def _is_unknown_value(fact: EvidenceFact) -> bool:
    value = fact.value
    return value.get("type") == "unknown" or value.get("holder") == "unknown" or value.get("status") == "unknown"


def _describe(fact: EvidenceFact) -> str:
    v = fact.value
    match fact.claim_type:
        case "campus_count":
            return f"{v.get('count')} campus{'es' if v.get('count') != 1 else ''}"
        case "ownership_type":
            return f"ownership type: {str(v.get('type')).replace('_', ' ')}"
        case "decision_authority":
            return f"decision authority: {str(v.get('holder')).replace('_', ' ')}"
        case "public_workflow_signal":
            return f"“{v.get('signal')}”"
        case "public_contact_channel":
            return str(v.get("channel")).replace("_", " ")
        case "school_levels":
            return "levels: " + ", ".join(str(x).replace("_", " ") for x in v.get("levels", []))
        case "software_in_use":
            return f"software named by a source: {v.get('product')}"
    return fact.claim_type


def _value_key(fact: EvidenceFact) -> str:
    return json.dumps(fact.value, sort_keys=True)


def _conflicts(facts: list[EvidenceFact]) -> bool:
    for claim_type in _EXCLUSIVE:
        values = {_value_key(f) for f in facts if f.claim_type == claim_type}
        if len(values) > 1:
            return True
    return False


def _freshness(facts: list[EvidenceFact], now: datetime) -> Literal["current", "aging"]:
    return "aging" if any(now - f.observed_at > AGING_AFTER for f in facts) else "current"


def _signal(key: str, facts: list[EvidenceFact], now: datetime) -> Signal:
    relevant = [f for f in facts if _relevant(key, f)]
    by_state: dict[str, list[EvidenceFact]] = {}
    for fact in relevant:
        by_state.setdefault(eligibility(fact, now), []).append(fact)
    usable = [f for f in by_state.get("usable", []) if not _is_unknown_value(f)]
    disputed = by_state.get("disputed", [])
    weak = by_state.get("hypothesis", []) + by_state.get("unauditable", [])
    stale = by_state.get("stale", [])
    signal = Signal(key, "unknown", "", CAVEATS[key], QUESTIONS[key])
    signal.stale_fact_ids = sorted(f.fact_id for f in stale)

    if usable and (_conflicts(usable) or disputed):
        cited = usable + disputed
        signal.state = "conflicting"
        signal.conflicting_fact_ids = sorted(f.fact_id for f in cited)
        described = "; ".join(sorted({_describe(f) for f in cited}))
        signal.statement = f"Cited sources disagree ({described}). All are kept for review; none is chosen."
    elif usable:
        signal.state = "observed"
        signal.fact_ids = sorted(f.fact_id for f in usable)
        described = "; ".join(sorted({_describe(f) for f in usable}))
        signal.statement = f"A cited source states: {described}."
    elif weak or disputed:
        signal.state = "hypothesis"
        signal.fact_ids = sorted(f.fact_id for f in weak + disputed)
        described = "; ".join(sorted({_describe(f) for f in weak + disputed}))
        signal.statement = f"Unverified: {described}. Not supported by an auditable current source."
    else:
        signal.statement = "Unknown: no current cited evidence."
        if stale:
            signal.statement = "Unknown now: earlier evidence has expired and needs to be checked again."
    cited_facts = usable or weak or disputed
    if signal.state == "conflicting":
        cited_facts = usable + disputed
    if cited_facts:
        signal.freshness = _freshness(cited_facts, now)
        signal.evidence_at = max(f.observed_at for f in cited_facts).isoformat()
    elif stale:
        signal.freshness = "stale"
    return signal


def evaluate(facts: list[EvidenceFact], now: datetime, linked_listings: int = 0) -> dict[str, Any]:
    """The six-key brief. `linked_listings` (reviewed P2.3 links) is context only, never a campus count."""
    signals = {key: asdict(_signal(key, facts, now)) for key in KEYS}
    if linked_listings:
        signals["campus_footprint"]["statement"] += (
            f" {linked_listings} reviewed listing(s) are linked to this account; a listing is not a campus count."
        )
    return {"rubric_version": RUBRIC_VERSION, "signals": signals}


def input_digest(facts: list[EvidenceFact], now: datetime, linked_listings: int) -> tuple[str, list[dict[str, str]]]:
    """Ordered inputs (fact id, type, status, eligibility now) plus links; changes whenever a reassessment is due."""
    inputs = [
        {"fact_id": f.fact_id, "claim_type": f.claim_type, "verification": f.verification_status,
         "eligibility": eligibility(f, now)}
        for f in sorted(facts, key=lambda f: f.fact_id)
    ]  # fmt: skip
    canonical = json.dumps({"rubric": RUBRIC_VERSION, "inputs": inputs, "linked_listings": linked_listings},
                           sort_keys=True, separators=(",", ":"))  # fmt: skip
    return hashlib.sha256(canonical.encode()).hexdigest(), inputs
