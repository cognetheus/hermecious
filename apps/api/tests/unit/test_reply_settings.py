"""P6.2 (KNOW-09, ADR-032): reply proposals cannot reach real conversations while P6.1 is not verified."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tests.factories import make_settings
from tests.unit.test_release_gate import PRODUCTION


def test_reply_proposals_are_off_by_default_and_fixtures_never_run_in_production() -> None:
    assert make_settings().reply_proposals == "off"
    assert make_settings(reply_proposals="fixtures").reply_proposals == "fixtures"  # test/dev: synthetic only
    with pytest.raises(ValidationError, match="HERMECIOUS_REPLY_PROPOSALS"):
        make_settings(**PRODUCTION, reply_proposals="fixtures")


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"intent_gate_signed_by": "Owner"},
        {"intent_gate_signed_by": "Owner", "intent_gate_signed_at": datetime.now(UTC) + timedelta(days=1)},
    ],
)
def test_inbound_proposals_need_a_named_human_sign_off_of_the_intent_gate(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="HERMECIOUS_INTENT_GATE_SIGNED_BY"):
        make_settings(reply_proposals="inbound", **extra)
    signed = make_settings(reply_proposals="inbound", intent_gate_signed_by="Owner",
                           intent_gate_signed_at=datetime.now(UTC) - timedelta(days=1))  # fmt: skip
    assert signed.reply_proposals == "inbound"
