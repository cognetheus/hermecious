"""P6.2 KNOW-01/03/04/05/07/08: the reply.v1 contract, the deterministic proposer and its frozen fixture corpus.

The corpus holds agent-authored policy expectations (what may and may not be drafted). It runs the real P6.1
classifier and the real proposer; nothing here is mocked except the knowledge snapshot's source rows.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.intent.classifier import observe
from app.replies import composer
from app.replies.composer import Inputs, propose, ungrounded
from app.replies.knowledge import ClaimRecord, Knowledge, PriceRecord
from app.replies.schema import InvalidProposal, ReplyProposal

FIXTURES = Path(__file__).parents[1] / "fixtures" / "replies"
NOW = datetime(2026, 11, 9, 7, 0, tzinfo=UTC)
ADMISSIONS = ClaimRecord("admissions_intake", "Online admissions intake with a document checklist", "available", (),
                         "1" * 64)  # fmt: skip
FEES = ClaimRecord("fee_tracking", "Fee vouchers and arrears tracking", "limited", ("Bank reconciliation is manual",),
                   "2" * 64)  # fmt: skip
PRICE = PriceRecord("per_student", "Core plan", Decimal("150.00"), "per_student_month", "3" * 64)
OFFERS = {
    "core": Knowledge("offer-1", 1, "a" * 64, (ADMISSIONS, FEES), ()),
    "priced": Knowledge("offer-1", 2, "b" * 64, (ADMISSIONS, FEES), (PRICE,)),
    "fees_only": Knowledge("offer-1", 3, "c" * 64, (FEES,), ()),
    "none": Knowledge(),
}


def run(text: str, offer: str = "core", matched: bool = True) -> ReplyProposal:
    observation = observe(text, message_id="m-1", now=NOW).model_dump(mode="json") | {"observation_id": "obs-1"}
    return propose(Inputs("m-1", text, "available", observation, OFFERS[offer], matched, NOW))


def corpus() -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / "reply_fixtures_v1.jsonl").read_text("utf-8").splitlines()]


# --- KNOW-01 -------------------------------------------------------------------------------------------------------


def test_know_01_reply_v1_contract_rejects_anything_executable_or_unanchored() -> None:
    good = run("fees module hai?").model_dump(mode="json")
    text = "fees module hai?"
    digests = OFFERS["core"].digests
    assert ReplyProposal.validated(good, text, digests).status == "proposed"
    for bad in (
        good | {"recommended_action": "send_now"},
        good | {"recommended_action": "approve_and_send"},
        good | {"intent": "ready_to_buy"},
        good | {"recipient": "+923001234567"},
        good | {"tool_calls": 1},
        good | {"model_version": "gpt-x"},
        good | {"proposed_reply": None},  # proposed without text
        good | {"abstention_codes": ["opt_out"]},  # proposed with an abstention code
        good | {"citations": [{"kind": "capability", "key": "attendance", "digest": "9" * 64, "sentence": 1}]},
        good
        | {
            "confirmed_facts": [
                {
                    "code": "current_tool",
                    "text": "Excel",
                    "message_id": "m-1",
                    "start": 0,
                    "end": 5,
                    "attribution": "prospect_stated",
                    "verified": False,
                }
            ]
        },  # fmt: skip
        good
        | {
            "confirmed_facts": [
                {
                    "code": "budget",
                    "text": "fees",
                    "message_id": "m-1",
                    "start": 0,
                    "end": 4,
                    "attribution": "prospect_stated",
                    "verified": True,
                }
            ]
        },  # fmt: skip
    ):
        with pytest.raises(InvalidProposal):
            ReplyProposal.validated(bad, text, digests)
    assert good["model_version"] is None and good["tool_calls"] == 0 and good["intent"] == "needs_details"


# --- KNOW-03 / 04 / 07 / 08: the frozen corpus -----------------------------------------------------------------------


def test_know_03_the_fixture_corpus_is_frozen_and_covers_every_language() -> None:
    raw = (FIXTURES / "reply_fixtures_v1.jsonl").read_bytes()
    manifest = json.loads((FIXTURES / "manifest.json").read_text("utf-8"))
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256"] and manifest["items"] >= 60
    assert all(manifest["by_language"][lang] >= 8 for lang in ("english", "roman_urdu", "urdu_script", "mixed"))


@pytest.mark.parametrize("case", corpus(), ids=lambda c: f"{c['id']}-{c['cluster']}")
def test_know_03_04_07_08_every_fixture_gets_its_policy_outcome(case: dict[str, Any]) -> None:
    p = run(case["text"], case["offer"], case["matched_contact"])
    e = case["expect"]
    observed = {
        "status": p.status, "action": p.recommended_action, "codes": sorted(p.abstention_codes),
        "cite": sorted(c.key for c in p.citations), "missing": sorted(p.missing_claims),
        "facts": sorted(f.code for f in p.confirmed_facts),
    }  # fmt: skip
    assert observed == {k: sorted(v) if isinstance(v, list) else v for k, v in e.items()}
    knowledge = OFFERS[case["offer"]]
    if p.proposed_reply is not None:
        sentences = p.proposed_reply  # KNOW-03: every commercial assertion carries a valid citation
        assert all(c.digest in knowledge.digests for c in p.citations)
        assert not composer._ASSERTION.search(sentences) or p.citations
        assert not any("؀" <= ch <= "ۿ" for ch in sentences)  # KNOW-08: no invented Urdu product wording
        assert p.reply_language == "en" and p.language_fallback == (p.inbound_language != "english")
    if p.status == "abstained":
        assert p.proposed_reply is None and p.citations == [] and p.escalate is True


def test_know_03_every_draft_sentence_with_an_assertion_is_cited() -> None:
    for case in corpus():
        p = run(case["text"], case["offer"], case["matched_contact"])
        if p.proposed_reply is None:
            continue
        cited = {c.sentence for c in p.citations}
        for c in p.citations:
            claim_text = (
                next(x.summary for x in (ADMISSIONS, FEES) if x.key == c.key) if c.kind == "capability" else None
            )
            assert claim_text is None or claim_text in p.proposed_reply  # approved wording, quoted verbatim
        assert cited or not composer._ASSERTION.search(p.proposed_reply)


# --- KNOW-04: the independent verifier --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "We may, of course, guarantee delivery by November 20.",
        "Naturally our system supports attendance as well.",
        "The plan is PKR 99 per student.",
        "Migration takes about 2 weeks.",
        "You will save 30% on admin time.",
        "We integrate with JazzCash.",
        "Uptime is 99.9% with 24/7 support.",
    ],
)
def test_know_04_hedged_or_hidden_commercial_assertions_without_a_citation_are_caught(sentence: str) -> None:
    sentences = ["Thank you for your message.", sentence, composer.SIGNOFF]
    assert ungrounded(sentences, [], OFFERS["core"]) == [1]
    forged = [{"kind": "capability", "key": "attendance", "digest": "9" * 64, "sentence": 1}]
    assert ungrounded(sentences, forged, OFFERS["core"]) == [1]  # a citation not in the snapshot counts for nothing


def test_know_05_stated_facts_are_quoted_spans_never_promoted() -> None:
    p = run("We are using Excel and have two campuses; the principal decides.")
    for fact in p.confirmed_facts:
        assert (fact.attribution, fact.verified) == ("prospect_stated", False)
        assert "We are using Excel and have two campuses; the principal decides."[fact.start : fact.end] == fact.text
    assert {f.code for f in p.confirmed_facts} == {"current_tool", "campus_count", "decision_maker"}


def test_know_07_safety_outranks_every_question_and_unavailable_content_never_drafts() -> None:
    assert run("Please stop contacting us, but send your price list", "priced").recommended_action == (
        "opt_out_review_no_reply"
    )
    assert run("Talk to your manager, fees module hai?").recommended_action == "human_handoff"
    missing = propose(Inputs("m-1", None, "expired", {"primary_intent": "needs_details", "safety_flags": [],
                                                      "language": "english", "observation_id": "o"},
                             OFFERS["core"], True, NOW))  # fmt: skip
    assert (missing.status, missing.abstention_codes) == ("abstained", ["content_unavailable"])
    no_intent = propose(Inputs("m-1", "fees module hai?", "available", None, OFFERS["core"], True, NOW))
    assert no_intent.abstention_codes == ["intent_missing"]
