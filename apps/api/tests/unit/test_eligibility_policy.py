"""P4.3 policy units (ELIG-01..08, 10): every branch of `eligibility-policy-1.0`, addresses and fixtures."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.contacts import addresses
from app.eligibility import fixtures, policy

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)  # Friday 12:00 Asia/Karachi


def permission(**over: Any) -> policy.PermissionFact:
    base = policy.PermissionFact(
        id="p1",
        status="verified",
        purpose="marketing",
        channel="whatsapp",
        business_name="CoderzHunt",
        consent_wording_version=policy.CONSENT_WORDING["marketing"],
        captured_at=NOW - timedelta(days=30),
        expires_at=NOW + timedelta(days=335),
        version=2,
    )
    return replace(base, **over)


TEMPLATE = policy.TemplateFact("fx_tpl_marketing_intro_v1", True, "approved", "marketing")


def inputs(**over: Any) -> policy.Inputs:
    base = policy.Inputs(
        purpose="marketing",
        now=NOW,
        kill_switch=False,
        suppressed=False,
        permissions=(permission(),),
        campaign_status="draft",
        template=TEMPLATE,
        human_owner_active=True,
    )
    return replace(base, **over)


def reasons(**over: Any) -> tuple[str, ...]:
    return policy.evaluate(inputs(**over)).reasons


def test_baseline_allows_simulation_only() -> None:
    decision = policy.evaluate(inputs())
    assert (decision.decision, decision.reasons, decision.live_send_authorized) == ("allow_for_simulation", (), False)
    assert (decision.policy_version, decision.permission_id, decision.permission_version) == (
        "eligibility-policy-1.0",
        "p1",
        2,
    )


def test_elig_01_no_opt_in_and_public_number_deny() -> None:
    assert reasons(permissions=()) == ("no_opt_in_permission",)


def test_elig_02_unverified_wrong_business_or_purpose_fail_closed() -> None:
    assert reasons(permissions=(permission(status="pending"),)) == ("permission_unverified",)
    assert reasons(permissions=(permission(status="rejected"),)) == ("no_opt_in_permission",)
    assert reasons(permissions=(permission(purpose="utility"),)) == ("purpose_not_covered",)
    assert reasons(permissions=(permission(business_name="Other Co"),)) == ("wrong_business",)
    assert reasons(permissions=(permission(channel="sms"),)) == ("no_opt_in_permission",)
    assert reasons(permissions=(permission(consent_wording_version="v0"),)) == ("consent_wording_outdated",)


def test_elig_03_only_a_verified_fixture_template_allows_and_never_live() -> None:
    operator_template = policy.TemplateFact("my_template", False, "approved", "marketing")
    assert reasons(template=operator_template) == ("template_unverified",)
    decision = policy.evaluate(inputs())
    assert decision.live_send_authorized is False


def test_elig_04_suppression_dominates() -> None:
    assert reasons(suppressed=True) == ("suppressed",)
    assert policy.evaluate(inputs(suppressed=True, purpose="service_reply")).decision == "deny"


def test_elig_05_revoked_expired_stale_and_future_proof() -> None:
    assert reasons(permissions=(permission(status="revoked"),)) == ("permission_revoked",)
    assert reasons(permissions=(permission(expires_at=NOW),)) == ("permission_expired",)
    assert reasons(permissions=(permission(captured_at=NOW - timedelta(days=366), expires_at=NOW + timedelta(1)),)) == (
        "proof_stale",
    )
    assert reasons(permissions=(permission(captured_at=NOW + timedelta(minutes=1)),)) == ("proof_future_dated",)


def test_elig_06_service_window_is_24h_and_never_marketing_consent() -> None:
    def reply(received: datetime, matches: bool = True) -> tuple[str, ...]:
        inbound = policy.InboundFact("fx_inbound_hello_v1", received, matches)
        return reasons(purpose="service_reply", permissions=(), template=None, campaign_status=None, inbound=inbound)

    assert reply(NOW - timedelta(hours=24) + timedelta(seconds=1)) == ()
    assert reply(NOW - timedelta(hours=24)) == ("service_window_closed",)
    assert reply(NOW - timedelta(hours=1), matches=False) == ("inbound_context_mismatch",)
    assert reply(NOW + timedelta(seconds=1)) == ("inbound_context_invalid",)
    assert reasons(purpose="service_reply", inbound=None) == ("no_inbound_context",)
    # The same inbound "hello" never stands in for a marketing opt-in.
    inbound = policy.InboundFact("fx_inbound_hello_v1", NOW - timedelta(hours=1), True)
    assert reasons(permissions=(), inbound=inbound) == ("no_opt_in_permission",)


def test_elig_07_templates() -> None:
    assert reasons(template=None) == ("template_missing",)
    assert reasons(template=replace(TEMPLATE, provider_status="pending")) == ("template_unverified",)
    assert reasons(template=replace(TEMPLATE, provider_status="rejected")) == ("template_rejected",)
    assert reasons(template=replace(TEMPLATE, category="utility")) == ("template_wrong_category",)
    assert reasons(template_blocker="fixture_requires_synthetic_account_outside_production") == (
        "fixture_requires_synthetic_account_outside_production",
    )


def test_elig_08_business_hours_timezone_and_caps_defer() -> None:
    # Friday 17:59:59 PKT is open; 18:00 is closed and defers to Saturday 09:00 PKT (04:00 UTC).
    open_edge = datetime(2026, 10, 23, 12, 59, 59, tzinfo=UTC)
    assert policy.evaluate(inputs(now=open_edge)).decision == "allow_for_simulation"
    closed = policy.evaluate(inputs(now=datetime(2026, 10, 23, 13, 0, tzinfo=UTC)))
    assert (closed.decision, closed.reasons) == ("defer", ("outside_business_hours",))
    assert closed.next_window_at == datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    # Saturday after hours -> Monday 09:00 PKT (Sunday is closed).
    sunday = policy.evaluate(inputs(now=datetime(2026, 10, 24, 14, 0, tzinfo=UTC)))
    assert sunday.next_window_at == datetime(2026, 10, 26, 4, 0, tzinfo=UTC)
    # 08:59 PKT (03:59 UTC) is before opening on the same day.
    early = policy.evaluate(inputs(now=datetime(2026, 10, 23, 3, 59, tzinfo=UTC)))
    assert early.next_window_at == datetime(2026, 10, 23, 4, 0, tzinfo=UTC)
    capped = policy.evaluate(inputs(usage=policy.Usage(org_business_initiated_today=policy.DAILY_CAP)))
    assert (capped.decision, capped.reasons) == ("defer", ("daily_cap_reached",))
    assert capped.next_window_at == datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    recent = policy.evaluate(inputs(usage=policy.Usage(contact_last_business_initiated_at=NOW - timedelta(days=1))))
    assert (recent.decision, recent.reasons) == ("defer", ("contact_frequency_cap",))
    assert recent.next_window_at == NOW + timedelta(days=6)  # Thursday 12:00 PKT is open
    # A deny always beats a defer.
    assert policy.evaluate(inputs(now=datetime(2026, 10, 23, 13, 0, tzinfo=UTC), suppressed=True)).decision == "deny"
    # Service replies inside the window are not deferred by business hours.
    inbound = policy.InboundFact("fx", datetime(2026, 10, 23, 12, 0, tzinfo=UTC), True)
    late_reply = inputs(
        now=datetime(2026, 10, 23, 13, 0, tzinfo=UTC), purpose="service_reply", inbound=inbound, campaign_status=None
    )
    assert policy.evaluate(late_reply).decision == "allow_for_simulation"


def test_elig_10_kill_switch_pause_campaign_gate_and_owner() -> None:
    assert reasons(kill_switch=True) == ("kill_switch_engaged",)
    assert reasons(campaign_status="paused", campaign_blockers=("campaign_paused",)) == ("campaign_paused",)
    assert reasons(campaign_status="cancelled") == ("campaign_cancelled",)
    assert reasons(campaign_status=None) == ("campaign_required",)
    assert reasons(campaign_blockers=("evidence_quality_gate_closed", "evidence_changed")) == (
        "evidence_quality_gate_closed",
        "evidence_changed",
    )
    assert reasons(human_owner_active=False) == ("no_active_human_owner",)
    # Precedence order is stable when several rules fail.
    assert reasons(kill_switch=True, suppressed=True, permissions=(), template=None) == (
        "kill_switch_engaged",
        "suppressed",
        "no_opt_in_permission",
        "template_missing",
    )


def test_addresses_canonical_digest_mask_and_rotation() -> None:
    assert addresses.canonical("0300 000-0101") == "+923000000101"
    assert addresses.canonical("+92 (300) 000 0101") == "+923000000101"
    assert addresses.canonical("0092 300 0000101") == "+923000000101"
    for bad in ("12345", "+0 300 000", "hello", "+92 300 000 0101 ext 4", "+9230000001011234567"):
        with pytest.raises(addresses.AddressError):
            addresses.canonical(bad)
    assert addresses.mask("+923000000101") == "+92 ••••••• 101"
    ring = addresses.parse_keyring("k2:" + "b" * 32 + ",k1:" + "a" * 32)
    assert ring.current[0] == "k2"
    both = addresses.digests(ring, "+923000000101")
    assert set(both) == {"k1", "k2"} and both["k1"] != both["k2"]
    assert addresses.digest(b"a" * 32, "+923000000101") == both["k1"]
    for bad_ring in ("", "k1:short", "K1:" + "a" * 32, "k1:" + "a" * 32 + ",k1:" + "b" * 32, "nocolon"):
        with pytest.raises(addresses.KeyringError):
            addresses.parse_keyring(bad_ring)


def test_fixtures_are_signed_and_tampering_is_ignored() -> None:
    assert fixtures.template("fx_tpl_marketing_intro_v1") is not None
    entry = fixtures.template("fx_tpl_marketing_pending_v1")
    assert entry is not None and entry["provider_status"] == "pending"
    forged = dict(entry) | {"provider_status": "approved"}
    assert fixtures._verified([forged]) == {}
    assert fixtures.template("my_template") is None
    hello = fixtures.inbound("fx_inbound_hello_v1")
    assert hello is not None and hello["received_at"] == datetime(2026, 10, 23, 5, 0, tzinfo=UTC)
    assert all(m["address"].startswith("+9200000") for m in fixtures._load()[1].values())
    assert "address" not in str(fixtures.catalogue())


@pytest.mark.parametrize("raw", ["+92۳۰۰۰۰۰۰۱۰۱", "03۰۰۰۰۰۰۱۰۱", "٠٣٠٠٠٠٠٠١٠١"])
def test_audit_eastern_digits_canonicalise_to_the_same_number(raw: str) -> None:
    """Urdu/Arabic digits must not create a second identity (duplicate check and suppression use the digest)."""
    assert addresses.canonical(raw) == "+923000000101"
    key = b"k" * 32
    assert addresses.digest(key, addresses.canonical(raw)) == addresses.digest(key, "+923000000101")
