"""P3.3 QUALIFY-01..06 (pure rubric `school-qualification-1.0`)."""

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.qualification import rubric
from app.qualification.rubric import OfferView
from app.signals import rubric as signals
from app.signals.rubric import EvidenceFact

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)
_seq = iter(range(1, 10_000))


def fact(claim_type: str, value: dict[str, Any], status: str = "source_supported", storage: str = "full_allowed",
         expires: datetime | None = NOW + timedelta(days=30)) -> EvidenceFact:  # fmt: skip
    n = next(_seq)
    sourced = status != "hypothesis"
    return EvidenceFact(f"f-{n:04d}", claim_type, value, status, NOW - timedelta(days=2),
                        source_id=f"s-{n}" if sourced else None, storage_class=storage if sourced else None,
                        source_expires_at=expires if sourced else None)  # fmt: skip


def signal(area: str, text: str = "x", **kw: Any) -> EvidenceFact:
    return fact("public_workflow_signal", {"area": area, "signal": text}, **kw)


OFFER = OfferView(
    "o-1", "school_admin_starter", "r-1", "caps-2026-11", True, True, ("admissions_intake", "fee_tracking")
)


def strong_facts() -> list[EvidenceFact]:
    return [
        signal("admissions"),
        signal("fees"),
        signal("reporting"),
        fact("campus_count", {"count": 3}),
        fact("public_contact_channel", {"channel": "website_form"}),
    ]


def run(facts: list[EvidenceFact], offer: OfferView | None = OFFER, links: int = 0) -> dict[str, Any]:
    brief = signals.evaluate(facts, NOW, links)
    return rubric.assess(facts, brief["signals"], offer, NOW)


def test_qualify_01_four_ordinal_dimensions_and_no_probability() -> None:
    result = run(strong_facts())
    assert result["rubric_version"] == "school-qualification-1.0"
    assert list(result["dimensions"]) == ["customer_fit", "need_evidence", "accessibility", "delivery_fit"]
    for dim in result["dimensions"].values():
        assert dim["value"] in ("strong", "moderate", "weak", "unknown") and dim["reason"]
    assert result["channel_eligibility"] == "not_evaluated"
    assert not re.search(r"\d+\s*%|probabilit|likelihood|score", str(result), re.I)


def test_qualify_02_directory_only_is_unknown_and_investigate() -> None:
    result = run([], offer=None, links=1)
    assert {k: d["value"] for k, d in result["dimensions"].items()} == dict.fromkeys(rubric.DIMENSIONS, "unknown")
    assert result["decision"] == "investigate" and result["questions"]
    assert not re.search(r"(?i)\b(erp|excel|budget|pain|needs? (a|an))\b", str(result["dimensions"]))


def test_qualify_03_supported_evidence_gives_contact_now_research_priority_only() -> None:
    result = run(strong_facts())
    values = {k: d["value"] for k, d in result["dimensions"].items()}
    assert values == {"customer_fit": "strong", "need_evidence": "strong", "accessibility": "moderate",
                      "delivery_fit": "strong"}  # fmt: skip
    assert result["decision"] == "contact_now"
    assert result["decision_reason"] == "Research priority: contact candidate — channel eligibility not checked."
    assert "not permission to send marketing" in result["dimensions"]["accessibility"]["reason"]
    assert "not a confirmed problem or purchase intent" in result["dimensions"]["need_evidence"]["reason"]


def test_qualify_03_generic_phone_is_not_decision_maker_access() -> None:
    facts = [*strong_facts()[:4], fact("public_contact_channel", {"channel": "public_phone_listed"})]
    result = run(facts)
    assert result["dimensions"]["accessibility"]["value"] == "weak" and result["decision"] == "investigate"


def test_qualify_04_exclude_only_on_supported_hard_disqualifier() -> None:
    closed = run([*strong_facts(), fact("hard_disqualifier", {"reason": "school_closed"})])
    assert (closed["decision"], closed["decision_fact_ids"] != []) == ("exclude", True)
    guessed = run([*strong_facts(), fact("hard_disqualifier", {"reason": "school_closed"}, status="hypothesis")])
    assert guessed["decision"] == "investigate"
    assert guessed["questions"][0] == "Is the school still operating and open to hearing from suppliers?"
    weak_only = run([fact("public_contact_channel", {"channel": "social_page"})], offer=None)
    assert weak_only["decision"] == "investigate"  # weak/unknown never excludes


def test_qualify_04_central_mandate_lowers_fit_and_access_without_excluding() -> None:
    central = [fact("decision_authority", {"holder": "head_office"}), fact("ownership_type", {"type": "chain_campus"})]
    result = run([*strong_facts(), *central])
    assert result["dimensions"]["customer_fit"]["value"] == "weak"
    assert result["dimensions"]["accessibility"]["value"] == "weak"
    assert result["decision"] == "investigate"


def test_qualify_05_documented_deferral_nurtures_guessed_one_does_not() -> None:
    future = (NOW + timedelta(days=60)).date().isoformat()
    proven = run([*strong_facts(), fact("review_deferral", {"reason": "budget_cycle", "until": future})])
    assert proven["decision"] == "nurture" and "No reminder is scheduled" in proven["decision_reason"]
    guessed = run([*strong_facts(), fact("review_deferral", {"reason": "budget_cycle", "until": future},
                                         status="hypothesis")])  # fmt: skip
    assert guessed["decision"] == "contact_now"  # an unverified guess changes nothing
    past = (NOW - timedelta(days=1)).date().isoformat()
    lapsed = run([*strong_facts(), fact("review_deferral", {"reason": "budget_cycle", "until": past})])
    assert lapsed["decision"] == "contact_now"


@pytest.mark.parametrize(
    ("offer", "value"),
    [
        (None, "unknown"),
        (OfferView("o", "x", None, None, False, True, ()), "weak"),
        (OfferView("o", "x", "r", "v", True, False, ("admissions_intake",)), "weak"),
        (OfferView("o", "x", "r", "v", True, True, ()), "weak"),
        (OfferView("o", "x", "r", "v", True, True, ("student_records",)), "moderate"),
    ],
)
def test_qualify_06_delivery_is_strong_only_with_a_matching_published_offer(
    offer: OfferView | None, value: str
) -> None:
    facts = [signal("admissions"), signal("fees"), fact("public_contact_channel", {"channel": "website_form"})]
    result = run(facts, offer=offer)
    assert result["dimensions"]["delivery_fit"]["value"] == value
    assert result["decision"] != "contact_now"


def test_conflicts_and_stale_evidence_block_contact_now() -> None:
    conflicting = run([*strong_facts(), fact("campus_count", {"count": 7})])
    assert conflicting["decision"] == "investigate" and any("conflicting" in b for b in conflicting["blocking"])
    stale = run([*strong_facts(), signal("communication", expires=NOW - timedelta(days=1))])
    assert stale["decision"] == "investigate" and any("re-checking" in b for b in stale["blocking"])


def test_digest_tracks_offer_revision_and_deferral_validity() -> None:
    facts = [fact("review_deferral", {"reason": "budget_cycle", "until": (NOW + timedelta(days=1)).date().isoformat()})]
    base = rubric.input_digest("d" * 64, OFFER, facts, NOW)
    assert base == rubric.input_digest("d" * 64, OFFER, facts, NOW)
    republished = replace(OFFER, revision_id="r-2")
    assert rubric.input_digest("d" * 64, republished, facts, NOW) != base
    assert rubric.input_digest("d" * 64, OFFER, facts, NOW + timedelta(days=3)) != base
