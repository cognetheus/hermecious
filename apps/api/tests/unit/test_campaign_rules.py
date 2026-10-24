"""P4.1 CAMPAIGN-02/03 (pure): typed target rules and deterministic candidate evaluation."""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.campaigns.rules import Budgets, Candidate, TargetRules, evaluate, item_digest, rules_digest

OFFER = "rev-1"


def candidate(**overrides: Any) -> Candidate:
    base: dict[str, Any] = {
        "account_id": str(uuid.UUID(int=1)), "name": "Fixture School", "city": "Lahore", "locality": "Gulberg",
        "archived": False, "provenance": "real", "manual_stage": None,
        "assessment": {"id": "a", "revision": 1, "decision": "contact_now", "offer_revision_id": OFFER,
                       "needs_reassessment": False,
                       "dims": {"customer_fit": "strong", "need_evidence": "moderate", "accessibility": "moderate",
                                "delivery_fit": "strong"}},
    }  # fmt: skip
    return Candidate(**(base | overrides))


def reasons(c: Candidate, rules: TargetRules | None = None, mode: str = "live") -> list[str]:
    return evaluate(c, rules or TargetRules(), OFFER, mode).reasons


def with_assessment(**changes: Any) -> Candidate:
    c = candidate()
    assert c.assessment is not None
    return candidate(assessment=c.assessment | changes)


def test_qualifying_candidate_has_no_reasons() -> None:
    assert evaluate(candidate(), TargetRules(), OFFER, "live").qualifies


@pytest.mark.parametrize(
    ("c", "reason"),
    [
        (candidate(assessment=None), "unassessed"),
        (with_assessment(needs_reassessment=True), "stale_assessment"),
        (with_assessment(offer_revision_id="other"), "assessed_against_other_offer"),
        (with_assessment(decision="investigate"), "decision_not_targeted"),
        (with_assessment(decision="exclude"), "decision_exclude"),
        (with_assessment(decision="nurture"), "decision_nurture"),
        (candidate(city="Karachi"), "other_city"),
        (candidate(archived=True), "account_archived"),
        (candidate(manual_stage="excluded"), "manually_excluded"),
        (candidate(provenance="synthetic"), "synthetic_account"),
        (candidate(provenance="unsourced"), "unsourced_account"),
    ],
)
def test_each_rejection_has_a_reason(c: Candidate, reason: str) -> None:
    assert reason in reasons(c)


def test_unknown_never_meets_a_minimum_and_fixture_mode_takes_only_synthetic() -> None:
    rules = TargetRules.model_validate({"minimums": {"accessibility": "weak"}})
    unknown = with_assessment(dims={"customer_fit": "strong", "need_evidence": "moderate", "accessibility": "unknown",
                                    "delivery_fit": "strong"})  # fmt: skip
    assert reasons(unknown, rules) == ["below_minimum:accessibility"]
    assert reasons(candidate(), mode="fixture") == ["real_account_in_fixture_campaign"]
    assert reasons(candidate(provenance="synthetic"), mode="fixture") == []


def test_localities_and_explicit_exclusions() -> None:
    rules = TargetRules.model_validate({"localities_include": ["Gulberg"], "localities_exclude": ["DHA"]})
    assert reasons(candidate(), rules) == []
    assert reasons(candidate(locality="Johar Town"), rules) == ["locality_not_targeted"]
    assert reasons(candidate(locality=None), rules) == ["locality_unknown"]
    blocked = TargetRules.model_validate({"exclude_account_ids": [str(uuid.UUID(int=1))]})
    assert reasons(candidate(), blocked) == ["manually_excluded"]


@pytest.mark.parametrize(
    "raw",
    [
        {"sql": "1=1"},
        {"decisions": ["contact_now; DROP TABLE accounts"]},
        {"decisions": []},
        {"minimums": {"customer_fit": "unknown"}},
        {"minimums": {"score": "strong"}},
        {"localities_include": ["Gulberg' OR '1'='1"]},
        {"localities_include": ["x"] * 21},
        {"exclude_account_ids": ["not-a-uuid"]},
    ],
)
def test_rules_are_a_strict_typed_allowlist(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TargetRules.model_validate(raw)


@pytest.mark.parametrize("raw", [{"preview_limit": 31}, {"approvals_per_day": 11}, {"drafts_per_day": -1}])
def test_budgets_only_tighten(raw: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Budgets.model_validate(raw)
    assert Budgets().model_dump() == {"preview_limit": 30, "approvals_per_day": 10, "drafts_per_day": 10}


def test_digests_are_deterministic_and_input_sensitive() -> None:
    rules = TargetRules()
    assert rules_digest(rules) == rules_digest(TargetRules())
    assert rules_digest(TargetRules(decisions=["investigate"])) != rules_digest(rules)
    d = rules_digest(rules)
    assert item_digest(candidate(), d, OFFER) == item_digest(candidate(), d, OFFER)
    assert item_digest(with_assessment(revision=2), d, OFFER) != item_digest(candidate(), d, OFFER)
