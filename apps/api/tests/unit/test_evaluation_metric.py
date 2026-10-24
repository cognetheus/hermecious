"""P3.4 EVAL-05 (pure): the evidence quality decision and its honest denominator."""

import pytest

from app.evaluation.service import decide_result


@pytest.mark.parametrize(
    ("corpus", "supported", "total", "displayed", "result"),
    [
        ("OK", 18, 20, 0, "PASSED"),  # exactly 0.90
        ("OK", 27, 30, 0, "PASSED"),
        ("OK", 17, 20, 0, "FAILED"),  # 0.85
        ("OK", 26, 30, 0, "FAILED"),  # 0.8667
        ("OK", 0, 0, 0, "FAILED"),  # 0/0 never passes
        ("OK", 30, 30, 1, "FAILED"),  # a failed claim still displayed as fact
        ("OK", 20, 20, 0, "PASSED"),
        ("INSUFFICIENT_CORPUS", 29, 29, 0, "BLOCKED"),  # 29 real accounts is not a passing 29/30
        ("SYNTHETIC_CORPUS", 18, 20, 0, "BLOCKED"),  # fixtures prove the math, never the gate
    ],
)
def test_decision(corpus: str, supported: int, total: int, displayed: int, result: str) -> None:
    assert decide_result(corpus, supported, total, displayed)[0] == result


def test_reasons_carry_numerator_and_denominator() -> None:
    assert decide_result("OK", 18, 20, 0)[1] == "18/20 supported; no failures displayed"
    assert "0/0 never passes" in decide_result("OK", 0, 0, 0)[1]
