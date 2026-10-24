"""P2.3 IDENTITY-02..05 and IDENTITY-09: the pure campus matcher against labelled gold fixtures."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.discovery.contracts import SourceCandidate
from app.resolution import matcher

GOLD = json.loads((Path(__file__).parents[1] / "fixtures" / "identity_gold_v1.json").read_text(encoding="utf-8"))
CASES = GOLD["cases"]


def side(data: dict[str, Any]) -> matcher.Side:
    return matcher.Side(**{**data, "names": tuple(data["names"])})


def test_gold_set_is_versioned_large_enough_and_matches_the_algorithm() -> None:
    assert GOLD["fixture_version"] == "campus-identity-gold-v1"
    assert GOLD["algorithm_version"] == matcher.ALGORITHM_VERSION
    assert len(CASES) + len(GOLD["upstream_rejections"]) >= 20
    assert {c["expected_resolution"] for c in CASES} == {
        "exact_reobservation", "suggest_review", "distinct", "insufficient_evidence"
    }  # fmt: skip


@pytest.mark.parametrize("case", CASES, ids=[f"{c['id']}-{c['description'][:40]}" for c in CASES])
def test_gold_case(case: dict[str, Any]) -> None:
    result = matcher.compare(side(case["left"]), side(case["right"]))
    assert (result.resolution, list(result.reason_codes)) == (case["expected_resolution"], case["expected_reasons"])
    assert result.algorithm_version == matcher.ALGORITHM_VERSION
    assert result.features["buying_authority"] == "unknown"


def test_scorecard_has_zero_automatic_merges_of_different_source_identities() -> None:
    """The only automatic outcome is exact re-observation of one (provider, key); everything else needs a human."""
    automatic = []
    for case in CASES:
        left, right = side(case["left"]), side(case["right"])
        result = matcher.compare(left, right)
        same_identity = (left.provider, left.external_key) == (right.provider, right.external_key)
        if result.resolution == "exact_reobservation" and not same_identity:
            automatic.append(case["id"])
    assert automatic == []
    counts: dict[str, int] = {}
    for case in CASES:
        counts[case["expected_resolution"]] = counts.get(case["expected_resolution"], 0) + 1
    assert counts == {"distinct": 11, "exact_reobservation": 3, "insufficient_evidence": 6, "suggest_review": 6}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_results_are_deterministic_and_symmetric(case: dict[str, Any]) -> None:
    left, right = side(case["left"]), side(case["right"])
    first, again, mirrored = matcher.compare(left, right), matcher.compare(left, right), matcher.compare(right, left)
    assert first == again
    assert (mirrored.resolution, set(mirrored.reason_codes)) == (first.resolution, set(first.reason_codes))


def test_features_never_carry_upstream_text() -> None:
    for case in CASES:
        result = matcher.compare(side(case["left"]), side(case["right"]))
        names = [n for s in (case["left"], case["right"]) for n in s["names"]]
        for value in result.features.values():
            assert value is None or isinstance(value, float) or value in {
                "yes", "no", "same", "different", "unknown", "conflict", "exact", "near", "latin", "arabic", "none",
                "point", "approximate",
            }, value  # fmt: skip
            assert not any(isinstance(value, str) and len(n) > 3 and n in value for n in names)


@pytest.mark.parametrize("upstream", GOLD["upstream_rejections"], ids=lambda u: u["id"])
def test_missing_or_invalid_source_keys_never_reach_matching(upstream: dict[str, Any]) -> None:
    for key in upstream["external_keys"]:
        base = {"provider": "p", "display_name": "Fixture", "city": "Lahore", "vertical_slug": "schools",
                "observed_at": "2026-10-23T07:00:00+00:00", "external_key": key}  # fmt: skip
        if key is None:
            assert SourceCandidate.model_validate(base).external_key is None  # the runner rejects: missing_key
        else:
            with pytest.raises(ValidationError):
                SourceCandidate.model_validate(base)


def test_original_names_are_untouched_and_normalization_is_conservative() -> None:
    original = "St. Mary's  Convent School — Gulberg Campus No. 2"
    left = matcher.Side("x", None, None, (original,), "Lahore")
    matcher.compare(left, left)
    assert left.names == (original,)
    assert matcher.core("The Lahore Grammar School") == "lahore grammar"  # only generic words dropped
    assert matcher.branch_marks(original) == (frozenset({"2"}), frozenset({"gulberg"}))  # branch numbers kept
    assert matcher.tokens("اِقرا سكول") == ["اقرا", "سکول"]  # diacritic + Arabic/Urdu kaf folding; no transliteration


def test_blocking_proposes_only_pairs_that_share_city_and_name_token() -> None:
    sides = [
        matcher.Side("1", "p", "1", ("Fixture Alpha School",), "Lahore"),
        matcher.Side("2", "q", "2", ("Fixture Alpha Academy",), "Lahore"),
        matcher.Side("3", "q", "3", ("Beta Institute",), "Lahore"),
        matcher.Side("4", "q", "4", ("Fixture Alpha School",), "Karachi"),
    ]
    pairs, skipped = matcher.candidate_pairs(sides)
    assert [(a.ref, b.ref) for a, b in pairs] == [("1", "2")] and skipped == 0
    crowd = [matcher.Side(str(i), "p", str(i), (f"Common Name {i}",), "Lahore") for i in range(70)]
    pairs, skipped = matcher.candidate_pairs(crowd)
    assert skipped == 2 and pairs == []  # "common" and "name" blocks exceed the cap; documented limit
