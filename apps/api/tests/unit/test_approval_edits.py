"""P4.4 APPROVAL-02/04 (pure): edits decompose only into reviewed or currently grounded sentences."""

import pytest

from app.drafts import composer
from app.drafts.composer import DraftError
from tests.unit.test_draft_composer import CLAIMS, compose, fact

FACTS = [
    fact("f1", "public_workflow_signal", {"area": "fees", "signal": "fee voucher or bank challan process described"})
]
QUESTIONS = [("operator_autonomy", "Who usually decides on new administration tools for this campus?")]


def library() -> list[composer.Sentence]:
    return composer.candidates(facts=FACTS, usable={"f1"}, claims=CLAIMS, questions=QUESTIONS, snapshot_id="snap")


def test_rendered_draft_round_trips_and_keeps_grounding() -> None:
    sentences = compose(FACTS)
    parsed = composer.parse(composer.render(sentences), library())
    assert [(s.category, s.text, s.grounding) for s in parsed] == [(s.category, s.text, s.grounding) for s in sentences]


def test_drop_reorder_and_swap_are_allowed_and_whitespace_is_canonical() -> None:
    sentences = compose(FACTS)
    texts = [s.text for s in sentences if s.category != "observation"]
    texts[2], texts[3] = texts[3], texts[2]  # capability <-> question
    texts.insert(2, "Our team offers admissions intake module for schools.")  # the other published claim
    texts.remove("Our team offers fee tracking module for schools.")
    parsed = composer.parse("\n\n".join(texts) + "  \n", library())
    assert [s.category for s in parsed] == [
        "greeting",
        "identity",
        "capability",
        "question",
        "cta",
        "opt_out",
        "signoff",
    ]
    assert parsed[2].grounding["capability_code"] == "admissions_intake"
    assert composer.verify(parsed) == []


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        ("Assalam-o-Alaikum, We are the best software company in Lahore.", "UNGROUNDED_TEXT"),
        ("Assalam-o-Alaikum, <script>alert(1)</script>", "UNGROUNDED_TEXT"),
        ("Assalam-o-Alaikum, Our team offers fee tracking module for schools at PKR 5000.", "UNGROUNDED_TEXT"),
        ("Assalam-o-Alaikum, Your school still uses Excel.", "UNGROUNDED_TEXT"),
        ("Assalam-o-Alaikum,Assalam-o-Alaikum,", "UNGROUNDED_TEXT"),  # no separator
        ("Assalam-o-Alaikum, Assalam-o-Alaikum,", "DUPLICATE_SENTENCE"),
        ("   ", "UNGROUNDED_TEXT"),
    ],
)
def test_new_wording_injection_and_duplicates_are_refused(edit: str, code: str) -> None:
    with pytest.raises(DraftError) as excinfo:
        composer.parse(edit, library())
    assert excinfo.value.code == code


def test_unusable_fact_sentence_is_not_in_the_library() -> None:
    lib = composer.candidates(facts=FACTS, usable=set(), claims=CLAIMS, questions=[], snapshot_id=None)
    observation = "We noticed that your public page explains how fee vouchers or bank challans are paid."
    with pytest.raises(DraftError):
        composer.parse(f"Assalam-o-Alaikum, {observation}", lib)


def test_verifier_still_applies_to_parsed_edits() -> None:
    parsed = composer.parse("Assalam-o-Alaikum, If it would help, could we share a short overview with you?", library())
    assert {"missing_sender_identity", "missing_opt_out"} <= set(composer.verify(parsed))


def test_canonical_text_is_nfc_and_whitespace_collapsed() -> None:
    assert composer.canonical_text("Café  \n x") == "Café x"
